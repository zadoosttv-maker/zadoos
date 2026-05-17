# Pokémon Soullink Tracker (Duo)

Automatic live tracker for a 2-player Pokémon **Soullink Nuzlocke** with OBS overlay.
Reads each player's party directly from the mGBA emulator memory and pushes updates
to a shared overlay in real time — no manual clicking needed when a Pokémon is
caught, fainted, or boxed.

Currently supports **Pokémon Smaragd / Emerald** (Gen 3). German Pokémon names.

## Features

- 🎮 **Auto party detection** — mGBA Lua script reads team straight from RAM
- 📡 **Live updates** via Server-Sent Events — overlay reacts instantly
- 🔗 **Linked pair logic** — when one player's Pokémon dies, both slots gray out
- 🌐 **Remote support** — second player can be on a different PC (via ngrok/Tailscale)
- ✏️ **Manual override** — control panel for nicknames, reordering, manual edits
- 🎲 **Randomizer-ready** — all 386 Gen 1-3 Pokémon supported

## Requirements

- Windows (Linux/Mac should work too, untested)
- Python 3.10+
- [mGBA](https://mgba.io/) 0.10+ (with Lua scripting)
- Pokémon Smaragd / Emerald ROM (not provided)

## Quick Start (Host = Player 1)

```bash
git clone https://github.com/YOUR-USERNAME/soullink-tracker.git
cd soullink-tracker
pip install -r requirements.txt
python tracker.py
```

First run downloads German Pokémon names from PokéAPI (one-time, ~2 min).

Then:

1. Open **http://127.0.0.1:5000/** in your browser — manual control panel
2. In OBS: add **Browser Source** with URL `http://127.0.0.1:5000/obs`, size **1920x1080**
3. In mGBA: `Tools → Scripting → File → Load script` → select `mgba_smaragd.lua`
4. Your party now appears automatically in the overlay!

### Fine-tuning slot positions

The overlay places sprites at absolute pixel coordinates. Tune via URL params:

```
http://127.0.0.1:5000/obs?x=860&y=200&slotW=78&slotH=78&rowGap=12&colGap=48&debug=1
```

`?debug=1` shows dashed outlines so you can align with your overlay. Drop it once positioned.

## Setup for Player 2 (different PC)

Player 2 needs to send their party data to Player 1's tracker. See
[`INSTRUCTIONS_PLAYER2.md`](INSTRUCTIONS_PLAYER2.md) — short version:

1. Player 1 starts tracker + exposes it via [ngrok](https://ngrok.com/) (`ngrok http 5000`)
2. Player 1 shares the ngrok URL with Player 2
3. Player 2 runs `agent.py` with the URL configured in `agent_config.json`
4. Player 2 also loads `mgba_smaragd.lua` in their mGBA

## File overview

| File | Purpose |
|---|---|
| `tracker.py` | Flask server: control panel, OBS overlay, SSE, party-sync |
| `mgba_smaragd.lua` | mGBA Lua script — reads party from Emerald RAM |
| `agent.py` | Companion script for Player 2 (pushes their party to host) |
| `start.bat` / `start_agent.bat` | Windows convenience launchers |
| `example_overlay/` | Sample OBS overlay design |

## How it works

```
mGBA (Player 1) ──> mgba_smaragd.lua ──> party_local.json
                                              │
                                              ▼ (file watcher)
                                         tracker.py ──SSE──> OBS Browser Source
                                              ▲
                                              │ POST /api/party/1
mGBA (Player 2) ──> lua ──> party_local.json ──> agent.py ──┘
                                            (over ngrok / Tailscale)
```

State is persisted in `state.json`. Manual edits (nicknames, ordering) survive auto-updates.

## Limitations

- **Gen 3 only** for now (Emerald/Ruby/Sapphire — only Emerald tested)
- **Boxed Pokémon detection** is inferred (party slot disappears → assumed boxed unless HP was 0)
- ngrok free tier rotates URL on every restart

## Languages

- 🇬🇧 [English (this file)](README.md)
- 🇩🇪 [Deutsch](README.de.md)

## License

[MIT](LICENSE) — do what you want, just keep the copyright notice.
