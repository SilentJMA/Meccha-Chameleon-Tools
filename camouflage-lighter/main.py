import sys, os, json, struct, socket, subprocess, threading, queue, hashlib, uuid, ctypes, shutil
import tkinter as tk
import ctypes.wintypes as wt
from pathlib import Path
from datetime import datetime

try:
    import psutil
except ImportError:
    psutil = None

GAME_PROCESS_NAME = "PenguinHotel-Win64-Shipping.exe"
BASE_DIR = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).parent
NATIVE_DIR = BASE_DIR / "native"
MESH_DIR = BASE_DIR / "mesh-profiles"
RUNTIME_DIR = Path(os.environ.get("LOCALAPPDATA", ".")) / "MecchaCamouflage" / "lite" / "runtime"

WM_HOTKEY = 0x0312
user32 = ctypes.windll.user32

WPARAM = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
LPARAM = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_longlong, ctypes.c_uint, WPARAM, LPARAM)

FILL_COLOR = "#FFFFFF"

# v1.6.2 tuning. emissive / fill_emissive default to 0.0 so paint no longer renders as a
# glow (v1.6.2 "Fixed material rendering issues that could leave painted surfaces looking
# incorrectly emissive"). Values mirror the official app defaults (Models.cs).
PAINT_TUNING = {
    "brush_1_enabled": False, "brush_1_size_texels": 25.0,
    "brush_2_enabled": True, "brush_2_size_texels": 5.0,
    "server_batch_auto_adapt": True, "server_batch_limit": 20, "server_batch_pacing_ms": 50,
    "coverage_step_texels": 5.0,
    "side_source_max_uv": 0.08, "front_back_source_max_uv": 0.45,
    "auto_material": False,
    "metallic": 0.0, "roughness": 1.0, "emissive": 0.0,
    "front_region_mode": "fill", "side_region_mode": "paint", "back_region_mode": "paint",
    "fill_metallic": 1.0, "fill_roughness": 0.0, "fill_emissive": 0.0,
}


def to_unit(b):
    return round(b / 255.0, 8)


def parse_color(hex_color):
    if hex_color.startswith("#") and len(hex_color) == 7:
        return int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return 255, 255, 255


def find_game_process():
    name = Path(GAME_PROCESS_NAME).stem
    for proc in (psutil.process_iter(["pid", "name"]) if psutil else []):
        try:
            if proc.info["name"] and name.lower() in proc.info["name"].lower():
                return proc.info["pid"], proc.info["name"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None, None


def get_process_creation_filetime(pid):
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    ct = wt.FILETIME()
    et = wt.FILETIME()
    kt = wt.FILETIME()
    ut = wt.FILETIME()
    ok = ctypes.windll.kernel32.GetProcessTimes(
        h, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut))
    ctypes.windll.kernel32.CloseHandle(h)
    if not ok:
        return None
    return (ct.dwHighDateTime << 32) | ct.dwLowDateTime


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.digest()


def build_start_block(pid, guid_bytes, token_bytes, sha256_bytes):
    block = bytearray(128)
    struct.pack_into("<I", block, 0, 0x3153434D)   # magic "MCS1"
    struct.pack_into("<I", block, 4, 128)            # size
    struct.pack_into("<I", block, 8, 1)             # abi version
    struct.pack_into("<I", block, 12, pid & 0xFFFFFFFF)
    block[16:32] = guid_bytes                         # 16-byte instance GUID (big-endian)
    block[32:64] = token_bytes                        # 32-byte connection token
    block[64:96] = sha256_bytes                       # 32-byte bridge hash
    struct.pack_into("<I", block, 108, 1)            # protocol = BridgeBootstrapProtocolV1
    # bytes 96..107 and 112..127 remain zero: requested_port=0 so the OS assigns the port.
    return bytes(block)


def parse_injector_result(stdout_text):
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


