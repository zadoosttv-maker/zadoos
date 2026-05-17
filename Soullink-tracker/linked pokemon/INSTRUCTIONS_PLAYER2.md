# Setup für Spieler 2 / Setup for Player 2

🇩🇪 Deutsch unten · 🇬🇧 English below

---

## 🇩🇪 Deutsch

Damit dein Team automatisch im Stream-Overlay des Hosts erscheint, brauchst du:

### Was du brauchst

- mGBA mit deiner Smaragd-ROM
- Python 3.10+ ([python.org](https://python.org), beim Installieren **"Add to PATH"** anhaken)
- Die Dateien `mgba_smaragd.lua`, `agent.py`, `start_agent.bat` (vom Host bekommen oder aus dem Repo)
- Die **ngrok-URL** vom Host (sieht aus wie `https://xyz.ngrok-free.app`)

### Einmaliges Setup

1. **Ordner anlegen**, z.B. `C:\Users\DEINNAME\Desktop\soullink\`
2. Die 3 Dateien (Lua, agent.py, start_agent.bat) reinkopieren
3. **`start_agent.bat`** doppelklicken → es erstellt `agent_config.json` und beschwert sich, dass sie fehlt (normal)
4. **`agent_config.json`** mit Notepad öffnen und ausfüllen:
   ```json
   {
     "server_url": "https://xyz.ngrok-free.app",
     "party_file": "C:\\Users\\DEINNAME\\Desktop\\soullink\\party_local.json",
     "player_index": 1
   }
   ```
   ⚠️ Backslashes in JSON doppeln (`\\`).

### Bei jeder Session

1. **mGBA** starten, ROM laden, ins Spiel rein
2. **Werkzeuge → Scripting → Datei → Datei laden** → `mgba_smaragd.lua`
   - Es muss `[Soullink] Smaragd-Reader aktiv` erscheinen
3. **`start_agent.bat`** doppelklicken
   - Es muss `[Agent] OK -> X Pokemon gesendet` erscheinen
4. Falls der Host eine **neue ngrok-URL** hat (ändert sich bei jedem Start),
   `agent_config.json` mit der neuen URL aktualisieren und Agent neu starten.

### Probleme?

| Fehler | Ursache |
|---|---|
| `Senden fehlgeschlagen` | Host-URL nicht erreichbar — neue ngrok-URL holen |
| `Lesefehler` | `party_file`-Pfad stimmt nicht mit `party_local.json` überein |
| Kein `Party aktualisiert` in mGBA | Lua-Script nicht geladen oder Spiel pausiert |

---

## 🇬🇧 English

For your party to show up automatically in the host's stream overlay, you need:

### What you need

- mGBA with your Emerald ROM
- Python 3.10+ ([python.org](https://python.org), tick **"Add to PATH"** when installing)
- The files `mgba_smaragd.lua`, `agent.py`, `start_agent.bat` (from the host or repo)
- The **ngrok URL** from the host (looks like `https://xyz.ngrok-free.app`)

### One-time setup

1. **Create a folder**, e.g. `C:\Users\YOURNAME\Desktop\soullink\`
2. Copy the 3 files (Lua, agent.py, start_agent.bat) into it
3. Double-click **`start_agent.bat`** → it creates `agent_config.json` and complains it's missing (that's expected)
4. Open **`agent_config.json`** in Notepad and fill in:
   ```json
   {
     "server_url": "https://xyz.ngrok-free.app",
     "party_file": "C:\\Users\\YOURNAME\\Desktop\\soullink\\party_local.json",
     "player_index": 1
   }
   ```
   ⚠️ Double backslashes in JSON (`\\`).

### Every session

1. Start **mGBA**, load ROM, get into game
2. **Tools → Scripting → File → Load script** → `mgba_smaragd.lua`
   - You should see `[Soullink] Smaragd-Reader aktiv`
3. Double-click **`start_agent.bat`**
   - You should see `[Agent] OK -> X Pokemon gesendet`
4. If the host has a **new ngrok URL** (changes on every restart), update
   `agent_config.json` and restart the agent.

### Troubleshooting

| Error | Cause |
|---|---|
| `Senden fehlgeschlagen` | Host URL unreachable — get the new ngrok URL |
| `Lesefehler` | `party_file` path doesn't match where Lua writes |
| No `Party aktualisiert` in mGBA | Lua script not loaded or game paused |
