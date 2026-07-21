import os, json, socket, struct, subprocess, sys, time, ctypes, ctypes.wintypes, hashlib, shutil, uuid
from pathlib import Path

GAME_PROCESS = "PenguinHotel-Win64-Shipping.exe"
CREATE_NO_WINDOW = 0x08000000
RUNTIME_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "MecchaCamouflage" / "lite" / "runtime"
_bridge_session = None


def _resource_path(relative):
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, relative)


def _find_game_pid(game_process=GAME_PROCESS):
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
            if pe.szExeFile.lower() == game_process.lower():
                return pe.th32ProcessID
            if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                return None
    finally:
        kernel32.CloseHandle(snapshot)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.digest()


def _build_start_block(pid, guid_bytes, token_bytes, sha256_bytes):
    block = bytearray(128)
    struct.pack_into("<I", block, 0, 0x3153434D)   # "MCS1"
    struct.pack_into("<I", block, 4, 128)
    struct.pack_into("<I", block, 8, 1)
    struct.pack_into("<I", block, 12, pid & 0xFFFFFFFF)
    block[16:32] = guid_bytes
    block[32:64] = token_bytes
    block[64:96] = sha256_bytes
    struct.pack_into("<I", block, 108, 1)
    return bytes(block)


def _parse_injector_result(stdout_text):
    for line in reversed(stdout_text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "result":
            return obj
    return None


def _to_unit(b):
    return round(b / 255.0, 8)


def _parse_color(hex_color):
    if hex_color.startswith("#") and len(hex_color) == 7:
        return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return 255, 255, 255


class BridgeSession:
    """Authenticated session to one injected direct-bridge instance."""

    def __init__(self, port, instance_guid, token_bytes, bridge_hash_hex):
        self.port = port
        self.instance_guid = instance_guid
        self.token_bytes = token_bytes
        self.bridge_hash_hex = bridge_hash_hex

    def _hello_line(self):
        return json.dumps({
            "type": "hello",
            "bootstrap_protocol": 1,
            "instance_id": self.instance_guid.hex,
            "token": self.token_bytes.hex(),
        }, separators=(",", ":"))

    def request(self, command_json, timeout=30):
        try:
            s = socket.create_connection(("127.0.0.1", self.port), timeout)
        except OSError:
            return None
        try:
            s.sendall((self._hello_line() + "\n").encode("utf-8"))
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            if b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                hello_raw = line.decode("utf-8", "replace")
            else:
                hello_raw = buf.decode("utf-8", "replace")
            if not hello_raw.strip():
                return None
            try:
                hello = json.loads(hello_raw)
            except json.JSONDecodeError:
                return None
            if not (hello.get("success") and hello.get("stage") == "hello"):
                return None
            data = (command_json if command_json.endswith("\n") else command_json + "\n").encode("utf-8")
            s.sendall(data)
            s.settimeout(timeout)
            response = b""
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                response += chunk
        finally:
            s.close()
        if not response:
            return None
        try:
            return json.loads(response.decode("utf-8", "replace").strip())
        except json.JSONDecodeError:
            return None


def cleanup_runtime_dir():
    """Remove leftover per-instance bridge directories from past sessions.

    Each injection stages ~6.5 MB (bridge DLL + injector + mesh profiles) into a
    unique bridge-instance-<guid> folder. The directory belonging to a bridge that
    is still loaded in a running game stays locked and is skipped (ignore_errors);
    everything else is reclaimed so these do not accumulate indefinitely.
    """
    if not RUNTIME_DIR.exists():
        return
    for d in RUNTIME_DIR.glob("bridge-instance-*"):
        if d.is_dir():
            shutil.rmtree(d, ignore_errors=True)


def inject_bridge(game_process=GAME_PROCESS) -> str:
    global _bridge_session
    native_dir = Path(_resource_path("native"))
    bridge_dll = native_dir / "runtime-bridge.dll"
    injector_exe = native_dir / "runtime-injector.exe"

    if not bridge_dll.exists() or not injector_exe.exists():
        return f"Native files not found in {native_dir}"

    pid = _find_game_pid(game_process)
    if pid is None:
        return f"Game process '{game_process}' not found"

    exe_path = None
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        buf = ctypes.create_unicode_buffer(260)
        size = ctypes.wintypes.DWORD(260)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            exe_path = buf.value
        ctypes.windll.kernel32.CloseHandle(h)
    if not exe_path:
        return "Could not read game executable path"

    def _get_process_creation_filetime(pid_):
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid_)
        if not h:
            return None
        ct = ctypes.wintypes.FILETIME()
        et = ctypes.wintypes.FILETIME()
        kt = ctypes.wintypes.FILETIME()
        ut = ctypes.wintypes.FILETIME()
        ok = ctypes.windll.kernel32.GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut))
        ctypes.windll.kernel32.CloseHandle(h)
        if not ok:
            return None
        return (ct.dwHighDateTime << 32) | ct.dwLowDateTime

    creation_ft = _get_process_creation_filetime(pid)
    if creation_ft is None:
        return "Could not read game process creation time"

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_runtime_dir()
    instance_guid = uuid.uuid4()
    token_bytes = os.urandom(32)
    bridge_hash = _sha256_file(str(bridge_dll))
    bridge_hash_hex = bridge_hash.hex()

    instance_dir = RUNTIME_DIR / ("bridge-instance-" + instance_guid.hex)
    instance_dir.mkdir(parents=True, exist_ok=True)

    dest_bridge = instance_dir / f"meccha-direct-bridge-v1-{bridge_hash_hex}-{instance_guid.hex}.dll"
    dest_injector = instance_dir / "runtime-injector.exe"
    shutil.copy2(str(bridge_dll), str(dest_bridge))
    shutil.copy2(str(injector_exe), str(dest_injector))

    profiles_target = instance_dir / "mesh-profiles"
    profiles_target.mkdir(parents=True, exist_ok=True)
    mesh_dir = Path(_resource_path("mesh-profiles"))
    if mesh_dir.exists():
        for pf in mesh_dir.glob("*.json"):
            shutil.copy2(str(pf), str(profiles_target / pf.name))

    block = _build_start_block(pid, instance_guid.bytes, token_bytes, bridge_hash)

    try:
        result = subprocess.run(
            [str(dest_injector), "--direct", str(pid), str(creation_ft), exe_path, str(dest_bridge)],
            input=block, capture_output=True, timeout=20,
            creationflags=CREATE_NO_WINDOW,
        )
        stdout = result.stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return "Injector timed out"
    except Exception as e:
        return str(e)

    parsed = _parse_injector_result(stdout)
    if parsed is None:
        detail = stdout.strip().splitlines()
        detail = detail[-1] if detail else "no injector result"
        return f"Injector: {detail}"
    if not parsed.get("success") or parsed.get("state") != "listening":
        return f"Injector failed: {parsed.get('detail')} (state={parsed.get('state')})"
    port = parsed.get("port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return "Injector returned an invalid port"

    _bridge_session = BridgeSession(port, instance_guid, token_bytes, bridge_hash_hex)
    return ""


def ensure_bridge_ready(game_process=GAME_PROCESS) -> str:
    global _bridge_session
    if _bridge_session is not None:
        if _bridge_session.request('{"type":"ping"}', timeout=2) is not None:
            return ""
    err = inject_bridge(game_process)
    if err:
        return err
    if _bridge_session is None:
        return "Bridge session not created"
    for _ in range(20):
        if _bridge_session.request('{"type":"ping"}', timeout=2) is not None:
            return ""
        time.sleep(0.25)
    return "Bridge did not become ready"


def is_bridge_alive() -> bool:
    return bridge_ping(timeout=2)


def bridge_ping(timeout=2):
    global _bridge_session
    if _bridge_session is None:
        return False
    resp = _bridge_session.request('{"type":"ping"}', timeout=timeout)
    if resp is None:
        return False
    return resp.get("success", False)


def bridge_send(payload_json, timeout=30):
    global _bridge_session
    if _bridge_session is None:
        return False, "Bridge not connected", ""
    resp = _bridge_session.request(payload_json, timeout=timeout)
    if resp is None:
        return False, "No response", ""
    return resp.get("success", False), resp.get("message", "") or "", resp.get("stage", "")


def _send_tcp(payload: dict, timeout=30) -> dict:
    ok, msg, stage = bridge_send(json.dumps(payload, separators=(",", ":")), timeout)
    return {"success": ok, "message": msg, "stage": stage}


def _find_and_kill_injector():
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
                    kernel32.CloseHandle(handle)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(pe)):
                return
    finally:
        kernel32.CloseHandle(snapshot)


