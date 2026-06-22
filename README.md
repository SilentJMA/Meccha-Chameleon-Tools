# Meccha Chameleon Tools

External ESP - Aimbot - Radar for MECCA CHAMELEON (UE5)

## Features

| Category | Capabilities |
|----------|-------------|
| **ESP** | Dot / 2D Box / Skeleton overlay, names, distance, snap lines, team filter, distance scaling |
| **Health Bars** | Health bar and shield bar, adjustable model height and Y offset |
| **Radar** | External minimap radar with configurable size and range |
| **Aimbot** | Smooth aim assist, FOV circle, rebindable key |
| **Colors** | Enemy, local, skeleton color pickers |

All features are fully external - no DLL injection, no UE4SS, no DXGI.

<img width="720" height="640" alt="image" src="https://github.com/user-attachments/assets/5a799f95-841d-4a1a-b8ad-c08d53973cb5" />


---

## Quick Start

### Option 1 - Standalone (no Python required)

1. Download MecchaCamouflage.exe from the latest release
2. Launch MECCA CHAMELEON (windowed / borderless)
3. Run MecchaCamouflage.exe

### Option 2 - From source

```
pip install -r requirements.txt
python -m meccha_chameleon_tools
```

Requirements: Windows 10/11, game running in windowed/borderless mode.

| Dependency | Purpose |
|-----------|---------|
| pymem | Game process memory read/write |
| PyQt5 | Transparent overlay + settings UI |
| pywin32 | GDI pixel sampling, window detection |

---

## Controls

| Key | Action |
|-----|--------|
| Insert / F1 | Toggle settings menu |

### Settings Tabs

The menu organises options across five tabs selected from a sidebar:

**ESP** - Enable/disable, style toggles (Dot / 2D Box / Skeleton), Show Local Player, Names, Distance, Snap Lines, Team Filter, Distance Scaling, dot radius.

**HEALTH** - Health bar toggle, shield bar toggle, model height, Y offset.

**RADAR** - Enable/disable, radar size (80-400 px), radar range (1000-50000).

**AIMBOT** - Enable toggle, FOV circle display, key binding recorder, FOV radius, smoothing factor, aim offset.

**COLORS** - Pick colours for enemy, local player, and skeleton overlay via colour picker dialog.

<img width="502" height="561" alt="image" src="https://github.com/user-attachments/assets/5a588a39-db23-4bf0-9dda-899d95bd1d92" />
<img width="2430" height="1177" alt="image" src="https://github.com/user-attachments/assets/38edb75b-e71d-4b35-addd-de8a80c38c66" />


---

## Package

```
meccha_chameleon_tools/   # Python package
|-- __init__.py           # Main application entry point
|-- __main__.py           # Module runner
|-- config.py             # Configuration + JSON save/load
|-- core.py               # Memory reading, ESP logic
|-- ui.py                 # Qt5 overlay + menu GUI
```

## Architecture

```
PatternScanner -> GUObjectArray, FNamePool
UObjectArray -> find_class, iter_objects
OffsetResolver -> dynamic property walking
GameReader -> world, camera, players
Overlay -> QPainter rendering loop @ 60 fps
Menu -> PyQt5 settings window (5-tab sidebar)
```

### Memory Access

1. **Pattern scanning** locates GUObjectArray and FNamePool in the game module via signature matching with fallback chains.
2. **Object walking** enumerates all UObjects to resolve engine class addresses and find player pawns, controllers, and camera managers.
3. **Dynamic offset resolution** walks the UStruct::ChildProperties -> FField::Next chain to find property offsets at runtime - no hardcoded offsets.
4. **ESP** reads player positions from GameState -> PlayerArray -> PlayerState -> PawnPrivate -> RootComponent -> RelativeLocation, projects through the camera view matrix.
5. **Radar** projects player positions relative to local player orientation onto a 2D minimap display.
6. **Aimbot** reads/writes ControlRotation on the local player controller with configurable smoothing.

### Engine Compatibility

The FNameResolver auto-detects UE4, UE5, and custom header-layout variants. The PatternScanner uses chunked reads (2 MiB) to avoid large allocations on shipping executables.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Game attach failed | Process name mismatch | Verify PenguinHotel-Win64-Shipping.exe is running |
| ESP shows nothing | Not in a match with players | Load into a lobby or match |
| Aimbot not firing | Key binding mismatch | Re-record the aim key in the AIMBOT tab |
| Radar not showing | Radar disabled | Enable Radar Enabled in the RADAR tab |

---

## Disclaimer

Educational and research purposes only. Use at your own risk.
