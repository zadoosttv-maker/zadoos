"""
Soullink-Tracker (Duo) mit OBS-Overlay.

Start:
    pip install flask requests
    python tracker.py

Dann im Browser:
    http://127.0.0.1:5000/          -> Steuerung (Team verwalten)
    http://127.0.0.1:5000/obs       -> Overlay-URL fuer OBS Browser-Quelle
"""
from __future__ import annotations

import json
import queue
import threading
import time
from pathlib import Path
from typing import Any

import requests
from flask import Flask, Response, jsonify, render_template_string, request

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"
POKEDEX_FILE = ROOT / "pokemon_de.json"

# -----------------------------------------------------------------------------
# Pokedex (deutsche Namen) - wird beim ersten Start aus PokeAPI geladen
# -----------------------------------------------------------------------------

def build_pokedex() -> list[dict]:
    """Holt alle Pokemon-Spezies + deutsche Namen aus PokeAPI."""
    print("[Pokedex] Erstanlage - lade deutsche Pokemon-Namen von PokeAPI ...")
    species_list = requests.get(
        "https://pokeapi.co/api/v2/pokemon-species?limit=2000", timeout=30
    ).json()["results"]

    out: list[dict] = []
    total = len(species_list)
    for i, sp in enumerate(species_list, 1):
        try:
            data = requests.get(sp["url"], timeout=30).json()
            name_de = next(
                (n["name"] for n in data["names"] if n["language"]["name"] == "de"),
                data["name"].capitalize(),
            )
            dex = data["id"]
            out.append({"id": dex, "de": name_de, "en": data["name"]})
            if i % 50 == 0 or i == total:
                print(f"  [{i}/{total}] {name_de}")
        except Exception as e:
            print(f"  Fehler bei {sp['name']}: {e}")
    out.sort(key=lambda x: x["de"].lower())
    return out


def load_pokedex() -> list[dict]:
    if POKEDEX_FILE.exists():
        return json.loads(POKEDEX_FILE.read_text(encoding="utf-8"))
    dex = build_pokedex()
    POKEDEX_FILE.write_text(json.dumps(dex, ensure_ascii=False, indent=2), encoding="utf-8")
    return dex


# -----------------------------------------------------------------------------
# State
# -----------------------------------------------------------------------------

DEFAULT_STATE: dict[str, Any] = {
    "players": [
        {"name": "Spieler 1", "team": [], "box": [], "tot": []},
        {"name": "Spieler 2", "team": [], "box": [], "tot": []},
    ],
}

_state_lock = threading.Lock()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_STATE))


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


STATE: dict = load_state()
POKEDEX: list[dict] = []
DEX_BY_ID: dict[int, dict] = {}


# -----------------------------------------------------------------------------
# Party-Sync: nimmt automatische Daten aus dem Spiel und mergt sie in STATE
# -----------------------------------------------------------------------------

