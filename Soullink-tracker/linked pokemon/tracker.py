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
from functools import wraps

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"
POKEDEX_FILE = ROOT / "pokemon_de.json"
PASSWORD_FILE = ROOT / "panel_password.txt"

# -----------------------------------------------------------------------------
# Passwortschutz fuer die Steuerungs-Seite (Overlay /obs bleibt frei)
# -----------------------------------------------------------------------------

def load_password() -> str:
    if PASSWORD_FILE.exists():
        pw = PASSWORD_FILE.read_text(encoding="utf-8").strip()
        if pw:
            return pw
    # Standardpasswort anlegen
    PASSWORD_FILE.write_text("soullink", encoding="utf-8")
    return "soullink"


PANEL_PASSWORD = load_password()


def require_auth(fn):
    """HTTP-Basic-Auth: schuetzt Steuerung + Schreibzugriffe. Benutzername egal."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if auth and auth.password == PANEL_PASSWORD:
            return fn(*args, **kwargs)
        return Response(
            "Login noetig", 401,
            {"WWW-Authenticate": 'Basic realm="Soullink Steuerung"'},
        )
    return wrapper

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
    "routeOrder": [],          # geordnete Liste der Routen-Namen (Tabellen-Zeilen)
    "locations": {},           # Fangort-Index (als String) -> Routen-Name
    "players": [
        {"name": "ZADOOS", "mons": [], "ignored": []},
        {"name": "AKUMA_FLO", "mons": [], "ignored": []},
    ],
}

_state_lock = threading.Lock()


def migrate_state(s: dict) -> dict:
    """Altes Modell (team/box/tot) -> neues Modell (mons mit status + route)."""
    s.setdefault("routeOrder", [])
    s.setdefault("locations", {})
    for p in s.get("players", []):
        p.setdefault("ignored", [])
        if "mons" not in p:
            mons = []
            for m in p.get("team", []):
                m.setdefault("status", "team"); m.setdefault("route", None); m.setdefault("met", None)
                mons.append(m)
            for m in p.get("box", []):
                m["status"] = "box"; m.setdefault("route", None); m.setdefault("met", None)
                mons.append(m)
            for m in p.get("tot", []):
                m["status"] = "dead"; m.setdefault("route", None); m.setdefault("met", None)
                mons.append(m)
            p["mons"] = mons
        p.pop("team", None); p.pop("box", None); p.pop("tot", None)
        for m in p["mons"]:
            m.setdefault("status", "team")
            m.setdefault("route", None)
            m.setdefault("met", None)
            m.setdefault("color", None)
            m.setdefault("nickLocked", False)
    return s


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return migrate_state(json.loads(STATE_FILE.read_text(encoding="utf-8")))
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

    GRUNDSATZ - der Sync mischt NICHTS um. Du behaeltst volle manuelle Kontrolle.
    Automatisch passiert nur:
    - NEU gefangenes Pokemon (unbekannte PID) -> ans Ende vom Team.
    - Bekanntes Pokemon -> Level/Name/Art werden an seinem Platz aktualisiert
      (egal ob Team/Box/Friedhof). Reihenfolge bleibt wie du sie gesetzt hast.
    - Faellt ein Team-Pokemon im Kampf (HP=0) -> ab in den Friedhof.
    Alles andere (Box, Loeschen, Tot-machen des Partners) ist MANUELL und wird
    vom Sync NICHT rueckgaengig gemacht. Geloeschte Pokemon (ignored) kommen
    nicht zurueck.
    """
    changed = False
    with _state_lock:
        p = STATE["players"][player_index]
        p.setdefault("mons", [])
        p.setdefault("ignored", [])

        # Neues Spiel erkennen: andere Trainer-ID (OTID) -> frischer Spielstand/ROM.
        # Haeufigste OTID der Party = deine eigene; weicht sie vom gespeicherten
        # Wert ab, war das ein anderer Spielstand -> alten Run leeren.
        otids = [raw.get("otid") for raw in party if raw.get("otid") is not None]
        if otids:
            game_otid = max(set(otids), key=otids.count)
            if p.get("otid") is not None and game_otid != p.get("otid"):
                p["mons"] = []
                p["ignored"] = []
                changed = True
            p["otid"] = game_otid

        ignored = set(p["ignored"])
        locations = STATE.setdefault("locations", {})

        def find(pid):
            for m in p["mons"]:
                if m.get("pid") == pid:
                    return m
            return None

        current_pids = {raw.get("pid") for raw in party if raw.get("pid") is not None}

        for raw in party:
            pid = raw.get("pid")
            if pid is None or pid in ignored:
                continue
            species_id = raw["species"]
            de_name = DEX_BY_ID.get(species_id, {}).get("de", f"#{species_id}")
            game_nick = (raw.get("nick") or "").strip()
            dead = bool(raw.get("dead"))
            met = raw.get("met")
            intern = raw.get("intern")
            m = find(pid)

            if m:
                # Diagnose: interne Spiel-Nummer mitfuehren
                if intern is not None and m.get("intern") != intern:
                    m["intern"] = intern; changed = True
                # Stats am Platz aktualisieren - Status/Route/Reihenfolge bleiben manuell
                if not m.get("speciesLocked") and m.get("id") != species_id:
                    m["id"] = species_id; m["de"] = de_name; changed = True
                if m.get("lvl") != raw["level"]:
                    m["lvl"] = raw["level"]; changed = True
                if m.get("met") is None and met is not None:
                    m["met"] = met; changed = True
                if not m.get("nickLocked"):
                    newnick = game_nick or de_name
                    if m.get("nick") != newnick:
                        m["nick"] = newnick; changed = True
                # Auto-Status nur wenn nicht manuell gesperrt
                if not m.get("statusLocked"):
                    if dead:
                        # Kampf-Tod: nur ein Team-Pokemon faellt in den Friedhof
                        if m.get("status") == "team":
                            m["status"] = "dead"; changed = True
                    else:
                        # Im Spiel-Team -> Status Team (eingewechselt)
                        if m.get("status") != "team":
                            m["status"] = "team"; changed = True
            else:
                # Neu gefangen -> Route automatisch, falls Fangort bekannt
                auto_route = locations.get(str(met)) if met is not None else None
                entry = {"id": species_id, "de": de_name, "intern": intern,
                         "nick": (game_nick or de_name), "lvl": raw["level"],
                         "pid": pid, "nickLocked": False, "color": None,
                         "met": met, "route": auto_route,
                         "status": "dead" if dead else "team"}
                p["mons"].append(entry)
                changed = True

        # Ausgewechselt: war im Team, ist aber nicht mehr in der Spiel-Party -> Box
        for m in p["mons"]:
            if (m.get("status") == "team"
                    and not m.get("statusLocked")
                    and m.get("pid") not in current_pids):
                m["status"] = "box"; changed = True

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
@require_auth
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
@require_auth
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
body { font-family: system-ui, 'Segoe UI', sans-serif; background:#0e1016; color:#eef; margin:0; padding:22px; max-width:1200px; margin:0 auto; }
.apphead h1 { margin:0 0 12px; font-size:1.7em; letter-spacing:.5px; }
h2 { margin:0 0 10px; font-size:1.1em; color:#cfe; }
.pnames { display:flex; gap:14px; margin-bottom:18px; }
.pnames input { flex:1; font-size:1.05em; font-weight:600; background:#171a25; border:1px solid #2a2f40; color:#fff; padding:10px 12px; border-radius:10px; }
.pnames input:first-child { border-left:4px solid #3b82f6; }
.pnames input:last-child  { border-left:4px solid #ef4444; }
.toolbar { display:flex; gap:8px; align-items:center; margin-bottom:18px; }
.toolbar input.route-add { flex:1; background:#171a25; border:1px solid #2a2f40; color:#eee; padding:10px 12px; border-radius:10px; }
button { background:#2b6cb0; border:none; color:#fff; padding:8px 12px; border-radius:8px; cursor:pointer; font-size:0.9em; line-height:1; }
button.sec { background:#333a4e; }
button.danger { background:#7a2a2a; }
button:hover { filter:brightness(1.15); }

/* "Gerade gefangen" Panel */
.unassigned { display:none; margin-bottom:22px; padding:14px 16px; border:1px solid #b4793c;
  background:linear-gradient(180deg,#241a10,#181a24); border-radius:14px; }
.unassigned.show { display:block; }
.ua-grid { display:grid; grid-template-columns:1fr 1fr; gap:14px; }
.ua-name { font-weight:700; margin-bottom:6px; color:#bcd; }
.ua-grid .ua-col:first-child .ua-name { color:#7ab0ff; }
.ua-grid .ua-col:last-child  .ua-name { color:#ff8a8a; }

table.routes { width:100%; border-collapse:separate; border-spacing:0 8px; }
table.routes th { text-align:left; padding:6px 10px; color:#8fa3c0; font-size:.8em; text-transform:uppercase; letter-spacing:.6px; }
table.routes th:nth-child(2){ color:#7ab0ff; }
table.routes th:nth-child(3){ color:#ff8a8a; }
table.routes td { padding:8px; vertical-align:top; width:38%; background:#141722; }
table.routes td:first-child { width:24%; border-radius:10px 0 0 10px; }
table.routes td:last-child { border-radius:0 10px 10px 0; }
.routecell { display:flex; align-items:center; gap:8px; }
.rnum { background:#222838; color:#cdd; min-width:26px; height:26px; border-radius:50%; display:inline-flex;
  align-items:center; justify-content:center; font-weight:700; font-size:.85em; flex:none; }
.routename { font-weight:700; flex:1; }
.rowtools { display:flex; gap:4px; opacity:.55; }
.routecell:hover .rowtools { opacity:1; }
.rowtools button { font-size:0.7em; padding:5px 7px; }
.cell-empty { color:#4a5066; font-style:italic; font-size:.85em; }

.card { position:relative; background:#1b1f2b; border-radius:10px; padding:9px; border-left:6px solid #444; }
.linkbadge { position:absolute; top:-9px; right:-9px; min-width:26px; height:26px; padding:0 5px; border-radius:13px;
  color:#fff; font-weight:800; font-size:.9em; display:flex; align-items:center; justify-content:center;
  border:2px solid #0e1016; box-shadow:0 1px 4px rgba(0,0,0,.5); }
.card.dead, .card.lost { opacity:0.5; }
.card.lost { filter:grayscale(1); }
.card .top { display:flex; align-items:center; gap:10px; }
.card img { width:54px; height:54px; image-rendering:pixelated; flex:none; }
.card .nick { font-weight:700; background:transparent; border:none; border-bottom:1px dashed transparent; color:#fff; font-size:1.02em; width:100%; padding:1px 0; }
.card .nick:focus { outline:none; border-bottom-color:#3b82f6; }
.card .nick.locked { color:#ffd479; }
.card .species { color:#8a93a8; font-size:0.82em; margin-top:3px; }
.species-edit.locked { color:#ffd479; }
.intern { color:#566; font-size:.8em; margin-left:6px; font-family:monospace; }
.card .ctrl { display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; align-items:center; }
.statusbtn { font-size:0.72em; padding:4px 8px; border-radius:6px; background:#2a3042; border:none; color:#cdd; cursor:pointer; }
.statusbtn.active.team { background:#2b8a3e; color:#fff; }
.statusbtn.active.box { background:#2b6cb0; color:#fff; }
.statusbtn.active.dead { background:#b03030; color:#fff; }
.statusbtn.active.lost { background:#666; color:#fff; }
.lvl { width:50px; background:#0e1016; border:1px solid #2a2f40; color:#eee; border-radius:4px; padding:2px 4px; }
.cards { display:flex; flex-wrap:wrap; gap:10px; }
.unassigned .card { width:260px; border-left-color:#d98a45; }
select.routesel { background:#0e1016; border:1px solid #2a2f40; color:#eee; border-radius:6px; padding:4px; font-size:0.8em; max-width:130px; }
.hint { color:#6b7488; font-size:0.82em; margin-top:26px; line-height:1.6; }
.hint code { background:#000; padding:2px 6px; border-radius:4px; color:#9cc; }
.drag { cursor:grab; color:#556; user-select:none; font-size:1.1em; }
</style>
</head>
<body>
<header class="apphead">
  <h1>🔗 Soullink Tracker</h1>
  <div class="pnames" id="pnames"></div>
</header>

<div class="toolbar">
  <input class="route-add" id="routeInput" placeholder="Neue Route hinzufuegen (z.B. Route 101) und Enter" onkeydown="if(event.key==='Enter')addRoute()">
  <button onclick="addRoute()">+ Route</button>
  <button class="sec" title="Alle gefangenen Pokemon loeschen (Routen + Namen bleiben)" onclick="newGame()">🆕 Neues Spiel</button>
  <button class="danger" title="ALLES loeschen inkl. Routen" onclick="wipeAll()">🗑️ Komplett leeren</button>
</div>

<section class="unassigned" id="unassigned"></section>

<table class="routes">
  <thead><tr id="thead"></tr></thead>
  <tbody id="tbody"></tbody>
</table>

<p class="hint">OBS-Overlay: <code id="obsurl"></code><br>
Neueste Route steht oben. Gleiche Route bei beiden = gelinktes Paar (gleiche Nummer im Overlay).<br>
Falscher Sprite? Auf das Bild oder den Art-Namen klicken und richtige Art waehlen.</p>

<script>
const SPRITE = id => `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${id}.png`;
let state = null;
let dragRi = null;

// location.origin enthaelt KEINE eingebetteten Login-Daten -> fetch funktioniert
// auch wenn die Seite per http://user:pass@host geoeffnet wurde.
const API = location.origin;
async function load(){ state = await (await fetch(API+'/api/state')).json(); render(); }
async function save(){
  try{
    const r = await fetch(API+'/api/update',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(state)});
    if(!r.ok) console.error('Speichern fehlgeschlagen:', r.status);
  }catch(e){ console.error('Speichern fehlgeschlagen:', e); }
}

function ensure(){
  state.routeOrder = state.routeOrder || [];
  state.locations = state.locations || {};
  state.players.forEach(p=>{ p.mons = p.mons||[]; p.ignored = p.ignored||[]; });
}

function render(){
  ensure();
  const pn = document.getElementById('pnames'); pn.innerHTML='';
  state.players.forEach((p,pi)=>{
    const inp=document.createElement('input'); inp.value=p.name;
    inp.oninput=()=>{ state.players[pi].name=inp.value; save(); };
    pn.appendChild(inp);
  });
  document.getElementById('thead').innerHTML='<th>Route</th>'+state.players.map(p=>`<th>${escapeHtml(p.name)}</th>`).join('');
  const tb=document.getElementById('tbody'); tb.innerHTML='';
  // Neueste Route oben (von unten nach oben), Nummer bleibt aber stabil (= Reihenfolge im Overlay)
  state.routeOrder.map((route,ri)=>({route,ri})).reverse().forEach(({route,ri})=>{
    const tr=document.createElement('tr');
    let html=`<td><div class="routecell">
      <span class="drag" draggable="true" data-ri="${ri}" title="Ziehen zum Sortieren">&#10303;</span>
      <span class="rnum" style="background:${linkColor(route)};color:#fff">${ri+1}</span>
      <span class="routename">${escapeHtml(route)}</span>
      <span class="rowtools">
        <button class="sec" title="Umbenennen" onclick="renameRoute(${ri})">&#9998;</button>
        <button class="danger" title="Route loeschen" onclick="delRoute(${ri})">&#128465;</button>
      </span></div></td>`;
    state.players.forEach((p,pi)=>{
      const mon=p.mons.find(m=>m.route===route);
      html+=`<td>${mon?cardHtml(pi,mon):`<span class="cell-empty">&mdash; noch nichts gefangen &mdash;</span>`}</td>`;
    });
    tr.innerHTML=html; tb.appendChild(tr);
  });
  tb.querySelectorAll('.drag').forEach(h=>h.addEventListener('dragstart',()=>{ dragRi=+h.dataset.ri; }));
  tb.querySelectorAll('tr').forEach((tr,ri)=>{
    tr.addEventListener('dragover',e=>e.preventDefault());
    tr.addEventListener('drop',e=>{ e.preventDefault(); if(dragRi!=null&&dragRi!==ri){ const r=state.routeOrder.splice(dragRi,1)[0]; state.routeOrder.splice(ri,0,r); dragRi=null; save(); render(); }});
  });
  renderUnassigned();
  document.getElementById('obsurl').textContent = location.origin+'/obs';
}

// Jede Route bekommt eine feste Nummer + Farbe. Beide Pokemon auf derselben
// Route teilen Nummer und Farbe -> man sieht sofort, was gelinkt ist.
const LINKCOLORS=['#3b82f6','#ef4444','#22c55e','#eab308','#a855f7','#ec4899','#14b8a6','#f97316','#06b6d4','#84cc16','#f43f5e','#8b5cf6','#0ea5e9','#d946ef'];
function linkNum(route){ const i=state.routeOrder.indexOf(route); return i<0?null:(i+1); }
function linkColor(route){ const i=state.routeOrder.indexOf(route); return i<0?'#556':LINKCOLORS[i%LINKCOLORS.length]; }

function cardHtml(pi,m){
  const idx=state.players[pi].mons.indexOf(m);
  const st=m.status||'team';
  const col=m.color||linkColor(m.route);
  const ln=linkNum(m.route);
  return `<div class="card ${st}" style="border-left-color:${col}">
    ${ln?`<span class="linkbadge" style="background:${col}" title="Link-Nummer ${ln} - gleiches Pokemon beim Partner gehoert dazu">${ln}</span>`:''}
    <div class="top">
      <img src="${SPRITE(m.id)}" title="Klicken: Art/Sprite manuell aendern" style="cursor:pointer" onclick="setSpecies(${pi},${idx})">
      <div style="flex:1">
        <input class="nick ${m.nickLocked?'locked':''}" value="${escapeHtml(m.nick)}" onchange="setNick(${pi},${idx},this.value)">
        <div class="species"><span class="species-edit ${m.speciesLocked?'locked':''}" title="Klicken: Art/Sprite manuell aendern" style="cursor:pointer;text-decoration:underline dotted" onclick="setSpecies(${pi},${idx})">${escapeHtml(m.de)}</span>${m.speciesLocked?` <button class="statusbtn" title="Art folgt wieder automatisch dem Spiel" onclick="unlockSpecies(${pi},${idx})">🔒</button>`:''} &middot; Lv <input class="lvl" type="number" value="${m.lvl}" onchange="setLvl(${pi},${idx},this.value)">${m.intern!=null?`<span class="intern" title="Interne Spiel-Nummer (zum Melden bei Fehlern)">#${m.intern}</span>`:''}</div>
      </div>
    </div>
    <div class="ctrl">
      ${sbtn(pi,idx,'team','Team',st)}${sbtn(pi,idx,'box','Box',st)}${sbtn(pi,idx,'dead','Tot',st)}${sbtn(pi,idx,'lost','Verloren',st)}
      ${m.statusLocked?`<button class="statusbtn" title="Status folgt wieder automatisch dem Spiel" onclick="unlockStatus(${pi},${idx})">🔒</button>`:''}
      <input type="color" value="${m.color||'#888888'}" onchange="setColor(${pi},${idx},this.value)" style="width:22px;height:22px;border:none;background:none;cursor:pointer">
      ${routeSel(pi,idx,m)}
      <button class="danger" style="font-size:0.7em" onclick="del(${pi},${idx})">X</button>
    </div>
  </div>`;
}
function sbtn(pi,idx,val,label,cur){ return `<button class="statusbtn ${val} ${cur===val?'active':''}" onclick="setStatus(${pi},${idx},'${val}')">${label}</button>`; }
function routeSel(pi,idx,m){
  const opts=`<option value="">&mdash; Route &mdash;</option>`+state.routeOrder.map(r=>`<option ${m.route===r?'selected':''}>${escapeHtml(r)}</option>`).join('');
  return `<select class="routesel" onchange="setRoute(${pi},${idx},this.value)">${opts}</select>`;
}

function renderUnassigned(){
  const root=document.getElementById('unassigned'); root.innerHTML='';
  const has=state.players.some(p=>p.mons.some(m=>!m.route));
  if(!has){ root.classList.remove('show'); return; }
  root.classList.add('show');
  let html='<h2>🆕 Gerade gefangen &mdash; Route zuweisen</h2><div class="ua-grid">';
  state.players.forEach((p,pi)=>{
    const list=p.mons.filter(m=>!m.route);
    html+=`<div class="ua-col"><div class="ua-name">${escapeHtml(p.name)}</div><div class="cards">`;
    if(list.length){ list.forEach(m=>{ html+=cardHtml(pi,m); }); }
    else { html+='<span class="cell-empty">&mdash;</span>'; }
    html+='</div></div>';
  });
  html+='</div>';
  root.innerHTML=html;
}

function addRoute(){
  const inp=document.getElementById('routeInput'); const v=inp.value.trim();
  if(!v) return; if(!state.routeOrder.includes(v)) state.routeOrder.push(v);
  inp.value=''; save(); render();
}
function newGame(){
  if(!confirm('Neues Spiel: ALLE gefangenen Pokemon loeschen?\\n(Routen und Spielernamen bleiben erhalten.)')) return;
  state.players.forEach(p=>{ p.mons=[]; p.ignored=[]; });
  save(); render();
}
function wipeAll(){
  if(!confirm('Komplett leeren: alle Pokemon UND alle Routen loeschen?')) return;
  state.routeOrder=[]; state.locations={};
  state.players.forEach(p=>{ p.mons=[]; p.ignored=[]; });
  save(); render();
}
function renameRoute(ri){
  const old=state.routeOrder[ri]; const v=prompt('Route umbenennen:',old); if(!v||v===old) return;
  state.routeOrder[ri]=v;
  state.players.forEach(p=>p.mons.forEach(m=>{ if(m.route===old)m.route=v; }));
  Object.keys(state.locations).forEach(k=>{ if(state.locations[k]===old)state.locations[k]=v; });
  save(); render();
}
function delRoute(ri){
  const r=state.routeOrder[ri];
  if(!confirm(`Route "${r}" entfernen? Pokemon kommen zu "Noch zuzuordnen".`)) return;
  state.routeOrder.splice(ri,1);
  state.players.forEach(p=>p.mons.forEach(m=>{ if(m.route===r)m.route=null; }));
  save(); render();
}
function setNick(pi,idx,v){ const m=state.players[pi].mons[idx]; m.nick=v; m.nickLocked=true; save(); render(); }
function setLvl(pi,idx,v){ state.players[pi].mons[idx].lvl=parseInt(v)||0; save(); }
function setColor(pi,idx,v){ state.players[pi].mons[idx].color=v; save(); render(); }
function setStatus(pi,idx,v){ const m=state.players[pi].mons[idx]; m.status=v; m.statusLocked=true; save(); render(); }
function unlockStatus(pi,idx){ const m=state.players[pi].mons[idx]; m.statusLocked=false; save(); render(); }
async function setSpecies(pi,idx){
  const q=prompt('Welches Pokemon ist das wirklich? (deutscher Name)');
  if(!q) return;
  let hits;
  try{ hits=await (await fetch(API+'/api/pokedex?q='+encodeURIComponent(q))).json(); }
  catch(e){ alert('Suche fehlgeschlagen.'); return; }
  if(!hits||!hits.length){ alert('Keine Art gefunden fuer "'+q+'".'); return; }
  let pick=hits[0];
  if(hits.length>1){
    const list=hits.slice(0,12).map((h,i)=>(i+1)+') '+h.de).join('\n');
    const sel=prompt('Mehrere Treffer - Nummer waehlen:\n'+list,'1');
    const n=parseInt(sel); if(!n||n<1||n>hits.length) return; pick=hits[n-1];
  }
  const m=state.players[pi].mons[idx];
  m.id=pick.id; m.de=pick.de; m.speciesLocked=true;
  if(!m.nickLocked) m.nick=pick.de;
  save(); render();
}
function unlockSpecies(pi,idx){ const m=state.players[pi].mons[idx]; m.speciesLocked=false; save(); render(); }
function setRoute(pi,idx,v){
  const m=state.players[pi].mons[idx];
  m.route = v||null;
  if(v && m.met!=null) state.locations[String(m.met)]=v;
  save(); render();
}
function del(pi,idx){
  const m=state.players[pi].mons[idx];
  if(!confirm('Pokemon loeschen?')) return;
  if(m.pid!=null){ state.players[pi].ignored=state.players[pi].ignored||[]; if(!state.players[pi].ignored.includes(m.pid)) state.players[pi].ignored.push(m.pid); }
  state.players[pi].mons.splice(idx,1); save(); render();
}
function escapeHtml(s){ return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }

const ev=new EventSource(API+'/events');
ev.onmessage=e=>{ const inc=JSON.parse(e.data); const a=document.activeElement; const typing=a&&(a.tagName==='INPUT'||a.tagName==='SELECT'); state=inc; if(!typing) render(); };
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
.slot { position:absolute; display:flex; align-items:center; justify-content:center; border:3px solid transparent; border-radius:10px; }
.slot img { max-width:100%; max-height:100%; image-rendering: pixelated; transition: opacity .3s, filter .3s; }
.slot.dead img { opacity:0.25; filter: grayscale(1); }
.slot .badge { position:absolute; top:-8px; left:-8px; min-width:24px; height:24px; padding:0 4px;
  background:#222; color:#fff; border:2px solid #fff; border-radius:12px; font-size:16px; font-weight:bold;
  display:flex; align-items:center; justify-content:center; text-shadow:1px 1px 0 #000; }
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

// REIHE = ROUTE. Beide Spieler teilen sich pro Route eine Reihe -> das gelinkte
// Paar steht IMMER nebeneinander. Tote bleiben ausgegraut an ihrem Platz stehen
// (nichts verrutscht). Eine Reihe verschwindet erst, wenn beide Pokemon
// manuell in Box/Verloren sind oder geloescht wurden.
const LINKCOLORS=['#3b82f6','#ef4444','#22c55e','#eab308','#a855f7','#ec4899','#14b8a6','#f97316','#06b6d4','#84cc16','#f43f5e','#8b5cf6','#0ea5e9','#d946ef'];
const SHOWN = s => { s = s || 'team'; return s === 'team' || s === 'dead'; };

function buildRows(state) {
  const order = state.routeOrder || [];
  const monOn = (pi, route) => (state.players[pi].mons || []).find(m => m.route === route && SHOWN(m.status));
  const rows = [];
  // Zuerst: Routen mit mindestens einem sichtbaren Pokemon (feste Reihenfolge)
  order.forEach((route, ri) => {
    const m1 = monOn(0, route), m2 = monOn(1, route);
    if (m1 || m2) rows.push({ m1, m2, num: ri + 1, color: LINKCOLORS[ri % LINKCOLORS.length] });
  });
  // Danach: noch nicht zugeordnete Team-Pokemon (ohne Route), pro Spieler aufgefuellt
  const un = pi => (state.players[pi].mons || []).filter(m => !m.route && SHOWN(m.status));
  const u1 = un(0), u2 = un(1);
  for (let i = 0; i < Math.max(u1.length, u2.length); i++)
    rows.push({ m1: u1[i], m2: u2[i], num: null, color: null });
  return rows.slice(0, CFG.rows);
}

function render(state) {
  const root = document.getElementById('root');
  root.innerHTML = '';
  buildRows(state).forEach((row, i) => {
    [['p1', row.m1], ['p2', row.m2]].forEach(([side, m]) => {
      if (m) {
        const col = m.color || row.color;
        const border = col ? `border-color:${col};` : '';
        const badge = (row.num != null)
          ? `<span class="badge" style="${col ? `background:${col};` : ''}">${row.num}</span>` : '';
        const dead = (m.status === 'dead') ? ' dead' : '';
        root.insertAdjacentHTML('beforeend',
          `<div class="slot ${side}${dead}" style="${slotStyle(i, side)}${border}">${badge}<img src="${SPRITE(m.id)}" alt="${escapeHtml(m.nick)}"></div>`);
      } else if (document.body.classList.contains('debug')) {
        root.insertAdjacentHTML('beforeend', `<div class="slot ${side}" style="${slotStyle(i, side)}"></div>`);
      }
    });
  });
}

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
