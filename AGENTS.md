# Meccha Chameleon Tools - Build Rules

## Build Output Location

The final build output MUST be placed in the `dist/` directory:

```
dist/
└── Meccha Chameleon Tools.exe    # Single executable with everything bundled
```

This single EXE contains:
- Qt5 overlay/menu (ESP, aimbot, magnet, teleport, player mod)
- pymem + pywin32 (memory reading)
- Bridge DLL + injector (camouflage, teleport collectible, player mod)
- Controller EXE (auto-injection, F10 hotkey)

## Build Process

### Step 1: Build C++ components (bridge DLL, injector, controller)
```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File runtime/scripts/build.ps1
```

### Step 2: Copy bridge artifacts to meccha_chameleon_tools/
```powershell
Copy-Item "runtime\.build\bin\runtime-bridge.dll" "meccha_chameleon_tools\runtime-bridge.dll" -Force
Copy-Item "runtime\.build\bin\runtime-injector.exe" "meccha_chameleon_tools\runtime-injector.exe" -Force
```

### Step 3: Build the full tool with PyInstaller
```powershell
pyinstaller --clean meccha_chameleon_tools.spec
```

This produces `dist\Meccha Chameleon Tools.exe` (~41MB) with everything bundled.

## Naming Convention

- The main executable MUST be named **"Meccha Chameleon Tools.exe"** (with spaces)
- Do NOT use "meccha-camouflage.exe" or other variants in the dist folder

## Verification

After build, verify the executable exists in `dist/`:
```powershell
Get-ChildItem "dist\Meccha Chameleon Tools.exe" | Select-Object Name,Length,LastWriteTime
```

## Spec File

The PyInstaller spec file is `meccha_chameleon_tools.spec` and bundles:
- `meccha-xenos-bridge.dll` - Bridge DLL for game injection
- `meccha-xenos-injector.exe` - DLL injector
- `meccha-camouflage.exe` - Controller EXE
