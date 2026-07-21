# Camouflage Lighter — Update from GitHub Release

> **Current version: v1.6.2** (2026-07-21)
> Generated from the official [MecchaCamouflage v1.6.2](https://github.com/acentrist/MecchaCamouflage/releases/tag/v1.6.2)
> release. v1.6.2 restored Auto Paint compatibility with MECCHA CHAMELEON 2.9.0,
> fixed painted surfaces looking incorrectly emissive, and added Emissive material
> controls (`emissive` / `fill_emissive` in the paint tuning).

## Overview

This file describes how to update the Camouflage Lighter standalone EXE when a new
version of [MecchaCamouflage](https://github.com/acentrist/MecchaCamouflage) is
released on GitHub.

The lighter EXE is a PyInstaller bundle of:
- `main.py` — Python/tkinter UI (4 buttons: Start Painting, Stop Painting, Review, Unreview)
- `native/runtime-bridge.dll` — injected into the game process
- `native/runtime-injector.exe` — direct injector
- `mesh-profiles/*.mesh-profile-v2.json` — character mesh definitions

## Update Process

### 1. Fetch the new release

Get the latest release tag from GitHub:

```
https://api.github.com/repos/acentrist/MecchaCamouflage/releases/latest
```

Download the release EXE asset (e.g. `meccha-camouflage-v{tag}.exe`).

### 2. Run the release EXE once

Execute the downloaded EXE. It self-extracts embedded assets to:

```
%LOCALAPPDATA%\MecchaCamouflage\versions\{tag}\runtime\package-assets\{hash}\
```

Wait for it to fully initialize (it opens a window), then close it.

### 3. Copy the native files + mesh profiles

From `...\package-assets\{hash}\`:

| Source | Destination |
|--------|-------------|
| `native\runtime-bridge.dll` | `native\runtime-bridge.dll` |
| `native\runtime-injector.exe` | `native\runtime-injector.exe` |
| `mesh-profiles\*.json` | `mesh-profiles\*.json` |

`update.bat` automates step 3 (copies from the newest installed version) and rebuilds.

### 4. Rebuild the EXE

```bat
build.bat
```

Output: `Camouflage.exe`

### 5. Verify

Run the new `Camouflage.exe`. It should:
1. Show "Connecting..." then inject the bridge
2. Show "Ready" when the bridge responds on the OS-assigned port
3. Allow painting (Start Painting, Review, etc.)

## Architecture Notes (for LLM context)

**Bridge protocol (direct injection):**
- Port: **OS-assigned, dynamic.** `requested_port` in the start block MUST be 0; the
  injector prints `{"event":"result","state":"listening","port":<bound_port>,...}` to
  stdout. The lighter parses `port` and uses it for all subsequent commands.
- Protocol: JSON-over-TCP, newline-terminated, one connection per command.
- Every connection is authenticated: send a `hello` line BEFORE the command:
  `{"type":"hello","bootstrap_protocol":1,"instance_id":"<guid32hex>","token":"<64hex>"}`
  Read the hello reply and confirm `success`/`stage=="hello"`.
- Commands are matched via `std::string::find("\"type\":\"<cmd>\"")` — compact JSON with
  NO spaces after colons is required. Use `json.dumps(payload, separators=(",", ":"))`.
- Ping: `{"type":"ping"}`
- Paint: `{"type":"paint_full_route", "preview_only": bool, "unpreview_only": bool, "tuning": {...}}`
- Cancel: `{"type":"cancel_paint"}`

**Paint tuning (v1.6.2).** `build_paint_payload()` sends the tuning the v1.6.2 app sends
(`BridgePayloadBuilder.cs`), including the two-pass brush model and the material fields:

```
brush_1_enabled, brush_1_size_texels, brush_2_enabled, brush_2_size_texels,
server_batch_auto_adapt, server_batch_limit, server_batch_pacing_ms,
coverage_step_texels, side_source_max_uv, front_back_source_max_uv, auto_material,
metallic, roughness, emissive,                      <- emissive is NEW in v1.6.2
front_region_mode, side_region_mode, back_region_mode,
fill_color, fill_color_r/g/b, fill_metallic, fill_roughness, fill_emissive   <- fill_emissive NEW
```

`emissive` / `fill_emissive` default to `0.0` so paint no longer renders as a glow.
Change the values in `PAINT_TUNING` (or `FILL_COLOR`) in `main.py` to adjust the look.

**Injection flow:**
1. Find the game process (pid, exe path, creation FILETIME UTC).
2. Compute `sha256(runtime-bridge.dll)`, generate a random 32-byte token + GUID.
3. Stage a per-instance directory with the renamed bridge DLL, a copy of the injector,
   and the mesh profiles.
4. Build the 128-byte `BridgeStartBlockV1` (see `build_start_block()`):
   - [0:4] magic `0x3153434D`, [4:8] size 128, [8:12] abi 1, [12:16] pid
   - [16:32] GUID (16 bytes, big-endian), [32:64] token, [64:96] sha256
   - [108:112] protocol = 1, other trailing fields zero (requested_port=0)
5. Run `runtime-injector.exe --direct <pid> <creationFiletimeUtc> <exePath> <bridgeDll>`
   with the 128-byte block on stdin; parse the `port` from the result line.
6. Store the port + instance GUID + token; use them for all hello-authenticated commands.

The native binaries needed are `runtime-bridge.dll` and `runtime-injector.exe`.

## Files in the Lighter Project

```
camouflage-lighter/
  main.py            — Python/tkinter UI with 4 buttons + bridge management
  build.bat          — Rebuild script
  update.bat         — Auto-copies native files from AppData and rebuilds
  requirements.txt   — psutil, pyinstaller
  native/
    runtime-bridge.dll    — Injected bridge (v1.6.2)
    runtime-injector.exe  — Direct injector (v1.6.2)
  mesh-profiles/
    paintman.mesh-profile-v2.json
    paintman_cube.mesh-profile-v2.json
```
