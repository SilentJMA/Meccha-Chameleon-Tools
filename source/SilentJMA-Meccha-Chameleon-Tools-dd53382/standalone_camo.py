#!/usr/bin/env python3
"""Minimal standalone camouflage tool — tkinter, no PyQt5, no pymem."""
import sys, os, json, time, socket, subprocess, shutil, threading, struct
from dataclasses import dataclass, fields as dc_fields
import ctypes
import tkinter as tk
from tkinter import messagebox

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CONFIG_FILE = os.path.join(os.environ.get("APPDATA", "."), "MecchaCamouflage", "camo_config.json")

@dataclass
class CamoConfig:
    camouflage_enabled: bool = False

def load_config():
    cfg = CamoConfig()
    try:
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE) as f:
                data = json.load(f)
            for field in dc_fields(cfg):
                if field.name in data:
                    setattr(cfg, field.name, data[field.name])
    except Exception:
        pass
    return cfg

def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump({field.name: getattr(cfg, field.name) for field in dc_fields(cfg)}, f, indent=2)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Bridge TCP
# ---------------------------------------------------------------------------
BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 47654

def bridge_request(command, payload=None, timeout=30):
    msg = json.dumps({
        "type": command,
        "request_id": f"{os.urandom(8).hex()}{int(time.time())}",
        "timestamp_utc": int(time.time()),
        "payload": payload or {},
    }) + "\n"
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((BRIDGE_HOST, BRIDGE_PORT))
        s.sendall(msg.encode())
        raw = b""
        while b"\n" not in raw:
            chunk = s.recv(65536)
            if not chunk:
                break
            raw += chunk
        line = raw.split(b"\n")[0]
        return json.loads(line) if line else {"success": False}
    except Exception:
        return {"success": False}
    finally:
        s.close()


# ---------------------------------------------------------------------------
# Engine — no pymem
# ---------------------------------------------------------------------------
class CamouflageEngine:
    DLL_NAME = "meccha-xenos-bridge.dll"
    EXE_NAME = "meccha-camouflage.exe"
    INJECTOR_NAME = "meccha-xenos-injector.exe"
    STABLE_DIR = os.path.join(os.environ.get("APPDATA", "."), "MecchaCamouflage")

    def __init__(self):
        self._bridge_proc = None
        self._game_pid = self._find_game_pid()

    @staticmethod
    def _find_game_pid():
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            TH32CS_SNAPPROCESS = 2
            proc_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if proc_snap == -1:
                return 0

            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", ctypes.c_ulong),
                    ("cntUsage", ctypes.c_ulong),
                    ("th32ProcessID", ctypes.c_ulong),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", ctypes.c_ulong),
                    ("cntThreads", ctypes.c_ulong),
                    ("th32ParentProcessID", ctypes.c_ulong),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", ctypes.c_ulong),
                    ("szExeFile", ctypes.c_char * 260),
                ]

            pe = PROCESSENTRY32()
            pe.dwSize = ctypes.sizeof(PROCESSENTRY32)
            targets = [b"PenguinHotel-Win64-Shipping.exe", b"PenguinHotel.exe"]
            pid = 0
            if kernel32.Process32First(proc_snap, ctypes.byref(pe)):
                while True:
                    for name in targets:
                        if pe.szExeFile.lower() == name.lower():
                            pid = pe.th32ProcessID
                            break
                    if pid:
                        break
                    if not kernel32.Process32Next(proc_snap, ctypes.byref(pe)):
                        break
            kernel32.CloseHandle(proc_snap)
            return pid
        except Exception:
            return 0

    def _get_binary(self, name):
        base = sys._MEIPASS if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, name)

    def _ensure_bridge(self):
        if not self._game_pid:
            return False
        if bridge_request("ping").get("success"):
            return True
        try:
            os.makedirs(self.STABLE_DIR, exist_ok=True)
            for fname in [self.EXE_NAME, self.DLL_NAME, self.INJECTOR_NAME]:
                src = self._get_binary(fname)
                dst = os.path.join(self.STABLE_DIR, fname)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
        except Exception:
            pass
        exe_path = os.path.join(self.STABLE_DIR, self.EXE_NAME)
        if not os.path.isfile(exe_path):
            return False
        try:
            CREATE_NO_WINDOW = 0x08000000
            self._bridge_proc = subprocess.Popen([exe_path], cwd=self.STABLE_DIR, creationflags=CREATE_NO_WINDOW)
        except Exception:
            return False
        # Wait for controller to auto-inject DLL and start bridge (no F10 needed)
        for i in range(120):
            time.sleep(0.5)
            if self._bridge_proc and self._bridge_proc.poll() is not None:
                return False
            if bridge_request("ping").get("success"):
                return True
        return False

    def camo_apply(self):
        if not self._game_pid or not self._ensure_bridge():
            return False
        # Two passes: front + back (rotate 180 between)
        for i, yaw in enumerate([0, 180]):
            if yaw != 0:
                bridge_request("rotate", {"yaw": yaw}, timeout=10)
                time.sleep(1.5)
            resp = bridge_request(
                "paint_full_route",
                {"native_apply_mode": "template_brush_paint",
                 "route": "f10_template_brush_paint",
                 "process": {"pid": self._game_pid, "name": "PenguinHotel-Win64-Shipping.exe"},
                 "max_paints_per_tick": 256, "paint_tick_budget_ms": 16,
                 "brush_radius": 4.0, "template_min_direct_points": 1000,
                 "auto_flush_during_paint": True},
                timeout=120,
            )
            if not resp or not resp.get("success", False):
                return False
        return True

    def camo_stop(self):
        resp = bridge_request("cancel_paint", {}, timeout=10)
        return resp.get("success", False) if resp else False

    def cleanup(self):
        if self._bridge_proc and self._bridge_proc.poll() is None:
            try:
                self._bridge_proc.terminate()
                self._bridge_proc.wait(3)
            except Exception:
                try:
                    self._bridge_proc.kill()
                except Exception:
                    pass
            self._bridge_proc = None


