#!/usr/bin/env python3
"""
全景地图渲染器 — 从 bridge DLL 或 Python fallback 获取地形数据 → 输出 PNG。
用法:
  python tools/map_renderer.py                    # 尝试 bridge，回退 Python
  python tools/map_renderer.py --from-json data.json  # 从已有 JSON 渲染
"""
import json, math, os, sys, time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from PIL import Image, ImageDraw
except ImportError:
    print("[!] 需要 Pillow: pip install Pillow")
    sys.exit(1)


def w2s(wx, wy, cx, cy, yaw_deg, scale):
    """将世界坐标 (wx, wy) 投影到地图画布坐标。"""
    dx = wx - cx
    dy = wy - cy
    yaw = math.radians(yaw_deg)
    rx = dx * math.cos(yaw) - dy * math.sin(yaw)
    ry = dx * math.sin(yaw) + dy * math.cos(yaw)
    return (rx * scale, -ry * scale)


def render_points(points, output_path, map_size=4096):
    """将地形点云渲染为 2D 俯视图 PNG。"""
    if not points:
        print("[!] 无数据可渲染")
        return

    xs = [p[0] for p in points if math.isfinite(p[0])]
    ys = [p[1] for p in points if math.isfinite(p[1])]
    if not xs or not ys:
        print("[!] 无有效坐标")
        return

    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    world_w = max(xs) - min(xs)
    world_h = max(ys) - min(ys)
    margin = 0.05
    scale = min(map_size * (1 - margin) / max(world_w, 1),
                map_size * (1 - margin) / max(world_h, 1))

    img = Image.new("RGBA", (map_size, map_size), (20, 20, 30, 255))
    draw = ImageDraw.Draw(img)

    # 网格 (每 10000 单位)
    grid = 10000
    for gx in range(int(min(xs) // grid) * grid, int(max(xs) // grid) * grid + grid, grid):
        sx = int(w2s(gx, 0, cx, cy, 0, scale)[0] + map_size / 2)
        draw.line([(sx, 0), (sx, map_size)], fill=(35, 35, 50))
    for gy in range(int(min(ys) // grid) * grid, int(max(ys) // grid) * grid + grid, grid):
        sy = int(w2s(0, gy, cx, cy, 0, scale)[1] + map_size / 2)
        draw.line([(0, sy), (map_size, sy)], fill=(35, 35, 50))

    # 按类名分类着色
    colors = {
        "StaticMeshActor": (100, 180, 255),
        "StaticMesh": (100, 160, 220),
        "SplineMesh": (80, 200, 120),
        "InstancedStaticMesh": (200, 180, 100),
    }
    default_color = (140, 140, 160)
    drawn = 0
    for x, y, cls in points:
        try:
            sx = int(w2s(x, y, cx, cy, 0, scale)[0] + map_size / 2)
            sy = int(w2s(x, y, cx, cy, 0, scale)[1] + map_size / 2)
            color = default_color
            for k, c in colors.items():
                if k in cls:
                    color = c
                    break
            draw.ellipse([(sx - 1, sy - 1), (sx + 1, sy + 1)], fill=color)
            drawn += 1
        except Exception:
            continue

    img.save(output_path, "PNG")
    print(f"[+] 渲染完成: {drawn} 个对象 → {output_path}", flush=True)
    print(f"    范围: X [{min(xs):.0f}, {max(xs):.0f}]  Y [{min(ys):.0f}, {max(ys):.0f}]", flush=True)


def fetch_via_bridge():
    from meccha_chameleon_tools.hypervision import _send
    print("[*] Bridge DLL scan_terrain...")
    r = _send("scan_terrain", {"center": [0, 0, 0], "range_xy": 50000,
                                "z_samples": 1, "z_range": 2000}, timeout=10)
    if r.get("success") and "segments" in r.get("metadata", {}):
        segs = r["metadata"]["segments"]
        print(f"[+] bridge returns {len(segs)} segs")
        return [(s[0], s[1], s[2], s[3], s[4], s[5]) for s in segs]
    print("[!] bridge not available")
    return None


def fetch_via_python():
    import sys
    from meccha_chameleon_tools.core import MecchaESP
    print("[*] Python pymem fallback...", flush=True)
    try:
        esp = MecchaESP()
        print("[+] Scanning terrain (up to 20000 objects)...", flush=True)
        t0 = time.time()
        segs = esp.scan_terrain()
        dt = time.time() - t0
        print(f"[+] Scan done: {len(segs)} points in {dt:.1f}s", flush=True)
        if segs:
            print(f"[+] Python returns {len(segs)} points", flush=True)
            return segs
        print("[!] Python scan returned 0 segments", flush=True)
    except Exception as e:
        print(f"[!] Python fallback failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
    return None


def main():
    segments = None
    output = os.path.join(os.path.dirname(__file__), "..", "map_output.png")

    if "--from-json" in sys.argv:
        idx = sys.argv.index("--from-json")
        if idx + 1 < len(sys.argv):
            with open(sys.argv[idx + 1]) as f:
                data = json.load(f)
            segments = [tuple(s) for s in data]
    else:
        segments = fetch_via_bridge()
        if not segments:
            segments = fetch_via_python()

    if "--output" in sys.argv:
        idx = sys.argv.index("--output")
        if idx + 1 < len(sys.argv):
            output = sys.argv[idx + 1]

    if segments:
        render_points(segments, output)


if __name__ == "__main__":
    main()