def build_paint_payload(process_pid, process_name, preview_only=False, unpreview_only=False):
    r, g, b = parse_color(FILL_COLOR)
    t = PAINT_TUNING
    payload = {
        "type": "paint_full_route",
        "native_apply_mode": "mesh_first_paint",
        "route": "f10_mesh_first_paint",
        "server_batch_rpc": "packed",
        "packed_route": "component",
        "preview_only": preview_only,
        "unpreview_only": unpreview_only,
        "research_artifacts": False,
        "process": {"pid": process_pid, "name": process_name},
        "tuning": {
            "brush_1_enabled": t["brush_1_enabled"],
            "brush_1_size_texels": t["brush_1_size_texels"],
            "brush_2_enabled": t["brush_2_enabled"],
            "brush_2_size_texels": t["brush_2_size_texels"],
            "server_batch_auto_adapt": t["server_batch_auto_adapt"],
            "server_batch_limit": t["server_batch_limit"],
            "server_batch_pacing_ms": t["server_batch_pacing_ms"],
            "coverage_step_texels": t["coverage_step_texels"],
            "side_source_max_uv": t["side_source_max_uv"],
            "front_back_source_max_uv": t["front_back_source_max_uv"],
            "auto_material": t["auto_material"],
            "metallic": t["metallic"],
            "roughness": t["roughness"],
            "emissive": t["emissive"],
            "front_region_mode": t["front_region_mode"],
            "side_region_mode": t["side_region_mode"],
            "back_region_mode": t["back_region_mode"],
            "fill_color": FILL_COLOR,
            "fill_color_r": to_unit(r),
            "fill_color_g": to_unit(g),
            "fill_color_b": to_unit(b),
            "fill_metallic": t["fill_metallic"],
            "fill_roughness": t["fill_roughness"],
            "fill_emissive": t["fill_emissive"],
        },
    }
    return json.dumps(payload, separators=(",", ":"))


class BridgeSession:
    """Authenticates and talks to one injected direct bridge instance."""

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

    def _recv_line(self, sock, buf):
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        if b"\n" in buf:
            line, _, rest = buf.partition(b"\n")
            return line.decode("utf-8", "replace"), rest
        return buf.decode("utf-8", "replace"), b""

    def request(self, command_json, timeout=30):
        try:
            s = socket.create_connection(("127.0.0.1", self.port), timeout)
        except OSError:
            return None
        try:
            s.sendall((self._hello_line() + "\n").encode("utf-8"))
            buf = b""
            hello_raw, buf = self._recv_line(s, buf)
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
            obj = json.loads(response.decode("utf-8", "replace").strip())
        except json.JSONDecodeError:
            return None
        return obj


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


