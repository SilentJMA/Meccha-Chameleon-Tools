#!/usr/bin/env python3
"""
HyperVision Engine — exposure volume mapping.
C++ bridge for compute, Python for caching & render data prep.
"""
import json
import math
import os
import socket
import time
from typing import List, Tuple, Optional, Dict

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 47654

# ---------------------------------------------------------------------------
# Low-level TCP
# ---------------------------------------------------------------------------
def _send(cmd: str, payload: dict = None, timeout: float = 30) -> dict:
    msg = json.dumps({
        "type": cmd,
        "request_id": f"{os.urandom(8).hex()}{int(time.time())}",
        "timestamp_utc": int(time.time()),
        "payload": payload or {},
    }) + "\n"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
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


def is_bridge_alive() -> bool:
    r = _send("ping", timeout=3)
    return r.get("success") is True


def bridge_scan_terrain(cx, cy, cz, range_xy=5000, z_samples=3, z_range=1000):
    return _send("scan_terrain", {
        "center": [cx, cy, cz], "range_xy": range_xy,
        "z_samples": z_samples, "z_range": z_range,
    }, timeout=60)


def bridge_visibility_scan(tx, ty, tz, step=80, z_layers=20, radius=2000):
    return _send("visibility_scan", {
        "target": [tx, ty, tz], "step": step,
        "z_layers": z_layers, "radius": radius,
    }, timeout=120)


def bridge_path_find(px, py, pz, tx, ty, tz, cloud):
    return _send("path_find", {
        "player_pos": [px, py, pz], "target_pos": [tx, ty, tz],
        "exposure_cloud": cloud,
    }, timeout=30)


# ---------------------------------------------------------------------------
# Simplify terrain segments
# ---------------------------------------------------------------------------
def simplify_segments(segments: List[Tuple]) -> List[Tuple]:
    by_level = {}
    for seg in segments:
        by_level.setdefault(seg[5], []).append(seg)
    result = []
    for zl, segs in by_level.items():
        seen = set()
        for s in segs:
            key = (round(s[0], -1), round(s[1], -1), round(s[2], -1), round(s[3], -1))
            if key not in seen:
                seen.add(key)
                result.append(s)
    return result


