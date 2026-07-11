<div align="center">

<img width="1582" height="1092" alt="Meccha Chameleon Tools" src="https://github.com/user-attachments/assets/e0dbeffe-b591-4bf5-9fc0-0f047a545c3d" />

# Meccha Chameleon Tools

External ESP · Aimbot · Radar · Player Mod · Camouflage for **MECCA CHAMELEON** (UE5.6)

<img width="1213" height="793" alt="Preview" src="https://github.com/user-attachments/assets/512aafbb-8199-42e5-9313-f28249306a02" />

</div>

---

## Overview

A fully **external** overlay tool for MECCA CHAMELEON. All gameplay reads happen via
memory (pymem) — nothing is injected into the game's code. The camouflage system is the
only component that uses a small injected bridge DLL for in-game mesh painting.

> **Status:** `1.9.1.1-beta` is a pre-release. Features are stable but the build is
> published under the `-beta` channel so the in-app updater can deliver it to testers.

---

## Features

| Category | Capabilities |
|----------|-------------|
| **ESP** | Dot / 2D Box / Corner Box / Skeleton overlays, names, role labels (Hunter/Survivor), distance, snap lines, enemy-only filter, visible/not-visible coloring, invincible detection, per-role toggles, team filter, distance scaling, Draw All |
| **Health** | Health + shield bars, adjustable model height & Y offset |
| **Visuals** | Per-role Hunter/Survivor colors, invincible flag, Draw All actors, Disable Buried, Show Cursor, Background Geometry, line thickness & point size |
| **Radar** | External minimap with configurable size (80–400 px) and range (1000–50000) |
| **Aimbot** | Smooth aim assist, FOV circle, rebindable key, visible-only check |
| **Magnet** | Snap aim assist with independent FOV, strength slider, and key binding |
| **Player Mod** | Speed & jump multipliers, Teleport Collectible hotkey — *host only* |
| **Camouflage** | Bridge-based in-game paint system — paint / stop / review / unreview |

> **Note on ESP accuracy:** All ESP overlays are calculated in real time by reading
> game memory. When an opponent moves rapidly or is partially obscured, the position
> may show slight inconsistency on a single frame. The **snap line** is the most
> reliable indicator — it always connects screen-center to the player's resolved
> position, so follow the line when the box or dot appears to trail.

### Multi-Language

The UI ships in **9 languages** (EN, DE, FR, ES, CN, JP, KR, RU, TR), selectable from the
menu. The choice persists across sessions.

### In-App Updater

The menu checks GitHub Releases (including pre-releases) on startup and lets you download
and open the latest build directly — no need to revisit the Releases page manually.

---

## Quick Start

### Standalone (recommended — no Python required)
1. Download **`Meccha Chameleon Tools.exe`** from the [latest release](../../releases/latest).
2. Launch MECCA CHAMELEON (windowed / borderless).
3. Run `Meccha Chameleon Tools.exe`.

### From source
```bash
pip install -r requirements.txt
python -m meccha_chameleon_tools
```

**Requirements:** Windows 10/11, game running in windowed or borderless mode.

---

## Controls

| Key | Action |
|-----|--------|
| Insert / F1 | Toggle settings menu |
| Y | Teleport Collectible |
| MB4 | Magnet aim assist (hold) |
| F10 | Start painting (configurable) |
| F9 | Stop painting (configurable) |
| END | Quit application |
| Close button | Quit application |

### Settings Tabs

- **ESP** — Dot / Box / Corner Box / Skeleton toggles, Show Local, Names, Roles, Distance,
  Snap Lines, Team Filter, Enemy Only, Distance Scaling, dot radius, visible/not-visible colors.
- **HEALTH** — Health bar, shield bar, model height, Y offset.
- **VISUALS** — Per-role ESP toggles, Hunter/Survivor colors, invincible detection, Draw All
  actors, Disable Buried, Show Cursor, Background Geometry, line thickness & point size.
- **RADAR** — Enable/disable, size (80–400 px), range (1000–50000).
- **AIM/ASSIST** — Aimbot (enable, FOV circle, key, radius, smoothing, offset) and the Magnet
  aim-assist sub-section (key, FOV, strength).
- **PLAYER** — Player Mod toggle with Speed & Jump multipliers, Teleport Collectible key.
  *Host only.*
- **CAMOUFLAGE** — Paint, stop, review, and unreview your character mesh. Requires the game
  process running.

---

## Package Structure