def inject_bridge():
    bridge_dll = NATIVE_DIR / "runtime-bridge.dll"
    injector_exe = NATIVE_DIR / "runtime-injector.exe"
    if not bridge_dll.exists() or not injector_exe.exists():
        return None, f"Native files not found in {NATIVE_DIR}"

    pid, _ = find_game_process()
    if pid is None:
        return None, "Game not found"

    try:
        proc = psutil.Process(pid)
        exe_path = proc.exe()
    except Exception:
        return None, "Could not read game process path"
    if not exe_path:
        return None, "Game executable path unavailable"

    creation_ft = get_process_creation_filetime(pid)
    if creation_ft is None:
        return None, "Could not read game process creation time"

    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    cleanup_runtime_dir()
    instance_guid = uuid.uuid4()
    token_bytes = os.urandom(32)
    bridge_hash = sha256_file(str(bridge_dll))
    bridge_hash_hex = bridge_hash.hex()

    instance_dir = RUNTIME_DIR / ("bridge-instance-" + instance_guid.hex)
    instance_dir.mkdir(parents=True, exist_ok=True)

    dest_bridge = instance_dir / f"meccha-direct-bridge-v1-{bridge_hash_hex}-{instance_guid.hex}.dll"
    dest_injector = instance_dir / "runtime-injector.exe"
    shutil.copy2(str(bridge_dll), str(dest_bridge))
    shutil.copy2(str(injector_exe), str(dest_injector))

    profiles_target = instance_dir / "mesh-profiles"
    profiles_target.mkdir(parents=True, exist_ok=True)
    if MESH_DIR.exists():
        for pf in MESH_DIR.glob("*.json"):
            shutil.copy2(str(pf), str(profiles_target / pf.name))

    block = build_start_block(pid, instance_guid.bytes, token_bytes, bridge_hash)

    try:
        result = subprocess.run(
            [str(dest_injector), "--direct", str(pid), str(creation_ft), exe_path, str(dest_bridge)],
            input=block, capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        stdout = result.stdout.decode("utf-8", "replace")
        stderr = result.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return None, "Injector timed out"
    except Exception as e:
        return None, str(e)

    parsed = parse_injector_result(stdout)
    if parsed is None:
        detail = (stderr or stdout).strip().splitlines()
        detail = detail[-1] if detail else "no injector result"
        return None, f"Injector: {detail}"
    if not parsed.get("success") or parsed.get("state") != "listening":
        return None, f"Injector failed: {parsed.get('detail')} (state={parsed.get('state')})"
    port = parsed.get("port")
    if not isinstance(port, int) or not (1 <= port <= 65535):
        return None, "Injector returned an invalid port"

    session = BridgeSession(port, instance_guid, token_bytes, bridge_hash_hex)
    return session, "Injection done"


def ensure_bridge():
    if getattr(ensure_bridge, "_session", None) is not None:
        if ensure_bridge._session.request('{"type":"ping"}', timeout=2) is not None:
            return ensure_bridge._session, "Bridge ready"
    pid, _ = find_game_process()
    if pid is None:
        return None, "Game not found"
    session, msg = inject_bridge()
    if session is None:
        return None, msg
    ensure_bridge._session = session
    import time as _time
    for _ in range(20):
        if session.request('{"type":"ping"}', timeout=2) is not None:
            return session, "Bridge ready"
        _time.sleep(0.25)
    return None, "Bridge did not become ready"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Camouflage")
        self.root.geometry("320x420")
        self.root.resizable(False, False)
        self.root.configure(bg="#0d0d0d")

        self.hotkey_queue = queue.Queue()
        self.bridge_ready = False
        self.bridge_status = "Initializing..."
        self.hotkey_window = None
        self._running = True
        self._wndproc_ref = None
        self._injection_attempted = False
        self._session = None
        self._bridge_lock = threading.Lock()
        self._check_after_id = None

        self._build_ui()
        self.root.after(100, self._poll_queue)
        self._check_after_id = self.root.after(500, self._check_bridge)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _make_button(self, parent, text, color, hover_color, command):
        btn = tk.Button(
            parent, text=text, command=command,
            bg="#1a1a1a", fg=color, activebackground=hover_color, activeforeground=color,
            relief=tk.FLAT, bd=1, highlightthickness=1,
            highlightbackground="#333333", font=("Segoe UI", 11, "bold"),
            height=2, cursor="hand2",
        )
        btn.bind("<Enter>", lambda e, b=btn, c=hover_color: b.configure(bg=c))
        btn.bind("<Leave>", lambda e, b=btn: b.configure(bg="#1a1a1a"))
        return btn

    def _build_ui(self):
        self.frame = tk.Frame(self.root, bg="#0d0d0d", padx=24, pady=20)
        self.frame.pack(fill=tk.BOTH, expand=True)

        title = tk.Label(
            self.frame, text="Camouflage",
            bg="#0d0d0d", fg="#ffffff", font=("Segoe UI", 16, "bold"),
        )
        title.pack()

        sep = tk.Frame(self.frame, bg="#2a2a2a", height=1)
        sep.pack(fill=tk.X, pady=(0, 16))

        btns = [
            ("Start Painting", "#4fd16a", "#1a4a2a", self._do_paint),
            ("Stop Painting", "#e74c3c", "#4a1a1a", self._do_stop),
            ("Review", "#3498db", "#1a2a4a", self._do_review),
            ("Unreview", "#f39c12", "#4a3a1a", self._do_unreview),
        ]
        for text, color, hover, cmd in btns:
            btn = self._make_button(self.frame, text.strip(), color, hover, cmd)
            btn.pack(fill=tk.X, pady=5)

        self.status_var = tk.StringVar(value=self.bridge_status)
        self.status_label = tk.Label(
            self.frame, textvariable=self.status_var,
            bg="#0d0d0d", fg="#888888", font=("Segoe UI", 9), cursor="hand2",
        )
        self.status_label.pack(side=tk.BOTTOM, pady=(12, 0))
        self.status_label.bind("<Button-1>", lambda e: self._retry_bridge())

        self.log_var = tk.StringVar(value="")
        self.log_label = tk.Label(
            self.frame, textvariable=self.log_var,
            bg="#0d0d0d", fg="#555555", font=("Segoe UI", 8),
        )
        self.log_label.pack(side=tk.BOTTOM)

    def _retry_bridge(self):
        self._injection_attempted = False
        self._session = None
        ensure_bridge._session = None
        # Cancel the pending poll so we don't spawn a second self-rescheduling loop.
        if self._check_after_id is not None:
            self.root.after_cancel(self._check_after_id)
            self._check_after_id = None
        self._log("Retrying bridge connection...")
        self._check_bridge()

    def _log(self, msg):
        now = datetime.now().strftime("%H:%M:%S")
        line = f"[{now}] {msg}"
        print(line)
        # May be called from worker threads; marshal the widget update to the UI thread.
        self.root.after(0, lambda: self.log_var.set(line))

    def _check_bridge(self):
        if not self._running:
            return
        # Schedule the next tick up front, then run the (blocking) ping off the UI thread.
        self._check_after_id = self.root.after(5000, self._check_bridge)
        threading.Thread(target=self._check_bridge_worker, daemon=True).start()

    def _check_bridge_worker(self):
        # If a command is already in flight, the bridge is in use (hence alive);
        # skip this poll rather than opening a competing connection.
        if not self._bridge_lock.acquire(blocking=False):
            return
        try:
            session = self._session
            ok = session is not None and session.request('{"type":"ping"}', timeout=2) is not None
        finally:
            self._bridge_lock.release()
        self.root.after(0, lambda: self._after_bridge_check(ok))

    def _after_bridge_check(self, ok):
        if not self._running:
            return
        self.bridge_ready = ok
        if ok:
            self._set_status("Ready", "#4fd16a")
        elif not self._injection_attempted:
            self._injection_attempted = True
            self._set_status("Connecting...", "#f39c12")
            self._log("Attempting bridge injection...")
            threading.Thread(target=self._try_inject, daemon=True).start()
        else:
            self._set_status("Offline", "#e74c3c")

    def _set_status(self, text, color):
        self.bridge_status = text
        self.status_label.configure(fg=color)
        self.status_var.set(f"Bridge: {self.bridge_status}")

    def _try_inject(self):
        session, msg = ensure_bridge()
        self.root.after(0, lambda: self._on_inject_result(session, msg))

    def _on_inject_result(self, session, msg):
        if session is not None:
            self._session = session
            ensure_bridge._session = session
            self._log("Bridge ready")
            self.bridge_ready = True
            self._set_status("Ready", "#4fd16a")
        else:
            self._log(f"Injection failed: {msg}")
            self._set_status(f"Offline ({msg})", "#e74c3c")

    def _poll_queue(self):
        if not self._running:
            return
        try:
            while True:
                action = self.hotkey_queue.get_nowait()
                self._log(f"Hotkey: {action}")
                getattr(self, f"_do_{action}", lambda: None)()
        except queue.Empty:
            pass
        self.root.after(50, self._poll_queue)

    def _dispatch(self, fn):
        """Run a blocking bridge command on a worker thread.

        Serialized via _bridge_lock so stacked button clicks (and the periodic
        ping) never open competing connections, and so the socket round-trip
        never blocks the tkinter UI thread.
        """
        if self._session is None:
            self._log("Bridge not ready")
            return
        if not self._bridge_lock.acquire(blocking=False):
            self._log("Bridge busy, please wait...")
            return

        def worker():
            try:
                fn()
            finally:
                self._bridge_lock.release()

        threading.Thread(target=worker, daemon=True).start()

    def _send_paint(self, preview=False, unpreview=False):
        if self._session is None:
            self._log("Bridge not ready")
            return
        pid, name = find_game_process()
        if pid is None:
            self._log("Game process not found")
            return
        payload = build_paint_payload(pid, name, preview, unpreview)
        resp = self._session.request(payload)
        act = "Review" if preview else ("Unreview" if unpreview else "Start Painting")
        if resp is None:
            self._log(f"{act}: no response")
            return
        ok = resp.get("success", False)
        msg = resp.get("message", "") or resp.get("stage", "")
        self._log(f"{act}: {'OK' if ok else 'FAIL'} - {msg}")

    def _send_stop(self):
        resp = self._session.request('{"type":"cancel_paint"}')
        if resp is None:
            self._log("Stop: no response")
            return
        ok = resp.get("success", False)
        msg = resp.get("message", "") or resp.get("stage", "")
        self._log(f"Stop: {'OK' if ok else 'FAIL'} - {msg}")

    def _do_paint(self):
        self._log("Starting paint...")
        self._dispatch(self._send_paint)

    def _do_stop(self):
        self._dispatch(self._send_stop)

    def _do_review(self):
        self._dispatch(lambda: self._send_paint(preview=True))

    def _do_unreview(self):
        self._dispatch(lambda: self._send_paint(unpreview=True))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_HOTKEY:
            hotkey_map = {0x70: "review", 0x71: "unreview", 0x79: "stop", 0x7A: "paint"}
            action = hotkey_map.get(wparam)
            if action:
                self.hotkey_queue.put(action)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _start_hotkeys(self):
        HWND_MESSAGE = -3
        wc = wt.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        wc.lpszClassName = "CamouflageHW"
        wc.hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wnd_proc)
        wc.lpfnWndProc = self._wndproc_ref
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            self._log("Failed to register hotkey window")
            return
        hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "", 0, 0, 0, 0, 0, HWND_MESSAGE, None, wc.hInstance, None)
        if not hwnd:
            self._log("Failed to create hotkey window")
            return
        self.hotkey_window = hwnd
        hotkey_map = {0x70: "review", 0x71: "unreview", 0x79: "stop", 0x7A: "paint"}
        MOD_NOREPEAT = 0x4000
        for vk in hotkey_map:
            if not user32.RegisterHotKey(hwnd, vk, MOD_NOREPEAT, vk):
                self._log(f"Hotkey registration failed for {vk}")
        msg = wt.MSG()
        while self._running:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _on_close(self):
        self._running = False
        if self.hotkey_window:
            hotkey_list = [0x70, 0x71, 0x79, 0x7A]
            for vk in hotkey_list:
                user32.UnregisterHotKey(self.hotkey_window, vk)
            user32.DestroyWindow(self.hotkey_window)
            self.hotkey_window = None
        self.root.destroy()

    def run(self):
        t = threading.Thread(target=self._start_hotkeys, daemon=True)
        t.start()
        self.root.mainloop()


if __name__ == "__main__":
    if psutil is None:
        print("ERROR: psutil not installed. Run: pip install psutil")
        sys.exit(1)
    App().run()
