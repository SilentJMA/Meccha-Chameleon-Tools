import os
import json
import socket
import subprocess
import sys
import time
import ctypes
import ctypes.wintypes

BRIDGE_PORT = 50262
GAME_PROCESS = "PenguinHotel-Win64-Shipping.exe"
CREATE_NO_WINDOW = 0x08000000


def _resource_path(relative):
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


def _find_game_pid():
    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.wintypes.DWORD),
            ("cntUsage", ctypes.wintypes.DWORD),
            ("th32ProcessID", ctypes.wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.wintypes.DWORD),
            ("cntThreads", ctypes.wintypes.DWORD),
            ("th32ParentProcessID", ctypes.wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * MAX_PATH),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == ctypes.wintypes.HANDLE(-1).value:
        return None
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(pe)):
            return None
        while True:
            if pe.szExeFile.lower() == GAME_PROCESS.lower():
                return pe.th32ProcessID
            if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                return None
    finally:
        kernel32.CloseHandle(snapshot)


def _send_tcp(payload: dict, timeout=10) -> dict:
    data = (json.dumps(payload) + "\n").encode("utf-8")
    try:
        s = socket.create_connection(("127.0.0.1", BRIDGE_PORT), timeout=timeout)
        with s:
            s.sendall(data)
            resp = s.makefile("r", encoding="utf-8").read()
            return json.loads(resp) if resp.strip() else {"success": False, "stage": "empty"}
    except socket.timeout:
        return {"success": False, "stage": "timeout", "message": "Connection timed out"}
    except ConnectionRefusedError:
        return {"success": False, "stage": "refused", "message": "Bridge not running"}
    except Exception as e:
        return {"success": False, "stage": "transport_error", "message": str(e)}


def is_bridge_alive() -> bool:
    resp = _send_tcp({"type": "ping"}, timeout=3)
    return resp.get("success") is True


def _find_and_kill_bridge():
    kernel32 = ctypes.windll.kernel32
    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", ctypes.wintypes.DWORD),
            ("cntUsage", ctypes.wintypes.DWORD),
            ("th32ProcessID", ctypes.wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", ctypes.wintypes.DWORD),
            ("cntThreads", ctypes.wintypes.DWORD),
            ("th32ParentProcessID", ctypes.wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", ctypes.wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * MAX_PATH),
        ]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == ctypes.wintypes.HANDLE(-1).value:
        return
    try:
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(pe)):
            return
        while True:
            if pe.szExeFile.lower() == "runtime-injector.exe":
                handle = kernel32.OpenProcess(0x0001, False, pe.th32ProcessID)
                if handle:
                    kernel32.TerminateProcess(handle, 1)
                    ctypes.windll.kernel32.CloseHandle(handle)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                return
    finally:
        kernel32.CloseHandle(snapshot)


def inject_bridge() -> str:
    dll_path = _resource_path("runtime-bridge.dll")
    injector_path = _resource_path("runtime-injector.exe")

    if not os.path.exists(dll_path):
        return "runtime-bridge.dll not found"
    if not os.path.exists(injector_path):
        return "runtime-injector.exe not found"

    pid = _find_game_pid()
    if pid is None:
        return f"Game process '{GAME_PROCESS}' not found. Is the game running?"

    try:
        with open(dll_path + ".port", "w") as f:
            f.write(str(BRIDGE_PORT) + "\n")
    except Exception as e:
        return f"Failed to write port file: {e}"

    try:
        cmd = [injector_path, GAME_PROCESS, dll_path]
        result = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW, timeout=15)
    except FileNotFoundError:
        return "Injector executable not found"
    except Exception as e:
        return f"Failed to run injector: {e}"

    if result.returncode != 0:
        stderr = result.stderr.strip()
        return f"Injector failed (exit {result.returncode}): {stderr or 'Unknown error'}"

    deadline = time.time() + 10
    while time.time() < deadline:
        if is_bridge_alive():
            return ""
        time.sleep(0.25)

    return "Bridge injected but did not respond to ping"


def ensure_bridge_ready(max_retries=2) -> str:
    if is_bridge_alive():
        return ""
    for attempt in range(max_retries):
        err = inject_bridge()
        if not err:
            return ""
        if attempt < max_retries - 1:
            time.sleep(1)
    return err


def paint_now() -> dict:
    pid = _find_game_pid()
    payload = {
        "type": "paint_full_route",
        "native_apply_mode": "mesh_first_paint",
        "route": "f10_mesh_first_paint",
        "process": {
            "pid": pid,
            "name": GAME_PROCESS
        },
        "tuning": {
            "stroke_size_texels": 9.0,
            "coverage_step_texels": 9.0,
            "side_source_max_uv": 0.08,
            "front_back_source_max_uv": 0.45,
            "server_batch_limit": 50,
            "server_batch_delay_ms": 150,
            "auto_material": False,
            "auto_material_properties": False,
            "metallic": 0.0,
            "roughness": 1.0,
            "front_region_mode": "fill",
            "side_region_mode": "paint",
            "back_region_mode": "paint",
            "enable_front_paint": False,
            "enable_side_paint": True,
            "enable_back_paint": True,
            "fill_color": "#FFFFFF",
            "fill_color_r": 1.0,
            "fill_color_g": 1.0,
            "fill_color_b": 1.0,
            "fill_metallic": 1.0,
            "fill_roughness": 0.0
        }
    }
    return _send_tcp(payload)


def stop_paint() -> dict:
    resp = _send_tcp({"type": "cancel_paint"})
    _find_and_kill_bridge()
    return resp


def shutdown_bridge() -> dict:
    resp = _send_tcp({"type": "shutdown"})
    _find_and_kill_bridge()
    return resp
