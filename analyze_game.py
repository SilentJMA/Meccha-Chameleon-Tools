#!/usr/bin/env python3
"""
Standalone game process analyzer — injects via pymem, dumps map/nav/actor info.
Usage: python analyze_game.py [--verbose]
"""
import sys, os, struct, math, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["PYTHONIOENCODING"] = "utf-8"

from meccha_chameleon_tools.core import (
    MecchaESP, rp, ru32, rfloat, rvec3, rvec3_f,
    read_array, OFFSETS, PatternScanner, FNameResolver, UObjectArray
)

PROCESS = "PenguinHotel-Win64-Shipping.exe"

def fmt_addr(a):
    return f"0x{a:016X}" if a else "0x0000000000000000"

def main():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

    print(f"[*] Attaching to {PROCESS}...")
    esp = MecchaESP()
    print(f"[+] Connected. PID={esp.pm.process_id}")
    print(f"[+] GUObjectArray: {fmt_addr(esp.guobject_array)}")
    print(f"[+] FNamePool: {fmt_addr(esp.fname_pool)}")

    # ---- 1. Camera ----
    cam = esp.get_camera()
    if cam:
        print(f"\n[*] Camera position: ({cam['loc'][0]:.1f}, {cam['loc'][1]:.1f}, {cam['loc'][2]:.1f})")
        print(f"[*] Camera rotation: ({cam['rot'][0]:.1f}, {cam['rot'][1]:.1f}, {cam['rot'][2]:.1f})")
        print(f"[*] FOV: {cam['fov']:.1f}")
    else:
        print("\n[!] No camera available")

    # ---- 2. World / Level ----
    world = esp._get_world()
    print(f"\n[*] UWorld: {fmt_addr(world)}")
    if world:
        persistent_level = rp(esp.pm, world + 0x30)
        print(f"[*] PersistentLevel: {fmt_addr(persistent_level)}")
        if persistent_level:
            actors_data = rp(esp.pm, persistent_level + 0x98)
            actors_count = ru32(esp.pm, persistent_level + 0xA0)
            print(f"[*] Actors in level: {actors_count}")

    # ---- 3. Navigation System ----
    print(f"\n{'='*60}")
    print("[*] NAVIGATION SYSTEM ANALYSIS")
    print(f"{'='*60}")

    nav_classes_found = []
    nav_instances = {}

    for obj in esp.objects.iter_objects():
        try:
            cls = esp.objects.class_name(obj)
            name = esp.objects.obj_name(obj)
            if not cls or not name:
                continue
            if name.startswith("Default__"):
                continue
            low_cls = cls.lower()
            if any(x in low_cls for x in ["navigation", "navdata", "navmesh", "recast",
                                            "navsystem", "navmodifier", "navlink",
                                            "navarea", "navfilter", "navcollision",
                                            "navinvoker", "navpath", "navnode"]):
                nav_classes_found.append((cls, name, obj))
                if cls not in nav_instances:
                    nav_instances[cls] = []
                nav_instances[cls].append((name, obj))
        except Exception:
            continue

    if nav_classes_found:
        print(f"\n[+] Navigation-related objects found: {len(nav_classes_found)}")
        for cls, name, addr in sorted(nav_classes_found, key=lambda x: x[0]):
            print(f"    {cls:50s} | {name:30s} | {fmt_addr(addr)}")

        # Try to read NavData / RecastNavMesh
        for cls_name, instances in nav_instances.items():
            if "NavData" in cls_name or "NavMesh" in cls_name or "Recast" in cls_name:
                for inst_name, inst_addr in instances:
                    print(f"\n[*] Reading {cls_name} ({inst_name}) at {fmt_addr(inst_addr)}")
                    # Read bounds
                    try:
                        bounds_x = rfloat(esp.pm, inst_addr + 0x280)
                        bounds_y = rfloat(esp.pm, inst_addr + 0x284)
                        bounds_z = rfloat(esp.pm, inst_addr + 0x288)
                        bounds_w = rfloat(esp.pm, inst_addr + 0x28C)
                        print(f"    Bounds: ({bounds_x:.1f}, {bounds_y:.1f}, {bounds_z:.1f}) w={bounds_w:.1f}")
                    except Exception:
                        print("    Bounds: N/A")

                    # Try to read tile count
                    try:
                        tiles_count = ru32(esp.pm, inst_addr + 0x300)
                        print(f"    NavMeshTiles: {tiles_count}")
                    except Exception:
                        print(f"    NavMeshTiles: N/A")

                    # Try to read A* cache
                    try:
                        astar_cache = rp(esp.pm, inst_addr + 0x330)
                        print(f"    AStarCache: {fmt_addr(astar_cache)}")
                    except Exception:
                        pass

                    # Player pos relative to nav bounds
                    if cam:
                        lx, ly, lz = cam["loc"]
                        print(f"    Player relative to nav: "
                              f"({lx-bounds_x:.1f}, {ly-bounds_y:.1f}, {lz-bounds_z:.1f})")
    else:
        print("\n[-] NO NAVIGATION CLASSES FOUND")
        print("    This game does NOT have a NavMesh baked in the level.")
        print("    Options: generate via UE4SS/console, or use raycast-based approach")

    # ---- 4. Terrain scan test ----
    print(f"\n{'='*60}")
    print("[*] TERRAIN SCAN TEST (first 5000 objects)")
    print(f"{'='*60}")

    terrain_segs = esp.scan_terrain()
    print(f"\n[+] scan_terrain returned {len(terrain_segs)} segments")
    if terrain_segs and verbose:
        for s in terrain_segs[:10]:
            print(f"    seg: ({s[0]:.1f}, {s[1]:.1f}) -> ({s[2]:.1f}, {s[3]:.1f}) z={s[5]:.1f} type={s[4]}")

    # ---- 5. Actor class enumeration ----
    print(f"\n{'='*60}")
    print("[*] ACTOR CLASS ENUMERATION (top 30 classes by count)")
    print(f"{'='*60}")

    class_counts = {}
    total = 0
    for obj in esp.objects.iter_objects():
        try:
            cls = esp.objects.class_name(obj)
            if cls:
                class_counts[cls] = class_counts.get(cls, 0) + 1
                total += 1
        except Exception:
            continue
        if total >= 100000:
            break

    print(f"\n[+] Total objects enumerated: {total}")
    print(f"[+] Unique classes: {len(class_counts)}")
    if verbose:
        for cls, count in sorted(class_counts.items(), key=lambda x: -x[1])[:30]:
            pct = count / total * 100
            print(f"    {cls:60s} x{count:6d} ({pct:.1f}%)")

    # ---- 6. Level actors with bounds ----
    print(f"\n{'='*60}")
    print("[*] ACTORS WITH NON-ZERO BOUNDS (sample)")
    print(f"{'='*60}")

    bounds_count = 0
    bounds_samples = []
    for obj in esp.objects.iter_objects():
        if bounds_count >= 100:
            break
        try:
            bounds = esp.get_actor_bounds(obj)
            if bounds:
                origin, extent, radius = bounds
                ox, oy, oz = origin
                ex, ey, ez = extent
                if max(ex, ey, ez) >= 10:
                    cls = esp.objects.class_name(obj)
                    bounds_count += 1
                    bounds_samples.append((cls, origin, extent, radius))
        except Exception:
            continue

    print(f"\n[+] Actors with bounds >= 10: {bounds_count}")
    if verbose and bounds_samples:
        for cls, origin, extent, radius in bounds_samples[:15]:
            print(f"    {cls:50s} origin=({origin[0]:.1f},{origin[1]:.1f},{origin[2]:.1f}) "
                  f"extent=({extent[0]:.1f},{extent[1]:.1f},{extent[2]:.1f}) r={radius:.1f}")

    # ---- 7. Summary ----
    print(f"\n{'='*60}")
    print("[SUMMARY]")
    print(f"{'='*60}")
    has_nav = len(nav_classes_found) > 0
    has_terrain = len(terrain_segs) > 0
    print(f"  NavMesh:          {'YES (' + str(len(nav_classes_found)) + ' objects)' if has_nav else 'NO'}")
    print(f"  Terrain segments: {'YES (' + str(len(terrain_segs)) + ' segs)' if has_terrain else 'NO'}")
    print(f"  Actors w/ bounds: {bounds_count}")
    print(f"  Camera:           {'YES' if cam else 'NO'}")
    print(f"\n  If NavMesh=NO: the level doesn't have baked navigation data.")
    print(f"  Use --verbose for detailed output.")

if __name__ == "__main__":
    main()
