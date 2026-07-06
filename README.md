<div align="center">

<img width="1582" height="1092" alt="image" src="https://github.com/user-attachments/assets/e0dbeffe-b591-4bf5-9fc0-0f047a545c3d" />

# Meccha Chameleon Tools

External ESP · Aimbot · Radar · Player Mod for MECCA CHAMELEON (UE5)

<img width="1213" height="793" alt="Image" src="https://github.com/user-attachments/assets/512aafbb-8199-42e5-9313-f28249306a02" />

https://github.com/user-attachments/assets/d3f86ee2-cb53-4a96-8599-47a20beb5788
</div>

---

## Features

| Category | Capabilities |
|----------|-------------|
| **ESP** | Dot / 2D Box / Corner Box / Skeleton overlay, player names, role labels (Hunter/Survivor), distance, snap lines (turn red on hit enemies), enemy-only filter, visible/not-visible coloring, invincible detection, per-role toggles, team filter, distance scaling, Draw All |
| **Health** | Health bar + shield bar, adjustable model height & Y offset |
| **Radar** | External minimap with configurable size (80-400px) and range (1000-50000) |
| **Aimbot** | Smooth aim assist, FOV circle, rebindable key, visible-only check |
| **Magnet** | Snap aim assist with independent FOV, strength slider, and key binding |
| **Visuals** | Per-role Hunter/Survivor colors, invincible flag (gold), Draw All actors, Disable Buried, Show Cursor, Background Geometry toggle |
| **Player Mod** | Speed & jump multipliers, Teleport Collectible hotkey — *host only* |
| **Camouflage** | 🚧 **In Development** — Bridge-based in-game paint system |

All features are fully external (memory read via pymem). Colors are pre-configured for optimal visibility.

### Multi-Language Support

The UI supports 7 languages (EN, DE, FR, ES, CN, JP, KR), selectable from the menu footer. Language persists across sessions.

---

## Quick Start

### Standalone (no Python required)
1. Download the latest release EXE from Releases
2. Launch MECCA CHAMELEON (windowed / borderless)
3. Run `Meccha Chameleon Tools.exe`

### From source
```
pip install -r requirements.txt
python -m meccha_chameleon_tools
```

**Requirements:** Windows 10/11, game running in windowed/borderless mode.

---

## Controls

| Key | Action |
|-----|--------|
| Insert / F1 | Toggle settings menu |
| Y | Teleport Collectible |
| MB4 | Magnet aim assist (hold) |
| END | Quit application |
| Close button | Quit application |

### Settings Tabs

**ESP** — Dot / Box / Corner Box / Skeleton toggles, Show Local, Names, Roles (Hunter = red, Survivor = blue), Distance, Snap Lines (turn red on hit enemies), Team Filter, Enemy Only, Distance Scaling, dot radius, visible/not-visible colors.

**HEALTH** — Health bar, shield bar, model height, Y offset.

**VISUAL** — Per-role ESP toggles, Hunter/Survivor colors, invincible detection (gold highlight), Draw All actors, Disable Buried, Show Cursor, Background Geometry, line thickness & point size.

**RADAR** — Enable/disable, size (80-400 px), range (1000-50000).

**AIMBOT** — Enable, FOV circle, key binding, FOV radius, smoothing, aim offset. Magnet sub-section with independent key, FOV, and strength.

**PLAYER** — Player Mod toggle with Speed & Jump multipliers. Teleport Collectible key binding. *Host only.*

> **🚧 CAMOUFLAGE** — Tab is disabled in this release. The bridge-based paint system is under active development.

---

## Package Structure

```
meccha_chameleon_tools/
  __init__.py        Entry point
  __main__.py        Module runner
  config.py          Configuration + JSON save/load
  core.py            Memory reading, ESP logic, role detection
  translations.py    Multi-language EN/DE/FR/ES/CN/JP/KR
  ui.py              Qt5 overlay + menu GUI
  camouflage.py      Camouflage bridge controller (DEV)
  runtime-bridge.dll Bridge DLL for camouflage (DEV)
  runtime-injector.exe DLL injector for camouflage (DEV)
```

---

## Architecture

```
PatternScanner → GUObjectArray, FNamePool
UObjectArray   → find_class, iter_objects
OffsetResolver → dynamic property walking
GameReader     → world, camera, players, role detection
Overlay        → QPainter rendering loop @ 60 fps
Menu           → PyQt5 settings window (6 tabs)
Bridge DLL     → TCP command server for teleport, player_mod
Camouflage     → TCP bridge client + injector (in development)
```

### Memory Access

1. **Pattern scanning** locates GUObjectArray and FNamePool via signature matching.
2. **Object walking** enumerates all UObjects to resolve engine class addresses.
3. **Dynamic offset resolution** walks UStruct::ChildProperties → FField::Next at runtime.
4. **ESP** projects player positions through the camera view matrix.
5. **Radar** projects positions relative to local player onto a 2D minimap.
6. **Aimbot** reads/writes ControlRotation with configurable smoothing.
7. **Camouflage** injects a bridge DLL into the game process and sends paint commands via TCP on port 50262 *(in development)*.

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Game attach failed | Verify PenguinHotel-Win64-Shipping.exe is running |
| ESP shows nothing | Load into a match |
| Fewer players detected | Disable Team Filter |
| Snap lines not visible | Off-screen players draw lines to screen edge |
| Aimbot not firing | Re-record the aim key |
| Radar not showing | Enable Radar Enabled in the RADAR tab |
| Player Mod not working | Must be game host |

---

## Changelog

### v1.8.2-wow — WIP Fusion Release (wzs12222)
- **Team-based colors** — Green(self) / Yellow(teammate) / Red(enemy) / Blue(unknown)
- **Background reader thread** — 10 reads/sec, eliminates render stutter
- **Auto-attach** — tool starts without game, attaches every 2s
- **Observer mode** — camera proximity detection for spectate targets
- **Filter Config dialog** — hide Enemy/Self/Teammate/Unknown by category
- **Configurable ESP FPS** — 10-60 slider in ESP tab
- **APPDATA config path** — settings survive PyInstaller builds
- **System language detection** — auto-detect on first launch
- **Load Config UI sync** — checkboxes and spinboxes refresh on load
- Retains all v1.8.1 features (7 languages, camouflage bridge, magnet, player mod, draw all, per-role toggles)

### v1.8.0 — Role detection, enemy filter, corner box
- Role detection (Hunter/Survivor), enemy-only filter, Show Roles toggle
- Corner Box 2D bounding boxes
- Visible/not-visible coloring, Load Config button, END key exit
- Teleport / Set FOV / Kill bridge commands

### v1.7.0 — Magnet aim, per-role visuals, invincible detection
- Magnet aim assist, per-role ESP toggles and colors
- Invincible detection (gold highlight)
- Draw All actors, Show Cursor, Player Mod, Teleport Collectible

---

## Disclaimer

Educational and research purposes only. Use at your own risk.

## License & Attribution

This project incorporates code from [acentrist/MecchaCamouflage](https://github.com/acentrist/MecchaCamouflage) (GPL-3.0). Full license text in `LICENSE.txt`.