def apply_party(player_index: int, party: list[dict]) -> bool:
    """Mergt eine Party (vom Lua-Script) in STATE.players[player_index].

    Regeln:
    - Der In-Game-Spitzname wird automatisch uebernommen (ihr benennt ja um).
    - Hat jemand den Namen manuell im Panel geaendert (nickLocked=True),
      bleibt dieser erhalten und wird NICHT vom Spiel ueberschrieben.
    - HP=0 -> Pokemon wird in 'tot' verschoben (Nuzlocke-Regel).
    - Verschwindet ein Pokemon aus der Party (HP>0) -> in 'box' verschieben.
    - Neue Pokemon erscheinen automatisch im Team.
    """
    changed = False
    with _state_lock:
        p = STATE["players"][player_index]
        old_team = p.get("team", [])

        # Vorhandenen Eintrag (egal ob Team/Box/Tot) per PID finden,
        # um manuelle Spitznamen-Sperre zu erhalten.
        def find_existing(pid):
            for lst in ("team", "box", "tot"):
                for m in p.get(lst, []):
                    if m.get("pid") == pid:
                        return m
            return None

        def resolve_nick(existing, game_nick, de_name):
            # Manueller Override gewinnt
            if existing and existing.get("nickLocked"):
                return existing.get("nick", de_name), True
            # Sonst: In-Game-Name, falls vorhanden, sonst deutscher Name
            game_nick = (game_nick or "").strip()
            return (game_nick or de_name), False

        new_team: list[dict] = []
        seen_pids: set[int] = set()

        for raw in party:
            pid = raw.get("pid")
            seen_pids.add(pid)
            species_id = raw["species"]
            de_name = DEX_BY_ID.get(species_id, {}).get("de", f"#{species_id}")
            existing = find_existing(pid)
            nick, locked = resolve_nick(existing, raw.get("nick"), de_name)

            if raw.get("dead"):
                # In Friedhof legen, nicht ins Team
                if not any(t.get("pid") == pid for t in p["tot"]):
                    p["tot"].append({"id": species_id, "de": de_name, "nick": nick,
                                     "lvl": raw["level"], "pid": pid, "nickLocked": locked})
                    changed = True
                continue

            new_team.append({
                "id": species_id, "de": de_name, "nick": nick,
                "lvl": raw["level"], "pid": pid, "nickLocked": locked,
            })

        # Pokemon, die vorher im Team waren und jetzt weg sind (und nicht tot) -> Box
        for old in old_team:
            opid = old.get("pid")
            if opid and opid not in seen_pids:
                if any(t.get("pid") == opid for t in p["tot"]):
                    continue  # schon tot
                if any(b.get("pid") == opid for b in p["box"]):
                    continue  # schon Box
                p["box"].append(old)
                changed = True

        if new_team != old_team:
            p["team"] = new_team
            changed = True

        if changed:
            save_state(STATE)
    return changed


def watch_party_file(path: Path, player_index: int) -> None:
    """Hintergrund-Thread, der eine lokale party_local.json auf Aenderungen prueft."""
    last_mtime = 0.0
    while True:
        try:
            if path.exists():
                mt = path.stat().st_mtime
                if mt != last_mtime:
                    last_mtime = mt
                    data = json.loads(path.read_text(encoding="utf-8"))
                    if apply_party(player_index, data.get("party", [])):
                        broadcast()
        except Exception as e:
            print(f"[watch] {e}")
        time.sleep(0.5)

# -----------------------------------------------------------------------------
# SSE - Live-Update fuer OBS
# -----------------------------------------------------------------------------

_subscribers: list[queue.Queue] = []


def broadcast() -> None:
    payload = json.dumps(STATE, ensure_ascii=False)
    dead: list[queue.Queue] = []
    for q in _subscribers:
        try:
            q.put_nowait(payload)
        except Exception:
            dead.append(q)
    for q in dead:
        if q in _subscribers:
            _subscribers.remove(q)


# -----------------------------------------------------------------------------
# Flask
# -----------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/api/state", methods=["GET"])
def api_state():
    return jsonify(STATE)


@app.route("/api/pokedex", methods=["GET"])
def api_pokedex():
    q = request.args.get("q", "").strip().lower()
    if not q:
        return jsonify(POKEDEX[:50])
    hits = [p for p in POKEDEX if q in p["de"].lower() or q in p["en"].lower()]
    return jsonify(hits[:50])


@app.route("/api/update", methods=["POST"])
def api_update():
    global STATE
    new_state = request.get_json(force=True)
    with _state_lock:
        STATE = new_state
        save_state(STATE)
    broadcast()
    return jsonify({"ok": True})


@app.route("/api/party/<int:player_index>", methods=["POST"])
def api_party(player_index: int):
    """Wird vom mGBA-Lua-Script bzw. dem Remote-Agent fuer Spieler 2 aufgerufen."""
    if player_index not in (0, 1):
        return jsonify({"error": "player_index muss 0 oder 1 sein"}), 400
    data = request.get_json(force=True)
    if apply_party(player_index, data.get("party", [])):
        broadcast()
    return jsonify({"ok": True})


@app.route("/events")
def events():
    def stream():
        q: queue.Queue = queue.Queue()
        _subscribers.append(q)
        try:
            yield f"data: {json.dumps(STATE, ensure_ascii=False)}\n\n"
            while True:
                try:
                    msg = q.get(timeout=15)
                    yield f"data: {msg}\n\n"
                except queue.Empty:
                    yield ": ping\n\n"
        finally:
            if q in _subscribers:
                _subscribers.remove(q)

    return Response(stream(), mimetype="text/event-stream")


