"""Build single-file EXE to dist/ with automatic lock-process termination.

Usage:
    python scripts/build.py

If dist/Meccha Chameleon Tools.exe is locked by a running instance,
the script auto-kills the process and retries.
"""
import os, sys, time, subprocess

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_FILE = os.path.join(PROJECT_DIR, "meccha_chameleon_tools.spec")
DIST_DIR = os.path.join(PROJECT_DIR, "dist")
TARGET_EXE = os.path.join(DIST_DIR, "Meccha Chameleon Tools.exe")
EXE_NAME = "Meccha Chameleon Tools.exe"


def _clean_build_artifacts():
    for d in [os.path.join(PROJECT_DIR, "build"),
              os.path.join(PROJECT_DIR, "dist_new"),
              os.path.join(PROJECT_DIR, "__pycache__")]:
        if os.path.exists(d):
            subprocess.run(["rmdir", "/s", "/q", d], shell=True, cwd=PROJECT_DIR, capture_output=True)


def _kill_existing_instance():
    """Kill any running instance of this tool using taskkill."""
    result = subprocess.run(
        ["taskkill", "/f", "/im", EXE_NAME],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  Killed existing {EXE_NAME} process.")
        time.sleep(1)
        return True
    return False


def _remove_locked(path):
    """Try to remove the file; return True if gone, False if still locked."""
    if not os.path.exists(path):
        return True
    try:
        os.remove(path)
        print(f"  Removed {path}")
        return True
    except PermissionError:
        return False


def build():
    os.chdir(PROJECT_DIR)
    print(f"Meccha Chameleon Tools — Build Script")
    print(f"{'=' * 50}")
    print(f"Spec:     {SPEC_FILE}")
    print(f"Output:   {DIST_DIR}\\{EXE_NAME}")
    print()

    # Phase 1: if target exists and locked, find+kill then retry delete
    if os.path.exists(TARGET_EXE):
        if _remove_locked(TARGET_EXE):
            print("  Target removed.")
        else:
            print(f"  {TARGET_EXE} is locked — killing owning process...")
            _kill_existing_instance()
            if _remove_locked(TARGET_EXE):
                print("  Target removed after kill.")
            else:
                print("  WARNING: could not remove target; build may fail.")

    # Clean stale build artifacts
    _clean_build_artifacts()

    # Phase 2: build via PyInstaller
    print("\nRunning PyInstaller...")
    ret = subprocess.run(
        [sys.executable, "-m", "PyInstaller", SPEC_FILE, "--clean", "--distpath", DIST_DIR],
        cwd=PROJECT_DIR
    )

    if ret.returncode == 0:
        size = os.path.getsize(TARGET_EXE) if os.path.exists(TARGET_EXE) else 0
        print(f"\n{'=' * 50}")
        print(f"Build succeeded!  ({size / 1024 / 1024:.1f} MB)")
        print(f"Output: {TARGET_EXE}")
        return

    # Phase 3: on failure, kill running instance and retry once
    print(f"\nBuild failed (rc={ret.returncode}).")
    if os.path.exists(TARGET_EXE):
        print("Attempting kill + retry...")
        _kill_existing_instance()
        _clean_build_artifacts()
        time.sleep(1)
        ret = subprocess.run(
            [sys.executable, "-m", "PyInstaller", SPEC_FILE, "--clean", "--distpath", DIST_DIR],
            cwd=PROJECT_DIR
        )
        if ret.returncode == 0:
            size = os.path.getsize(TARGET_EXE) if os.path.exists(TARGET_EXE) else 0
            print(f"\n{'=' * 50}")
            print(f"Build succeeded on retry!  ({size / 1024 / 1024:.1f} MB)")
            print(f"Output: {TARGET_EXE}")
            return

    print(f"\nBuild failed with return code {ret.returncode}")
    sys.exit(1)


if __name__ == "__main__":
    build()
