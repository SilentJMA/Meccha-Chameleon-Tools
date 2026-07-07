#!/usr/bin/env python3
"""HyperVision — thread-safe bridge client. All TCP in a worker thread."""
import json, math, os, socket, threading, time
from typing import List, Tuple

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 47654
_bridge_ok = False
_bridge_lock = threading.Lock()
_bridge_checked = 0.0
_BRIDGE_TTL = 3.0


def _send(cmd: str, payload: dict = None, timeout: float = 5) -> dict:
    msg = json.dumps({"type": cmd,
                       "request_id": f"{os.urandom(8).hex()}{int(time.time())}",
                       "timestamp_utc": int(time.time()),
                       "payload": payload or {}}) + "\n"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((BRIDGE_HOST, BRIDGE_PORT))
        s.sendall(msg.encode())
        raw = b""
        while b"\n" not in raw:
            c = s.recv(65536)
            if not c: break
            raw += c
        return json.loads(raw.split(b"\n")[0]) if raw else {"success": False}
    except Exception:
        return {"success": False}
    finally:
        s.close()


def ping_fast() -> bool:
    global _bridge_ok, _bridge_checked
    now = time.time()
    with _bridge_lock:
        if now - _bridge_checked < _BRIDGE_TTL:
            return _bridge_ok
        _bridge_checked = now
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect((BRIDGE_HOST, BRIDGE_PORT))
        s.sendall(b'{"type":"ping","request_id":"p","timestamp_utc":0,"payload":{}}\n')
        s.recv(1024)
        with _bridge_lock:
            _bridge_ok = True
    except Exception:
        with _bridge_lock:
            _bridge_ok = False
    finally:
        s.close()
    return _bridge_ok


def _bg(fn, *a, **kw):
    """Run fn in daemon thread (fire-and-forget)."""
    threading.Thread(target=fn, args=a, kwargs=kw, daemon=True).start()


# Public API (all fire-and-forget to avoid UI blocking)
def bg_scan_terrain(cx, cy, cz, cb, range_xy=5000, z_samples=5, z_range=1500):
    def _w():
        r = _send("scan_terrain", {"center": [cx, cy, cz], "range_xy": range_xy,
                                    "z_samples": z_samples, "z_range": z_range}, timeout=60)
        segs = []
        if r.get("success") and "segments" in r.get("metadata", {}):
            segs = [(s[0], s[1], s[2], s[3], s[4], s[5]) for s in r["metadata"]["segments"]]
        cb(segs)
    _bg(_w)


def bg_visibility_scan(tx, ty, tz, cb, step=80, z_layers=15, radius=1500):
    def _w():
        r = _send("visibility_scan", {"target": [tx, ty, tz], "step": step,
                                       "z_layers": z_layers, "radius": radius}, timeout=120)
        cb(r.get("metadata", {}).get("exposure_cloud", []) if r.get("success") else [])
    _bg(_w)


def bg_path_find(px, py, pz, tx, ty, tz, cloud, cb):
    def _w():
        r = _send("path_find", {"player_pos": [px, py, pz], "target_pos": [tx, ty, tz],
                                 "exposure_cloud": cloud}, timeout=30)
        cb(r.get("metadata", {}).get("paths", []) if r.get("success") else [])
    _bg(_w)


def bg_start_hv(tx, ty, tz, px, py, pz, quality=1):
    _bg(lambda: _send("start_hypervision", {"target": [tx, ty, tz], "player": [px, py, pz],
                                             "quality": quality}, timeout=60))


def bg_update_hv(tx, ty, tz, px, py, pz):
    _bg(lambda: _send("update_hypervision", {"target": [tx, ty, tz], "player": [px, py, pz]}, timeout=10))


def bg_stop_hv():
    _bg(lambda: _send("stop_hypervision", timeout=10))


_injecting = False

def bg_ensure_bridge():
    """Auto-inject bridge DLL once; no concurrent attempts."""
    global _injecting
    if _injecting:
        return
    _injecting = True
    def _w():
        global _injecting
        try:
            from meccha_chameleon_tools.camouflage import ensure_bridge_ready
            ensure_bridge_ready()
        finally:
            _injecting = False
    _bg(_w)


def simplify_segments(segments: List[Tuple]) -> List[Tuple]:
    by_level = {}
    for s in segments:
        by_level.setdefault(s[5], []).append(s)
    out = []
    for zl, segs in by_level.items():
        seen = set()
        for s in segs:
            k = (round(s[0], -1), round(s[1], -1), round(s[2], -1), round(s[3], -1))
            if k not in seen:
                seen.add(k)
                out.append(s)
    return out