```
meccha_chameleon_tools/
  __init__.py        Entry point
  __main__.py        Module runner
  config.py          Configuration + JSON save/load
  core.py            Memory reading, ESP logic, role detection
  translations.py    Multi-language (9 languages)
  ui.py              Qt5 overlay + menu GUI
  camouflage.py      Camouflage bridge controller
  updater.py         In-app update checker/downloader
  native/            Bridge DLL, loader DLL, injector EXE
  mesh-profiles/     Mesh profile JSON configs
```

---

## Architecture

```
PatternScanner → GUObjectArray, FNamePool
UObjectArray   → find_class, iter_objects
OffsetResolver → dynamic property walking
GameReader     → world, camera, players, role detection
Overlay        → QPainter rendering loop (off-thread snapshot → paint)
Menu           → PyQt5 settings window (tabs + in-app updater)
Camouflage     → loader-based bridge injection (TCP, port 50262) for mesh painting
```

### Memory Access
1. **Pattern scanning** locates GUObjectArray and FNamePool via signature matching.
2. **Object walking** enumerates all UObjects to resolve engine class addresses.
3. **Dynamic offset resolution** walks UStruct::ChildProperties → FField::Next at runtime.
4. **ESP** builds a coherent off-thread snapshot, then projects player positions through the
   camera view matrix on the paint thread.
5. **Radar** projects positions relative to the local player onto a 2D minimap.
6. **Aimbot / Magnet** read the camera and apply aim assist with configurable smoothing.
7. **Camouflage** injects a bridge DLL (via loader + runtime-injector) and sends paint commands
   over TCP on port 50262.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Game attach failed | Verify the game process is running before launching the tool |
| ESP shows nothing | Load into a match |
| Fewer players detected | Disable Team Filter |
| Snap lines not visible | Off-screen players draw lines to the screen edge |
| Aimbot not firing | Re-record the aim key |
| Radar not showing | Enable Radar in the RADAR tab |
| Player Mod not working | Must be the game host |

---

## Building from Source

```bash
# 1. Build the native components (bridge DLL, injector, controller)
pwsh -NoProfile -ExecutionPolicy Bypass -File runtime/scripts/build.ps1

# 2. Copy bridge artifacts into the package
Copy-Item "runtime\.build\bin\meccha-camouflage.exe" "meccha_chameleon_tools\meccha-camouflage.exe" -Force
Copy-Item "runtime\.build\bin\runtime-bridge.dll"     "meccha_chameleon_tools\meccha-xenos-bridge.dll" -Force
Copy-Item "runtime\.build\bin\runtime-injector.exe"   "meccha_chameleon_tools\meccha-xenos-injector.exe" -Force

# 3. Bundle everything into a single executable
pyinstaller --clean meccha_chameleon_tools.spec
```

Output: `dist/Meccha Chameleon Tools.exe`.

---

## Changelog

### v1.9.1.2-beta
- **Camouflage engine updated** — new authenticated session protocol replaces the old
  loader-based injection (no more `bridge-loader.dll`). Dynamic port assignment,
  per-instance staging with automatic cleanup of stale bridge folders.
- **Config persistence fix** — settings now save next to the EXE when frozen, resolving
  a silent write failure inside the PyInstaller bundle directory.
- **ESP `bHidden` offset** updated for the latest game patch.
- **Bridge status** in the Camouflage tab now reliably transitions from "checking" to
  "Connected" or "Disconnected" (no more stuck label).

### v1.9.1.1-beta
- **UI redesign** — modern dark theme with accent palette, gradient controls, and a reorganized
  card-based menu (sidebar icons, grouped sections, primary Save / danger Close buttons).
- **ESP stability** — overlays now render from a coherent off-thread snapshot with player
  persistence, eliminating flicker, lag, and players disappearing during fast movement.
- **Localization** — added Russian (RU) and Turkish (TR); now 9 languages.
- **Updater** — in-app update checker/downloader added; `meccha_chameleon_tools.spec` now tracked
  so maintainers can rebuild.

### v1.9.1-beta
- In-app update checker/downloader.
- Build spec tracked in repo.
- Version source centralized in `updater.py`.

### v1.9.0-beta
- Camouflage reworked with a lighter bridge system (loader-based injection, port 50262).
- Simplified camouflage UI (Start / Stop / Review / Unreview).
- Native files moved into the `native/` subdirectory.

### v1.8.1
- Multi-language support (7 languages).
- Coherent dark theme with styled combo box popup, sliders, and scrollbars.

### v1.8.0
- Role detection (Hunter/Survivor), enemy-only filter, corner box.
- Visible/not-visible coloring, Load Config, END-key exit.

---

## Disclaimer

For educational and research purposes only. Use at your own risk.

## License & Attribution

This project incorporates code from [acentrist/MecchaCamouflage](https://github.com/acentrist/MecchaCamouflage)
(GPL-3.0). Full license text in `LICENSE.txt`.