# ---------------------------------------------------------------------------
# Minimal tkinter GUI
# ---------------------------------------------------------------------------
BG = "#0e0e14"
FG = "#bbb"
ACCENT = "#8ab4f8"
BTN_GREEN = "#2a4a3a"
BTN_RED = "#4a2a2a"

class CamoWindow(tk.Tk):
    def __init__(self, config, engine):
        super().__init__()
        self.config = config
        self.engine = engine
        self._camo_thread = None

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.92)
        self.configure(bg=BG)

        self._build_ui()
        self._bind_drag()

        ws = self.winfo_screenwidth()
        hs = self.winfo_screenheight()
        x = (ws - 280) // 2
        y = (hs - 260) // 2
        self.geometry(f"280x260+{x}+{y}")

    def _build_ui(self):
        pad = 10
        frame = tk.Frame(self, bg=BG, highlightbackground="#2a2a3e", highlightthickness=1)
        frame.pack(fill="both", expand=True, padx=4, pady=4)

        title = tk.Label(frame, text="MECCHA CAMOUFLAGE", bg=BG, fg=ACCENT,
                         font=("Segoe UI", 11, "bold"))
        title.pack(pady=(8, 4))

        self.cb_var = tk.BooleanVar(value=self.config.camouflage_enabled)
        cb = tk.Checkbutton(frame, text="Enable Camouflage", variable=self.cb_var,
                           bg=BG, fg=FG, selectcolor=BG, activebackground=BG,
                           activeforeground=FG, font=("Segoe UI", 10))
        cb.pack(anchor="w", padx=pad)
        self.cb_var.trace_add("write", lambda *_: setattr(self.config, "camouflage_enabled", self.cb_var.get()))

        sep = tk.Frame(frame, bg="#2a2a3e", height=1)
        sep.pack(fill="x", padx=pad, pady=4)

        info = tk.Label(frame, text="Launches bridge, triggers F10 to paint",
                       bg=BG, fg="#888", font=("Segoe UI", 9), wraplength=250)
        info.pack(padx=pad, pady=(0, 2))

        self.status = tk.Label(frame, text="Ready", bg=BG, fg="#888",
                              font=("Segoe UI", 9))
        self.status.pack(pady=(0, 4))

        btn_frame = tk.Frame(frame, bg=BG)
        btn_frame.pack(pady=(0, 8))

        self.btn_paint = tk.Button(btn_frame, text="Paint Now", width=14,
                                   bg=BTN_GREEN, fg="#ccc", activebackground="#3a6a4a",
                                   activeforeground="#fff", relief="flat", bd=0,
                                   font=("Segoe UI", 10, "bold"),
                                   padx=8, pady=4, cursor="hand2")
        self.btn_paint.pack(side="left", padx=4)
        self.btn_paint.bind("<Button-1>", lambda e: self._paint())

        self.btn_stop = tk.Button(btn_frame, text="Stop Camo", width=14,
                                  bg=BTN_RED, fg="#ccc", activebackground="#6a3a3a",
                                  activeforeground="#fff", relief="flat", bd=0,
                                  font=("Segoe UI", 10, "bold"),
                                  padx=8, pady=4, cursor="hand2")
        self.btn_stop.pack(side="left", padx=4)
        self.btn_stop.bind("<Button-1>", lambda e: self._stop())

        close_btn = tk.Button(frame, text="X", bg="#3a1a1a", fg="#ccc",
                              activebackground="#5a2a2a", activeforeground="#fff",
                              relief="flat", bd=0, font=("Segoe UI", 9),
                              width=2, cursor="hand2",
                              command=self._close)
        close_btn.place(relx=1.0, x=-4, y=4, anchor="ne")

        # Watermark
        wm = tk.Label(frame, text="Meccha Chameleon Tools",
                      bg=BG, fg="#333333", font=("Segoe UI", 7))
        wm.pack(side="bottom", anchor="se", padx=4, pady=2)

    def _bind_drag(self):
        self._drag_data = {"x": 0, "y": 0}
        def start(ev):
            self._drag_data["x"] = ev.x
            self._drag_data["y"] = ev.y
        def move(ev):
            dx = ev.x - self._drag_data["x"]
            dy = ev.y - self._drag_data["y"]
            self.geometry(f"+{self.winfo_x()+dx}+{self.winfo_y()+dy}")
        self.bind("<Button-1>", start)
        self.bind("<B1-Motion>", move)

    def _set_status(self, text, color="#888"):
        self.status.configure(text=text, fg=color)
        if text not in ("Ready",):
            self.after(3000, lambda: self._set_status("Ready"))

    def _paint(self):
        if self._camo_thread and self._camo_thread.is_alive():
            return
        self._set_status("Painting...", ACCENT)
        self._camo_thread = threading.Thread(target=self._paint_worker, daemon=True)
        self._camo_thread.start()

    def _paint_worker(self):
        ok = self.engine.camo_apply()
        self.after(0, lambda: self._set_status("Painted!" if ok else "Paint failed",
                                                "#4c4" if ok else "#c44"))

    def _stop(self):
        self._set_status("Stopping...", "#fa0")
        threading.Thread(target=self._stop_worker, daemon=True).start()

    def _stop_worker(self):
        ok = self.engine.camo_stop()
        self.after(0, lambda: self._set_status("Stopped" if ok else "Stop failed",
                                                "#4c4" if ok else "#c44"))

    def _close(self):
        self.engine.cleanup()
        self.destroy()


# ---------------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------------
def main():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        pass

    config = load_config()
    engine = CamouflageEngine()

    if not engine._game_pid:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Game Not Found",
            "Could not find the game process.\nMake sure the game is running.")
        root.destroy()
        sys.exit(1)

    win = CamoWindow(config, engine)
    win.protocol("WM_DELETE_WINDOW", win._close)
    win.mainloop()
    save_config(config)


if __name__ == "__main__":
    main()
