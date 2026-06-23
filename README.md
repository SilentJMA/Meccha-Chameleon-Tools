<img width="504" height="561" alt="image" src="https://github.com/user-attachments/assets/a83d6aaa-b6aa-40c0-b6d8-2f2fa54d9856" />

# Meccha Chameleon Tools

External ESP - Aimbot - Radar for MECCA CHAMELEON (UE5) - Camouflage WIP

## Features

| Category | Capabilities |
|----------|-------------|
| **ESP** | Dot / 2D Box / Skeleton overlay, names, distance, snap lines, team filter, distance scaling |
| **Camouflage** | WARNING DEV / OPTIONAL - Disabled by default. F10 samples screen color and applies to character material. Prompt at startup to enable. |
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

> **Startup prompts** -- On first launch the tool asks:
> 1. Enable **Camouflage**? (optional, DEV -- disabled by default)
> 2. Download the **latest release** from GitHub and install it to the game directory?

---

## Camouflage (DEV / Optional)

WARNING: This feature is in DEVELOPMENT and disabled by default.

### How to use

1. **Enable at startup** -- A dialog asks "Would you like to enable camouflage?" Click **Yes** to activate.
<img width="505" height="236" alt="image" src="https://github.com/user-attachments/assets/a3607aff-dd41-4e12-8f8e-aca47b35d03c" />
If you click Yes
<img width="552" height="232" alt="image" src="https://github.com/user-attachments/assets/bfe7769c-4ba1-431e-88d8-cfcdfb1890cd" />
success
<img width="496" height="138" alt="image" src="https://github.com/user-attachments/assets/a534fe20-4cfe-434e-b659-1d9f15f7fcf9" />
make sure the game start with next run
<img width="414" height="171" alt="image" src="https://github.com/user-attachments/assets/f58eba89-440d-4183-96d6-1a2574c57b8a" />

3. **Or enable later** -- Open settings (Insert/F1), go to the CAMOUFLAGE tab, check "Camouflage Enabled".
4. **Sample and apply** -- Press **F10** in-game to sample screen color and apply to character's 3D model.
5. **Toggle off** -- Press F10 again to restore original color.

> The setting is per-session. You will be prompted again each launch.

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
| F10 | Camouflage (DEV / optional -- disabled by default) |

### Settings Tabs

The menu organises options across five tabs selected from a sidebar:

**ESP** - Enable/disable, style toggles (Dot / 2D Box / Skeleton), Show Local Player, Names, Distance, Snap Lines, Team Filter, Distance Scaling, dot radius.

**HEALTH** - Health bar toggle, shield bar toggle, model height, Y offset.

**RADAR** - Enable/disable, radar size (80-400 px), radar range (1000-50000).

**AIMBOT** - Enable toggle, FOV circle display, key binding recorder, FOV radius, smoothing factor, aim offset.

**COLORS** - Pick colours for enemy, local player, and skeleton overlay via colour picker dialog.

**CAMOUFLAGE** - WARNING DEV / OPTIONAL -- Disabled by default. Enable via startup prompt or the CAMOUFLAGE tab. Press F10 to sample screen colour and apply it to your character's 3D model.

<img width="512" height="572" alt="image" src="https://github.com/user-attachments/assets/11c72fa0-81ac-40dc-9356-75ba0d5efe23" />

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
| Game Freeze after pressing F10 | time to write and analyze the colors location| Normal this takes between 1-2min |
| Game attach failed | Process name mismatch | Verify PenguinHotel-Win64-Shipping.exe is running |
| ESP shows nothing | Not in a match with players | Load into a lobby or match |
| Only 1-2 players detected (4+ in game) | Team filter on; all use same character class | Disable Team Filter in the ESP tab (or update to v1.2.1 where it defaults to off) |
| Snap lines not visible | w2s dropped off-screen projections | Update to v1.2.1 — off-screen players now correctly draw lines to screen edge |
| Aimbot not firing | Key binding mismatch | Re-record the aim key in the AIMBOT tab |
| Radar not showing | Radar disabled | Enable Radar Enabled in the RADAR tab |

---

## Changelog

### v1.3.0 - Camouflage optional (DEV) + auto-install prompt

- **Camouflage is now disabled by default** -- user is asked at startup whether to enable it.
- **Camouflage marked as DEV / experimental** -- clearly labelled throughout UI and README.
- **Auto-install prompt** -- tool asks at startup whether to download the latest release from GitHub to the game directory.
- **Startup dialogs** -- two Qt prompts at launch: camouflage opt-in and release download/install.

### v1.2.1 - Player count & snap line fixes

- **Fix: Only 1-2 players detected** - Team filter default changed to False. Previously, players sharing the same character class as the local player were filtered out; this caused most or all enemies to be invisible in modes where everyone uses the same Blueprint class.
- **Fix: Snap lines not drawing** - w2s() no longer returns None for off-screen positions. Snap lines now draw from screen bottom-center to the player angular position at the screen edge. On-screen elements (dots, health bars, labels) are clamped to the visible area.
- **Added** clamp_screen() helper for clean off-screen element handling.

### v1.2.0 - Tabbed UI

- Sidebar with five tabs: ESP, HEALTH, RADAR, AIMBOT, COLORS
- All toggles, sliders, and color pickers organised per-tab
- Rebindable aim key with Insert/F1 menu toggle
- First standalone release with PyInstaller build

### v1.1.x - Initial releases

---

## Disclaimer

Educational and research purposes only. Use at your own risk.