def _build_tuning(config=None):
    r, g, b = _parse_color(getattr(config, "fill_color", "#FFFFFF") if config else "#FFFFFF")
    return {
        "stroke_size_texels": getattr(config, "stroke_size_texels", 9.0) if config else 9.0,
        "coverage_step_texels": getattr(config, "coverage_step_texels", 9.0) if config else 9.0,
        "side_source_max_uv": getattr(config, "side_source_max_uv", 0.08) if config else 0.08,
        "front_back_source_max_uv": getattr(config, "front_back_source_max_uv", 0.45) if config else 0.45,
        "auto_material": getattr(config, "auto_material", False) if config else False,
        "metallic": getattr(config, "metallic", 0.0) if config else 0.0,
        "roughness": getattr(config, "roughness", 1.0) if config else 1.0,
        "emissive": getattr(config, "emissive", 0.0) if config else 0.0,
        "front_region_mode": getattr(config, "front_region_mode", "fill") if config else "fill",
        "side_region_mode": getattr(config, "side_region_mode", "paint") if config else "paint",
        "back_region_mode": getattr(config, "back_region_mode", "paint") if config else "paint",
        "fill_color": getattr(config, "fill_color", "#FFFFFF") if config else "#FFFFFF",
        "fill_color_r": _to_unit(r),
        "fill_color_g": _to_unit(g),
        "fill_color_b": _to_unit(b),
        "fill_metallic": getattr(config, "fill_metallic", 1.0) if config else 1.0,
        "fill_roughness": getattr(config, "fill_roughness", 0.0) if config else 0.0,
        "fill_emissive": getattr(config, "fill_emissive", 0.0) if config else 0.0,
    }


