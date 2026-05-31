"""
Soullink-Agent fuer Spieler 2 (AKUMA_FLO).

Laeuft auf Flo's PC, ueberwacht die lokale party_local.json (geschrieben vom
mGBA-Lua-Script) und schickt jede Aenderung an Zadoos' Tracker.

Setup:
1. agent_config.json neben dieser Datei oeffnen / anlegen
2. server_url + party_file eintragen
3. start_agent.bat doppelklicken
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent
CONFIG_FILE = ROOT / "agent_config.json"

DEFAULT_CONFIG = {
    "server_url": "https://DEINE-NGROK-URL.ngrok-free.app",
    "party_file": r"C:\Users\Flo\Desktop\soullink\party_local.json",
    "player_index": 1,
}


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
        print(f"[Agent] Erstanlage: agent_config.json wurde angelegt.")
        print(f"[Agent] Bitte oeffnen und 'server_url' und 'party_file' eintragen, dann neu starten.")
        sys.exit(1)
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def main() -> None:
    cfg = load_config()
    server = cfg["server_url"].rstrip("/")
    party_file = Path(cfg["party_file"])
    pi = cfg.get("player_index", 1)
    endpoint = f"{server}/api/party/{pi}"

    print(f"[Agent] Beobachte: {party_file}")
    print(f"[Agent] Sende an:  {endpoint}")
    print(f"[Agent] Druecke Strg+C zum Beenden.\n")

    last_mtime = 0.0
    while True:
        try:
            if party_file.exists():
                mt = party_file.stat().st_mtime
                if mt != last_mtime:
                    last_mtime = mt
                    data = json.loads(party_file.read_text(encoding="utf-8"))
                    try:
                        r = requests.post(endpoint, json=data, timeout=10,
                                          headers={"ngrok-skip-browser-warning": "1"})
                        if r.status_code == 200:
                            n = len(data.get("party", []))
                            print(f"[Agent] OK -> {n} Pokemon gesendet")
                        else:
                            print(f"[Agent] Fehler {r.status_code}: {r.text[:200]}")
                    except Exception as e:
                        print(f"[Agent] Senden fehlgeschlagen: {e}")
        except Exception as e:
            print(f"[Agent] Lesefehler: {e}")
        time.sleep(1)


if __name__ == "__main__":
    main()
