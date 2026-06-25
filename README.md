<div align="center">
  
<img src="preview.png" alt="Meccha Chameleon Tools" width="100%"/>

# Meccha Chameleon Tools

External ESP - Aimbot - Radar for MECCA CHAMELEON (UE5)

</div>

---

## Features

| Category | Capabilities |
|----------|-------------|
| **ESP** | Dot / 2D Box / Skeleton overlay, names, distance, snap lines, team filter, distance scaling |
| **Health Bars** | Health bar and shield bar, adjustable model height and Y offset |
| **Radar** | External minimap radar with configurable size and range |
| **Aimbot** | Smooth aim assist, FOV circle, rebindable key |
| **Colors** | Enemy, local, skeleton color pickers |

All features are fully external - no DLL injection, no UE4SS, no DXGI.

---

## Quick Start

### Option 1 - Standalone (no Python required)

1. Download the latest release EXE
2. Launch MECCA CHAMELEON (windowed / borderless)
3. Run the EXE

### Option 2 - From source

```
pip install -r requirements.txt
python -m meccha_chameleon_tools
```

Requirements: Windows 10/11, game running in windowed/borderless mode.

---

## Controls

| Key | Action |
|-----|--------|
| Insert / F1 | Toggle settings menu |
| F9 | Photo paint (camouflage) |
| Close button | Bottom bar of menu -- quits the application entirely |

### Settings Tabs

The menu organises options across five tabs selected from a sidebar:

**ESP** - Enable/disable, style toggles (Dot / 2D Box / Skeleton), Show Local Player, Names, Distance, Snap Lines, Team Filter, Distance Scaling, dot radius.

**HEALTH** - Health bar toggle, shield bar toggle, model height, Y offset.

**RADAR** - Enable/disable, radar size (80-400 px), radar range (1000-50000).

**AIMBOT** - Enable toggle, FOV circle display, key binding recorder, FOV radius, smoothing factor, aim offset.

**COLORS** - Pick colours for enemy, local player, and skeleton overlay via colour picker dialog.

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
Menu -> PyQt5 settings window (5-tab sidebar: ESP, HEALTH, RADAR, AIMBOT, COLORS)
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
| Only 1-2 players detected (4+ in game) | Team filter on; all use same character class | Disable Team Filter in the ESP tab |
| Snap lines not visible | w2s dropped off-screen projections | Update â€” off-screen players now correctly draw lines to screen edge |
| Aimbot not firing | Key binding mismatch | Re-record the aim key in the AIMBOT tab |
| Radar not showing | Radar disabled | Enable Radar Enabled in the RADAR tab |

---

## Changelog

### v1.5.0 - Clean startup, aimbot consistency fix

- **Removed all startup dialogs** -- no game directory prompt, no GitHub download check, no camouflage opt-in dialog. Tool launches silently.
- **Aimbot consistency fix** -- `_aim_at()` now uses the same camera data as `_find_best_target()` instead of re-fetching, eliminating aim drift.
- **Cleanup** -- removed all debug/test scripts, dnSpy decompiler, reverse-engineered DLLs from the project folder.
- **Updated .gitignore** -- comprehensive ignore patterns for all debug scripts.

### v1.4.1 - CI auto-build + Close button + __main__ fix

- **CI/CD** -- GitHub Actions auto-builds the single-file EXE on every push to master and attaches it to releases.
- **Close button** -- added to the menu bottom bar to quit the application at any time.
- **__main__.py fix** -- corrected import path (double-__init__) to prevent EXE crash when game is not running.

### v1.4.0 - Smarter auto-install (prompt only on first launch) + CI auto-build

- **CI/CD** -- GitHub Actions auto-builds the EXE on every push to master and attaches it to published releases.
- **Prompt only once** -- dialog only shows if no release is found in the game directory.
- **Already installed** -- no dialog at all, no GitHub API call, opens menu directly.
- **First install** -- checks GitHub and asks "Install MecchaCamouflage?" with version info.
- **Version tracking** -- .meccha_version file written to game directory after install.

### v1.3.0 - Camouflage optional (DEV) + auto-install prompt

- **Camouflage is now disabled by default** -- user is asked at startup whether to enable it.
- **Auto-install prompt** -- tool asks at startup whether to download the latest release from GitHub to the game directory.

### v1.2.1 - Player count & snap line fixes

- **Fix: Only 1-2 players detected** - Team filter default changed to False.
- **Fix: Snap lines not drawing** - w2s() no longer returns None for off-screen positions.

### v1.2.0 - Tabbed UI

- Sidebar with five tabs: ESP, HEALTH, RADAR, AIMBOT, COLORS
- All toggles, sliders, and color pickers organised per-tab
- Rebindable aim key with Insert/F1 menu toggle
- First standalone release with PyInstaller build

### v1.1.x - Initial releases

---

## Disclaimer

Educational and research purposes only. Use at your own risk.