def paint_now(config=None) -> dict:
    game = getattr(config, "game_process_name", GAME_PROCESS) if config else GAME_PROCESS
    pid = _find_game_pid(game)
    payload = {
        "type": "paint_full_route",
        "native_apply_mode": "mesh_first_paint",
        "route": "f10_mesh_first_paint",
        "preview_only": False,
        "unpreview_only": False,
        "research_artifacts": False,
        "process": {"pid": pid, "name": game},
        "tuning": _build_tuning(config),
    }
    return _send_tcp(payload)


def stop_paint() -> dict:
    return _send_tcp({"type": "cancel_paint"})


def shutdown_bridge() -> dict:
    resp = _send_tcp({"type": "shutdown"})
    _find_and_kill_injector()
    return resp


def paint_start(config=None) -> dict:
    return paint_now(config)


def paint_single(config=None) -> dict:
    return paint_now(config)


def send_preview(config=None) -> dict:
    game = getattr(config, "game_process_name", GAME_PROCESS) if config else GAME_PROCESS
    pid = _find_game_pid(game)
    payload = {
        "type": "paint_full_route",
        "native_apply_mode": "mesh_first_paint",
        "route": "f10_mesh_first_paint",
        "preview_only": True,
        "unpreview_only": False,
        "research_artifacts": False,
        "process": {"pid": pid, "name": game},
        "tuning": _build_tuning(config),
    }
    return _send_tcp(payload)


def send_unpreview(config=None) -> dict:
    game = getattr(config, "game_process_name", GAME_PROCESS) if config else GAME_PROCESS
    pid = _find_game_pid(game)
    payload = {
        "type": "paint_full_route",
        "native_apply_mode": "mesh_first_paint",
        "route": "f10_mesh_first_paint",
        "preview_only": False,
        "unpreview_only": True,
        "research_artifacts": False,
        "process": {"pid": pid, "name": game},
        "tuning": _build_tuning(config),
    }
    return _send_tcp(payload)