# ---------------------------------------------------------------------------
# HyperVision Engine
# ---------------------------------------------------------------------------
class HyperVisionEngine:
    """Manages dynamic exposure scanning + path finding with C++ bridge.

    Runs a scan loop: for each tracked enemy target, periodically request
    visibility_scan + path_find from the bridge DLL. Caches results.
    Python side does frustum culling & overlay rendering.
    """

    def __init__(self, config):
        self.config = config
        self._bridge_ok = False

        # Cached results
        self.terrain_segments: List[Tuple] = []
        self.terrain_z = 0.0
        self.last_terrain_time = 0

        # Per-target exposure cache: { target_id: { cloud, paths, time } }
        self.target_cache: Dict[int, dict] = {}

        # Scan scheduling
        self._scan_counter = 0

    @property
    def bridge_alive(self):
        return self._bridge_ok

    def check_bridge(self) -> bool:
        self._bridge_ok = is_bridge_alive()
        return self._bridge_ok

    # ------------------------------------------------------------------
    # Terrain
    # ------------------------------------------------------------------
    def refresh_terrain(self, cam_pos, force=False) -> List[Tuple]:
        now = time.time()
        if not force and (now - self.last_terrain_time) < 15:
            return self.terrain_segments
        self.last_terrain_time = now
        self.terrain_z = cam_pos[2] if cam_pos else 0

        if self._bridge_ok:
            r = bridge_scan_terrain(
                cam_pos[0], cam_pos[1], cam_pos[2],
                range_xy=5000, z_samples=5, z_range=1500)
            if r.get("success") and "segments" in r.get("metadata", {}):
                raw = r["metadata"]["segments"]
                self.terrain_segments = [(s[0], s[1], s[2], s[3], s[4], s[5]) for s in raw]
                return self.terrain_segments
        return []

    # ------------------------------------------------------------------
    # Target scanning (called from overlay main loop, ~every 500ms)
    # ------------------------------------------------------------------
    def update_targets(self, players: list, cam_pos) -> dict:
        """Given all players + camera, scan up to N targets. Returns
        { enemy_idx: { cloud, paths, time } } for rendering."""
        if not self._bridge_ok:
            # Fallback: use Python heading, no real exposure data
            return {}

        enemies = [p for p in players if not p.get("is_local", True) and p.get("is_enemy", False)]
        if not enemies:
            return {}

        # Quality-based scan budget
        q = self.config.hv_quality
        max_targets = {"low": 1, "medium": 2, "high": 4, "ultra": 8}.get(q, 2)
        scan_interval = {"low": 3.0, "medium": 2.0, "high": 1.0, "ultra": 0.5}.get(q, 2.0)
        step = {"low": 120, "medium": 80, "high": 50, "ultra": 35}.get(q, 80)

        now = time.time()

        # Round-robin: scan one target per call
        self._scan_counter = (self._scan_counter + 1) % max(len(enemies), 1)
        target = enemies[self._scan_counter % len(enemies)]
        eid = target.get("idx", 0)
        ep = target["pos"]

        # Check cache: if recently scanned, skip
        cached = self.target_cache.get(eid)
        if cached and (now - cached["time"]) < scan_interval:
            return dict(self.target_cache)

        # Fire visibility scan
        r = bridge_visibility_scan(ep[0], ep[1], ep[2],
                                   step=step, z_layers=15, radius=1500)
        cloud = []
        if r.get("success"):
            meta = r.get("metadata", {})
            cloud = meta.get("exposure_cloud", [])

            # Also path find
            pp = target.get("pos", ep)
            paths = []
            if cloud:
                pr = bridge_path_find(cam_pos[0], cam_pos[1], cam_pos[2],
                                      ep[0], ep[1], ep[2], cloud)
                if pr.get("success"):
                    paths = pr.get("metadata", {}).get("paths", [])

            self.target_cache[eid] = {
                "cloud": cloud,
                "paths": paths,
                "time": now,
                "pos": ep,
            }

        return dict(self.target_cache)

    # ------------------------------------------------------------------
    # Path rendering data: world-space → screen-space
    # ------------------------------------------------------------------
    def get_render_data(self, camera, screen_w, screen_h):
        """Returns (path_lines, exposure_dots) for overlay."""
        def _w2s(wp, cam, sw, sh):
            import math as _m
            p, y, r = [_m.radians(x) for x in cam["rot"]]
            sp, cp = _m.sin(p), _m.cos(p)
            sy, cy = _m.sin(y), _m.cos(y)
            fwd = (cp*cy, cp*sy, sp)
            rgt = (r*sp*cy - cy*sy, r*sp*sy + cy*cy, -r*cp)
            up = (-(r*cp*cy + sy*sp), cy*sy - r*cp*cy, r*cp)
            dx, dy, dz = wp[0]-cam["loc"][0], wp[1]-cam["loc"][1], wp[2]-cam["loc"][2]
            vx = dx*fwd[0] + dy*fwd[1] + dz*fwd[2]
            if vx <= 0.1: return None
            vy = dx*rgt[0] + dy*rgt[1] + dz*rgt[2]
            vz = dx*up[0] + dy*up[1] + dz*up[2]
            aspect = sw/sh
            tan_hfov = _m.tan(_m.radians(cam["fov"])/2)
            ndc_x, ndc_y = vy/(vx*tan_hfov), vz/(vx*tan_hfov/aspect)
            return ((1+ndc_x)*sw/2, (1-ndc_y)*sh/2)

        path_lines = []
        exposure_dots = []

        for eid, data in self.target_cache.items():
            if (time.time() - data["time"]) > 5.0:
                continue

            for pt in data.get("cloud", []):
                s = _w2s(pt, camera, screen_w, screen_h)
                if s:
                    exposure_dots.append((int(s[0]), int(s[1]), pt))

            for path in data.get("paths", []):
                screen_pts = []
                for wp in path:
                    s = _w2s(wp, camera, screen_w, screen_h)
                    if s:
                        screen_pts.append((int(s[0]), int(s[1]), wp))
                if len(screen_pts) >= 2:
                    path_lines.append(screen_pts)

        return path_lines, exposure_dots


def world_to_radar(world_x, world_y, local_x, local_y,
                   cam_yaw, radar_cx, radar_cy, half, radar_range):
    """Convert world coords to radar pixel coords."""
    dx = world_x - local_x
    dy = world_y - local_y
    d2d = math.sqrt(dx * dx + dy * dy)
    if d2d > radar_range or d2d < 1.0:
        return None
    angle = math.atan2(dx, dy) - cam_yaw
    r = (d2d / radar_range) * (half - 8)
    rx = radar_cx + r * math.sin(angle)
    ry = radar_cy - r * math.cos(angle)
    return (int(rx), int(ry))
