<div align="center">
  <h1>Meccha Chameleon Tools</h1>
  <p><strong>External ESP · Aimbot · Active Camouflage</strong></p>
  <p>for <em>MECCHA CHAMELEON</em> (UE5)</p>
  <a href="https://github.com/SilentJMA/Meccha-Chameleon-Tools/releases/latest"><img alt="Download" src="https://img.shields.io/badge/Download-Latest_Release-blue?style=for-the-badge&logo=github"></a>
  <br><br>
</div>

## Features

| Category | Capabilities |
|----------|-------------|
| **ESP** | Dot / 2D Box / Both rendering styles, corner box option, skeleton overlay, snap lines, player names, distance, health, shield, weapon labels, team filtering, distance culling |
| **Aimbot** | Smooth aim assist, configurable FOV circle, target height offset, fully rebindable key |
| **Camouflage** | One-key screen-centre colour capture (GDI), writes directly to player material memory, adjustable fallback colour preset |

All features are fully external — no DLL injection, no UE4SS dependency, no DXGI screen capture.

<img width="1497" height="619" alt="image" src="https://github.com/user-attachments/assets/e9b6b1ce-bc39-426b-b8dc-2a67bdb5b4fe" />


---

## Quick Start

### Option 1 — Standalone (no Python required)

1. Download `MecchaCamouflage.exe` from the [latest release](https://github.com/SilentJMA/Meccha-Camouflage-Tools/releases/latest)
2. Launch **MECCHA CHAMELEON** (windowed / borderless)
3. Run `MecchaCamouflage.exe`

### Option 2 — From source

```powershell
pip install -r requirements.txt
python -m meccha_camouflage
```

**Requirements:** Windows 10/11, game running in windowed/borderless mode.

| Dependency | Purpose |
|-----------|---------|
| `pymem` | Game process memory read/write |
| `PyQt5` | Transparent overlay + settings UI |
| `pywin32` | GDI pixel sampling, window detection |


---

## Controls

| Key | Action |
|-----|--------|
| `Insert` / `F1` | Toggle settings menu |
| `F10` | Sample screen centre + apply camouflage colour |

### Settings

The menu organises options across three tabs:

**ESP** — Style selector (Dot / 2D Box / Both), Corner Box toggle, Skeleton overlay, Labels (Names, Distance, Health, Shield, Weapon), Team Filter, Snap Lines, colours, model height, dot radius, Y offset, max distance culling.

**Camouflage** — Enable/disable, fallback RGB presets, live status feedback.

**Aimbot** — Enable toggle, FOV circle display, FOV radius, smoothing factor, aim offset, key binding recorder (supports full keyboard + mouse buttons).

<img width="161" height="308" alt="image" src="https://github.com/user-attachments/assets/050a0169-eb49-45e4-bab5-6a21de940306" />


---

## Package

```
meccha_camouflage/       # Python package
├── __init__.py          # Main application logic
└── __main__.py          # Entry point: python -m meccha_camouflage
```

---

## Architecture

```
┌─ PatternScanner ──► GUObjectArray, FNamePool ──┐
│                                                │
├─ UObjectArray ────► find_class, iter_objects   │
│                                                │
├─ OffsetResolver ──► dynamic property walking   │
│                     (ChildProperties chain)     │
│                                                │
├─ GameReader ──────► world, camera, players     │
│                                                │
├─ Overlay ─────────► QPainter rendering loop    │
│                     @ 60 fps (16 ms timer)     │
│                                                │
├─ CamoApplier ─────► material memory write      │
│                                                │
├─ Menu ────────────► PyQt5 settings window      │
└────────────────────────────────────────────────┘
```

<img width="161" height="308" alt="image" src="https://github.com/user-attachments/assets/f22841e2-d417-41e9-ab37-e8f6888eba23" />


<img width="161" height="308" alt="image" src="https://github.com/user-attachments/assets/83bc4207-a3ba-4f68-9a8b-a7d6058fec2f" />


### Memory Access

1. **Pattern scanning** locates `GUObjectArray` and `FNamePool` in the game module via signature matching with fallback chains.
2. **Object walking** enumerates all UObjects to resolve engine class addresses and find player pawns, controllers, and camera managers.
3. **Dynamic offset resolution** walks the `UStruct::ChildProperties → FField::Next` chain to find property offsets at runtime — no hardcoded offsets beyond the UE5 bootstrap layout.
4. **ESP** reads player positions from `GameState → PlayerArray → PlayerState → PawnPrivate → RootComponent → RelativeLocation`, projects through the camera view matrix.
5. **Camouflage** samples a single pixel via GDI `GetPixel` (zero GPU overhead) and writes RGBA directly into the player's material `VectorParameterValues`.
6. **Aimbot** reads/writes `ControlRotation` on the local player controller with configurable smoothing.

### Engine Compatibility

The `FNameResolver` auto-detects UE4, UE5, and custom header-layout variants. The `PatternScanner` uses chunked reads (2 MiB) to avoid large allocations on shipping executables.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "Game attach failed" | Process name mismatch | Verify `PenguinHotel-Win64-Shipping.exe` is running |
| ESP shows nothing | Not in a match with players | Load into a lobby or match; enable "Show Local Player" to verify projection |
| Camouflage not applying | Material property not resolved | Check the status label in the Camouflage tab after pressing F10 |
| Wrong camouflage colour | GDI reads desktop composition | Use the Preset Colour sliders as fallback |
| Aimbot not firing | Key binding mismatch | Re-record the aim key in the Aimbot tab |

---

## Disclaimer

This project is provided for **educational and research purposes only**. Using third-party tools in online games may violate the game's Terms of Service and can result in account suspension. Use at your own risk. The authors assume no liability for any damages or consequences resulting from the use of this software.
