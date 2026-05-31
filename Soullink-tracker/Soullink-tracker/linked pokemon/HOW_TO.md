# 🟢 HOW-TO — Soullink Tracker

Kurzanleitung für Zadoos. Alles was du brauchst, an einem Ort.

---

## ⚡ TL;DR — bei JEDEM Stream (Reihenfolge)

### Bei DIR (Zadoos)
1. **`start.bat`** doppelklicken → Tracker-Konsole offen lassen
2. **`ngrok http 5000`** in PowerShell → URL kopieren (sieht aus wie `https://xxxx.ngrok-free.dev`)
3. Die **ngrok-URL an Flo** schicken (Discord)
4. **mGBA** starten → ROM laden → **Werkzeuge → Scripting → Datei laden → `mgba_smaragd.lua`**
   - Im Log muss stehen: `[Soullink] Smaragd-Reader aktiv`
5. **OBS** läuft mit Browser-Quelle `http://127.0.0.1:5000/obs` (1920x1080)

### Bei FLO (parallel)
1. **`agent_config.json`** öffnen → die neue ngrok-URL bei `server_url` eintragen → speichern
2. **mGBA** starten → ROM laden → **Werkzeuge → Scripting → Datei laden → `mgba_smaragd.lua`**
3. **`start_agent.bat`** doppelklicken
   - Muss zeigen: `[Agent] OK -> X Pokemon gesendet`
4. **OBS** mit Browser-Quelle `https://xxxx.ngrok-free.dev/obs?ngrok-skip-browser-warning=true` (1920x1080)

---

## 📌 Die wichtigste Regel

**Das Lua-Script wird bei JEDEM mGBA-Neustart entladen.**
→ Immer neu laden: Werkzeuge → Scripting → Datei → Datei laden.
Wenn das Overlay „eingefroren" wirkt, ist das zu 90 % der Grund.

---

## 🔁 Wer braucht welche Datei nach einem Update?

| Geänderte Datei | Wer braucht sie neu? |
|---|---|
| `tracker.py` | **Nur du** (Tracker neu starten) |
| `mgba_smaragd.lua` | **Du UND Flo** (beide neu laden in mGBA) |
| `agent.py` | **Nur Flo** |

Faustregel: Wenn die **Lua** geändert wurde → Flo braucht sie auch immer.

---

## 🛠️ Häufige Probleme

| Problem | Lösung |
|---|---|
| Overlay aktualisiert nicht | Lua in mGBA neu laden. Spiel darf nicht pausiert sein. |
| Flo sieht nichts in OBS | URL muss mit `/obs` enden. Cache aktualisieren. Einmal „Visit Site" über Rechtsklick → Interagieren. |
| Flos Agent: „Senden fehlgeschlagen" | ngrok-URL ist neu/falsch → in `agent_config.json` aktualisieren. ngrok bei dir muss laufen. |
| Falsches Pokémon angezeigt | Lua-Log prüfen (`DEBUG = true`): zeigt `intern=… -> natdex=…`. Screenshot an Claude schicken. |
| Falscher Name | Im Panel manuell ändern → wird gelb/gesperrt 🔒. „auto"-Button = wieder automatisch. |

---

## 🌐 Adressen (bei dir lokal)

- **Steuerung:** http://127.0.0.1:5000/
- **OBS-Overlay:** http://127.0.0.1:5000/obs
- **ngrok-Dashboard (live):** http://127.0.0.1:4040

---

## 🎮 Control-Panel (http://127.0.0.1:5000/)

- **Namen** kommen automatisch aus dem Spiel (ihr benennt ja um).
- Manuell geänderter Name = **gelb & gesperrt**, Spiel überschreibt ihn nicht mehr.
  Kleiner **„auto"-Button** macht ihn wieder automatisch.
- **Checkboxen** = mehrere Pokémon auswählen → **→ Team / → Box / → Tot / Löschen**.
- Pokémon manuell hinzufügen: Suchfeld (deutscher Name).

---

## ⚠️ ngrok-URL ändert sich

Jedes Mal wenn du ngrok neu startest, gibt es eine **neue URL**.
→ Dann muss Flo sie neu eintragen (in `agent_config.json` UND in seiner OBS-Browser-Quelle).
**Tipp:** ngrok während des ganzen Streams offen lassen, nicht zwischendurch schließen.