@app.route("/")
def control():
    return render_template_string(CONTROL_HTML)


@app.route("/obs")
def obs():
    return render_template_string(OBS_HTML)


# -----------------------------------------------------------------------------
# HTML Templates
# -----------------------------------------------------------------------------

CONTROL_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Soullink Tracker - Steuerung</title>
<style>
* { box-sizing: border-box; }
body { font-family: system-ui, sans-serif; background:#1e1e2e; color:#eee; margin:0; padding:20px; }
h1 { margin-top:0; }
.players { display:grid; grid-template-columns:1fr 1fr; gap:20px; }
.player { background:#2a2a3e; padding:16px; border-radius:10px; }
.player input.name { width:100%; font-size:1.2em; background:#1e1e2e; border:1px solid #444; color:#eee; padding:6px; border-radius:6px; margin-bottom:10px; }
.section { margin-top:14px; }
.section h3 { margin:6px 0; font-size:0.95em; color:#aaa; text-transform:uppercase; letter-spacing:1px; }
.mon { display:flex; align-items:center; gap:8px; background:#1e1e2e; padding:6px; border-radius:6px; margin-bottom:6px; }
.mon img { width:48px; height:48px; image-rendering: pixelated; }
.mon .info { flex:1; }
.mon .info input { background:transparent; border:none; color:#eee; font-size:0.95em; width:100%; }
.mon .info input.nick { font-weight:bold; }
.mon .info input.lvl { width:60px; }
.mon .actions button { background:#444; border:none; color:#eee; padding:4px 8px; border-radius:4px; cursor:pointer; font-size:0.85em; margin-left:2px; }
.mon .actions button:hover { background:#666; }
.mon.dead { opacity:0.5; }
.mon.sel { outline:2px solid #6ad; }
.mon input.chk { width:18px; height:18px; flex:none; cursor:pointer; }
.mon .info input.nick.locked { color:#ffd479; }
.bulk { display:flex; gap:6px; align-items:center; margin:4px 0 8px; flex-wrap:wrap; font-size:0.85em; color:#aaa; }
.bulk button { background:#444; border:none; color:#eee; padding:4px 8px; border-radius:4px; cursor:pointer; }
.bulk button:hover { background:#666; }
.bulk button.danger { background:#7a2a2a; }
.add { display:flex; gap:6px; margin-top:8px; position:relative; }
.add input { flex:1; background:#1e1e2e; border:1px solid #444; color:#eee; padding:6px; border-radius:6px; }
.suggest { position:absolute; top:100%; left:0; right:0; background:#2a2a3e; border:1px solid #444; max-height:240px; overflow-y:auto; z-index:10; border-radius:6px; }
.suggest div { padding:6px 10px; cursor:pointer; display:flex; align-items:center; gap:8px; }
.suggest div:hover { background:#3a3a5e; }
.suggest img { width:32px; height:32px; image-rendering: pixelated; }
.hint { color:#888; font-size:0.85em; margin-top:20px; }
.hint code { background:#000; padding:2px 6px; border-radius:4px; }
</style>
</head>
<body>
<h1>Soullink Tracker</h1>
<div class="players" id="players"></div>
<p class="hint">OBS Browser-Quelle: <code id="obsurl"></code> &nbsp; | &nbsp; transparenter Hintergrund, empfohlene Groesse z.B. 900x500.</p>

<script>
const SPRITE = id => `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${id}.png`;
let state = null;

async function load() {
  state = await (await fetch('/api/state')).json();
  render();
}

async function save() {
  await fetch('/api/update', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(state)});
}

function render() {
  const root = document.getElementById('players');
  root.innerHTML = '';
  state.players.forEach((p, pi) => {
    const div = document.createElement('div');
    div.className = 'player';
    div.innerHTML = `
      <input class="name" value="${escapeHtml(p.name)}" data-pi="${pi}" oninput="state.players[${pi}].name=this.value; save()">
      <div class="section">
        <h3>Team (${p.team.length}/6)</h3>
        ${bulkBar(pi, 'team')}
        <div id="team-${pi}"></div>
        ${p.team.length < 6 ? addBox(pi, 'team') : ''}
      </div>
      <div class="section">
        <h3>Box</h3>
        ${bulkBar(pi, 'box')}
        <div id="box-${pi}"></div>
        ${addBox(pi, 'box')}
      </div>
      <div class="section">
        <h3>Friedhof</h3>
        ${bulkBar(pi, 'tot')}
        <div id="tot-${pi}"></div>
      </div>
    `;
    root.appendChild(div);
    renderList(pi, 'team', p.team);
    renderList(pi, 'box', p.box);
    renderList(pi, 'tot', p.tot);
  });
  document.getElementById('obsurl').textContent = location.origin + '/obs';
}

function addBox(pi, list) {
  return `
    <div class="add">
      <input placeholder="Pokemon suchen (deutsch) ..." oninput="suggest(this, ${pi}, '${list}')" onfocus="suggest(this, ${pi}, '${list}')">
      <div class="suggest" style="display:none"></div>
    </div>`;
}

async function suggest(inp, pi, list) {
  const box = inp.nextElementSibling;
  const q = inp.value.trim();
  const res = await (await fetch('/api/pokedex?q=' + encodeURIComponent(q))).json();
  box.innerHTML = '';
  box.style.display = res.length ? 'block' : 'none';
  res.forEach(p => {
    const d = document.createElement('div');
    d.innerHTML = `<img src="${SPRITE(p.id)}"><span>${p.de}</span>`;
    d.onclick = () => { addMon(pi, list, p); box.style.display='none'; inp.value=''; };
    box.appendChild(d);
  });
  setTimeout(() => document.addEventListener('click', ev => {
    if (!box.contains(ev.target) && ev.target !== inp) box.style.display = 'none';
  }, {once:true}), 0);
}

function addMon(pi, list, p) {
  // Manuell hinzugefuegt -> kein pid, Name gesperrt
  state.players[pi][list].push({id: p.id, de: p.de, nick: p.de, lvl: 5, nickLocked: true});
  save(); render();
}

// --- Multi-Select ---------------------------------------------------------
// selected[pi][list] = Set von Indizes
const selected = {};
function selKey(pi, list) { return `${pi}|${list}`; }
function getSel(pi, list) {
  const k = selKey(pi, list);
  if (!selected[k]) selected[k] = new Set();
  return selected[k];
}
function toggleSel(pi, list, mi, on) {
  const s = getSel(pi, list);
  if (on) s.add(mi); else s.delete(mi);
  render();
}

function bulkBar(pi, list) {
  const arr = state.players[pi][list] || [];
  const sel = getSel(pi, list);
  const n = sel.size;
  let btns = `<input type="checkbox" class="chk" ${n===arr.length&&arr.length>0?'checked':''} onclick="selAll(${pi},'${list}',this.checked)" title="Alle auswaehlen">
              <span>${n>0 ? n+' gewaehlt' : 'auswaehlen'}</span>`;
  if (n > 0) {
    if (list !== 'team') btns += `<button onclick="bulkMove(${pi},'${list}','team')">→ Team</button>`;
    if (list !== 'box')  btns += `<button onclick="bulkMove(${pi},'${list}','box')">→ Box</button>`;
    if (list !== 'tot')  btns += `<button class="danger" onclick="bulkMove(${pi},'${list}','tot')">→ Tot</button>`;
    btns += `<button class="danger" onclick="bulkDel(${pi},'${list}')">Loeschen</button>`;
    btns += `<button onclick="getSel(${pi},'${list}').clear(); render()">x</button>`;
  }
  return `<div class="bulk">${btns}</div>`;
}

function selAll(pi, list, on) {
  const arr = state.players[pi][list] || [];
  const s = getSel(pi, list);
  s.clear();
  if (on) arr.forEach((_, i) => s.add(i));
  render();
}
function bulkMove(pi, from, to) {
  const idx = [...getSel(pi, from)].sort((a,b)=>b-a);  // absteigend
  idx.forEach(i => {
    const m = state.players[pi][from].splice(i,1)[0];
    if (m) state.players[pi][to].push(m);
  });
  getSel(pi, from).clear();
  save(); render();
}
function bulkDel(pi, list) {
  if (!confirm(getSel(pi,list).size + ' Pokemon wirklich loeschen?')) return;
  const idx = [...getSel(pi, list)].sort((a,b)=>b-a);
  idx.forEach(i => state.players[pi][list].splice(i,1));
  getSel(pi, list).clear();
  save(); render();
}

function renderList(pi, list, arr) {
  const root = document.getElementById(`${list}-${pi}`);
  root.innerHTML = '';
  const sel = getSel(pi, list);
  arr.forEach((m, mi) => {
    const div = document.createElement('div');
    div.className = 'mon' + (list==='tot' ? ' dead' : '') + (sel.has(mi) ? ' sel' : '');
    div.innerHTML = `
      <input type="checkbox" class="chk" ${sel.has(mi)?'checked':''} onclick="toggleSel(${pi},'${list}',${mi},this.checked)">
      <img src="${SPRITE(m.id)}">
      <div class="info">
        <input class="nick ${m.nickLocked?'locked':''}" value="${escapeHtml(m.nick)}"
               title="${m.nickLocked?'Manuell gesperrt - wird nicht vom Spiel ueberschrieben':'Auto vom Spiel'}"
               onchange="setNick(${pi},'${list}',${mi},this.value)">
        <div style="display:flex; gap:6px; align-items:center;">
          <span style="color:#888; font-size:0.8em;">${escapeHtml(m.de)}</span>
          <span style="color:#888; font-size:0.8em;">Lv</span>
          <input class="lvl" type="number" value="${m.lvl}" onchange="state.players[${pi}].${list}[${mi}].lvl=parseInt(this.value)||0; save()">
          ${m.nickLocked ? `<button onclick="unlockNick(${pi},'${list}',${mi})" style="background:#444;border:none;color:#aaa;border-radius:4px;cursor:pointer;font-size:0.75em;" title="Wieder automatisch vom Spiel">auto</button>` : ''}
        </div>
      </div>
      <div class="actions">
        ${list!=='team' && state.players[pi].team.length < 6 ? `<button onclick="move(${pi},'${list}','team',${mi})">Team</button>` : ''}
        ${list!=='box' ? `<button onclick="move(${pi},'${list}','box',${mi})">Box</button>` : ''}
        ${list!=='tot' ? `<button onclick="kill(${pi},'${list}',${mi})" style="background:#7a2a2a">Tot</button>` : ''}
        <button onclick="del(${pi},'${list}',${mi})">X</button>
      </div>`;
    root.appendChild(div);
  });
}

function setNick(pi, list, mi, val) {
  const m = state.players[pi][list][mi];
  m.nick = val;
  m.nickLocked = true;   // manueller Name -> sperren
  save(); render();
}
function unlockNick(pi, list, mi) {
  state.players[pi][list][mi].nickLocked = false;
  save(); render();
}

function move(pi, from, to, mi) {
  const m = state.players[pi][from].splice(mi,1)[0];
  state.players[pi][to].push(m);
  save(); render();
}
function kill(pi, from, mi) {
  if (!confirm('Pokemon als tot markieren?')) return;
  move(pi, from, 'tot', mi);
}
function del(pi, list, mi) {
  if (!confirm('Wirklich loeschen?')) return;
  state.players[pi][list].splice(mi,1);
  save(); render();
}
function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

// Live-Updates vom Spiel auch im Panel anzeigen (nicht waehrend man tippt)
const ev = new EventSource('/events');
ev.onmessage = e => {
  const incoming = JSON.parse(e.data);
  const active = document.activeElement;
  const typing = active && (active.tagName === 'INPUT');
  state = incoming;
  if (!typing) render();
};

load();
</script>
</body>
</html>
"""

OBS_HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>Soullink OBS Overlay</title>
<style>
* { box-sizing: border-box; }
html, body { margin:0; padding:0; width:1920px; height:1080px; background: transparent; overflow:hidden; font-family: 'Segoe UI', system-ui, sans-serif; }
.slot { position:absolute; display:flex; align-items:center; justify-content:center; }
.slot img { max-width:100%; max-height:100%; image-rendering: pixelated; transition: opacity .3s, filter .3s; }
.slot.dead img { opacity:0.25; filter: grayscale(1); }
/* Hilfsraster zum Ausrichten: ?debug=1 anhaengen */
.debug .slot { outline: 2px dashed #0f0; }
.debug .slot.p2 { outline-color:#f0f; }
</style>
</head>
<body>
<div id="root"></div>

<script>
const SPRITE = id => `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${id}.png`;

// Slot-Positionen (an dein Overlay angepasst, 1920x1080).
// Ueber URL anpassbar:  /obs?x=820&y=160&slotW=85&slotH=85&rowGap=10&colGap=55&debug=1
const qs = new URLSearchParams(location.search);
const CFG = {
  x:       parseInt(qs.get('x'))       || 820,   // X des linken (blauen) Slots
  y:       parseInt(qs.get('y'))       || 165,   // Y des obersten Slots
  slotW:   parseInt(qs.get('slotW'))   || 85,
  slotH:   parseInt(qs.get('slotH'))   || 85,
  rowGap:  parseInt(qs.get('rowGap'))  || 10,    // vertikaler Abstand zwischen Reihen
  colGap:  parseInt(qs.get('colGap'))  || 45,    // horizontaler Abstand zwischen blau und rot
  rows:    parseInt(qs.get('rows'))    || 6,
};
if (qs.get('debug') === '1') document.body.classList.add('debug');

function slotStyle(row, side) {
  const x = CFG.x + (side === 'p2' ? CFG.slotW + CFG.colGap : 0);
  const y = CFG.y + row * (CFG.slotH + CFG.rowGap);
  return `left:${x}px; top:${y}px; width:${CFG.slotW}px; height:${CFG.slotH}px;`;
}

function render(state) {
  const root = document.getElementById('root');
  root.innerHTML = '';
  const p1 = state.players[0], p2 = state.players[1];
  for (let i = 0; i < CFG.rows; i++) {
    const m1 = p1.team[i], m2 = p2.team[i];
    // Linked-Pair-Logik: wenn EIN Partner tot ist -> beide grau
    const pairDead = (m1 && isDead(state, 0, m1)) || (m2 && isDead(state, 1, m2));
    if (m1) root.insertAdjacentHTML('beforeend',
      `<div class="slot p1 ${pairDead ? 'dead':''}" style="${slotStyle(i,'p1')}"><img src="${SPRITE(m1.id)}" alt="${escapeHtml(m1.nick)}"></div>`);
    if (m2) root.insertAdjacentHTML('beforeend',
      `<div class="slot p2 ${pairDead ? 'dead':''}" style="${slotStyle(i,'p2')}"><img src="${SPRITE(m2.id)}" alt="${escapeHtml(m2.nick)}"></div>`);
    // Leere Slots im Debug-Modus zeigen
    if (document.body.classList.contains('debug')) {
      if (!m1) root.insertAdjacentHTML('beforeend', `<div class="slot p1" style="${slotStyle(i,'p1')}"></div>`);
      if (!m2) root.insertAdjacentHTML('beforeend', `<div class="slot p2" style="${slotStyle(i,'p2')}"></div>`);
    }
  }
}
function isDead(state, pi, m) { return state.players[pi].tot.some(t => t === m); }

function escapeHtml(s) { return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

const ev = new EventSource('/events');
ev.onmessage = e => render(JSON.parse(e.data));
</script>
</body>
</html>
"""


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main() -> None:
    global POKEDEX, DEX_BY_ID
    POKEDEX = load_pokedex()
    DEX_BY_ID = {p["id"]: p for p in POKEDEX}
    print(f"[Pokedex] {len(POKEDEX)} Eintraege geladen.")

    # Lokalen Party-Watcher starten (Spieler 1 = du)
    local_party = ROOT / "party_local.json"
    t = threading.Thread(target=watch_party_file, args=(local_party, 0), daemon=True)
    t.start()
    print(f"[Watcher] Beobachte {local_party} fuer Spieler 1")

    print("\n  Steuerung:  http://127.0.0.1:5000/")
    print("  OBS-Quelle: http://127.0.0.1:5000/obs")
    print("  Remote-Endpoint fuer Spieler 2: POST http://<deine-ip>:5000/api/party/1\n")
    # host=0.0.0.0 damit Spieler 2 sich per LAN/Tunnel verbinden kann
    app.run(host="0.0.0.0", port=5000, threaded=True)


if __name__ == "__main__":
    main()
