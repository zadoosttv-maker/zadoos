# Pokémon Soullink Tracker (Duo)

Automatischer Live-Tracker für eine **Soullink-Nuzlocke** zu zweit, mit OBS-Overlay.
Liest das Team direkt aus dem mGBA-Emulator und aktualisiert das Overlay sofort —
ohne manuelles Klicken wenn ein Pokémon gefangen wird, stirbt oder in die Box wandert.

Aktuell unterstützt: **Pokémon Smaragd / Emerald** (Gen 3). Deutsche Pokémon-Namen.

## Features

- 🎮 **Auto-Erkennung** — mGBA Lua-Script liest das Team direkt aus dem RAM
- 📡 **Live-Updates** über Server-Sent Events — Overlay reagiert sofort
- 🔗 **Linked-Pair-Logik** — wenn ein Pokémon stirbt, werden beide Slots ausgegraut
- 🌐 **Remote-Support** — Spieler 2 kann auf einem anderen PC sein (ngrok/Tailscale)
- ✏️ **Manuelles Override** — Control-Panel für Spitznamen, Reihenfolge, manuelle Edits
- 🎲 **Randomizer-tauglich** — alle 386 Gen 1-3 Pokémon werden erkannt

## Voraussetzungen

- Windows (Linux/Mac sollte auch gehen, ungetestet)
- Python 3.10+
- [mGBA](https://mgba.io/) 0.10+ (mit Lua-Scripting)
- Pokémon Smaragd / Emerald ROM (nicht enthalten)

## Schnellstart (Host = Spieler 1)

```bash
git clone https://github.com/DEIN-NAME/soullink-tracker.git
cd soullink-tracker
pip install -r requirements.txt
python tracker.py
```

Beim ersten Start werden die deutschen Pokémon-Namen einmalig von PokéAPI geladen (~2 Min).

Dann:

1. Im Browser **http://127.0.0.1:5000/** öffnen — manuelle Steuerung
2. In OBS: **Browser-Quelle** hinzufügen, URL `http://127.0.0.1:5000/obs`, Größe **1920x1080**
3. In mGBA: `Werkzeuge → Scripting → Datei → Datei laden` → `mgba_smaragd.lua` auswählen
4. Dein Team erscheint automatisch im Overlay!

### Slot-Positionen feintunen

Das Overlay positioniert Sprites mit absoluten Pixel-Koordinaten. Über URL anpassbar:

```
http://127.0.0.1:5000/obs?x=860&y=200&slotW=78&slotH=78&rowGap=12&colGap=48&debug=1
```

`?debug=1` zeigt gestrichelte Rahmen zum Ausrichten. Wenn alles sitzt, weglassen.

## Setup für Spieler 2 (anderer PC)

Spieler 2 muss seine Team-Daten zum Tracker von Spieler 1 schicken. Siehe
[`INSTRUCTIONS_PLAYER2.md`](INSTRUCTIONS_PLAYER2.md) — Kurzfassung:

1. Spieler 1 startet Tracker + macht ihn per [ngrok](https://ngrok.com/) erreichbar (`ngrok http 5000`)
2. Spieler 1 schickt die ngrok-URL an Spieler 2
3. Spieler 2 startet `agent.py` mit der URL in `agent_config.json`
4. Spieler 2 lädt `mgba_smaragd.lua` in sein mGBA

## Datei-Übersicht

| Datei | Zweck |
|---|---|
| `tracker.py` | Flask-Server: Control-Panel, OBS-Overlay, SSE, Party-Sync |
| `mgba_smaragd.lua` | mGBA Lua-Script — liest Party aus Emerald-RAM |
| `agent.py` | Companion-Script für Spieler 2 (sendet Party an Host) |
| `start.bat` / `start_agent.bat` | Windows-Launcher zum Doppelklicken |
| `example_overlay/` | Beispiel-OBS-Overlay-Design |

## Funktionsweise

```
mGBA (Spieler 1) ──> mgba_smaragd.lua ──> party_local.json
                                              │
                                              ▼ (file watcher)
                                         tracker.py ──SSE──> OBS Browser-Quelle
                                              ▲
                                              │ POST /api/party/1
mGBA (Spieler 2) ──> lua ──> party_local.json ──> agent.py ──┘
                                            (via ngrok / Tailscale)
```

State wird in `state.json` gespeichert. Manuelle Edits (Spitznamen, Reihenfolge)
überleben Auto-Updates.

## Einschränkungen

- **Nur Gen 3** aktuell (Smaragd/Rubin/Saphir — nur Smaragd getestet)
- **Box-Erkennung** wird abgeleitet (Slot leer → Box, außer KP war 0 → Tot)
- ngrok Free-Plan wechselt die URL bei jedem Neustart

## Sprachen

- 🇬🇧 [English](README.md)
- 🇩🇪 [Deutsch (diese Datei)](README.de.md)

## Lizenz

[MIT](LICENSE) — mach was du willst, lass nur den Copyright-Hinweis drin.
