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


def render_segments(segments, output_path, center=None, map_size=4096):
    """将地形线段渲染为 PNG。"""
    if not segments:
        print("[!] 无地形数据可渲染")
        return

    # 收集坐标范围
    xs, ys = [], []
    for s in segments:
        for v in [s[0], s[2]]:
            if math.isfinite(v): xs.append(v)
        for v in [s[1], s[3]]:
            if math.isfinite(v): ys.append(v)
    if not xs or not ys:
        print("[!] 无有效坐标")
        return

    if center:
        cx, cy = center
    else:
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2

    # 计算缩放
    world_w = max(xs) - min(xs)
    world_h = max(ys) - min(ys)
    margin = 0.1
    scale = min(map_size * (1 - margin) / max(world_w, 1),
                map_size * (1 - margin) / max(world_h, 1))

    img = Image.new("RGBA", (map_size, map_size), (20, 20, 30, 255))
    draw = ImageDraw.Draw(img)

    # 画网格
    grid_size = 1000  # 每 1000 单位一格
    for gx in range(int(min(xs) / grid_size) * grid_size,
                    int(max(xs) / grid_size) * grid_size + grid_size, grid_size):
        sx, sy = w2s(gx, 0, cx, cy, 0, scale)
        sx = int(sx + map_size / 2)
        draw.line([(sx, 0), (sx, map_size)], fill=(40, 40, 60))

    # 画地形线段
    seg_count = 0
    for s in segments:
        try:
            x1, y1, x2, y2 = s[0], s[1], s[2], s[3]
            if not all(math.isfinite(v) for v in (x1, y1, x2, y2)):
                continue
            sx1, sy1 = w2s(x1, y1, cx, cy, 0, scale)
            sx2, sy2 = w2s(x2, y2, cx, cy, 0, scale)
            sx1 = int(sx1 + map_size / 2)
            sy1 = int(sy1 + map_size / 2)
            sx2 = int(sx2 + map_size / 2)
            sy2 = int(sy2 + map_size / 2)
            if len(s) >= 4:
                stype = s[4] if len(s) > 4 else "wall"
                color = {"wall": (140, 180, 220), "overhang": (120, 80, 80)}.get(stype, (100, 100, 120))
            else:
                color = (100, 100, 120)
            draw.line([(sx1, sy1), (sx2, sy2)], fill=color, width=2)
            seg_count += 1
        except Exception:
            continue

    img.save(output_path, "PNG")
    print(f"[+] 渲染完成: {seg_count} 线段 → {output_path}")
    print(f"    地图范围: X=[{min(xs):.0f}, {max(xs):.0f}], Y=[{min(ys):.0f}, {max(ys):.0f}]")
    print(f"    画布大小: {map_size}x{map_size}, 缩放: {scale:.2f} px/单位")


def fetch_via_bridge():
    """通过 bridge DLL 获取地形数据（C++ 计算）。"""
    from meccha_chameleon_tools.hypervision import _send
    print("[*] 尝试 bridge DLL...")
    r = _send("scan_terrain", {"center": [0, 0, 0], "range_xy": 50000,
                                "z_samples": 1, "z_range": 2000}, timeout=60)
    if r.get("success") and "segments" in r.get("metadata", {}):
        segs = r["metadata"]["segments"]
        print(f"[+] bridge 返回 {len(segs)} 线段")
        return [(s[0], s[1], s[2], s[3], s[4], s[5]) for s in segs]
    print("[!] bridge 不可用")
    return None


def fetch_via_python():
    """Python pymem fallback。"""
    from meccha_chameleon_tools.core import MecchaESP
    from meccha_chameleon_tools.hypervision import simplify_segments
    print("[*] Python pymem fallback...")
    esp = MecchaESP()
    segs = esp.scan_terrain()
    if segs:
        segs = simplify_segments(segs)
        print(f"[+] Python 返回 {len(segs)} 线段")
    return segs


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
        render_segments(segments, output)


if __name__ == "__main__":
    main()
