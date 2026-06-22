#!/usr/bin/env python3
"""
FNamePool layout diagnostic for MECCHA CHAMELEON.
Run while the game is open and paste the output.
"""
import struct
import pymem

PROCESS_NAME = "PenguinHotel-Win64-Shipping.exe"
MODULE_NAME = "PenguinHotel-Win64-Shipping.exe"
FNAMEPOOL_DELTA = 0xE3B40

GUOBJECT_SIG = bytes([
    0x48, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00,
    0x48, 0x89, 0x01, 0x45, 0x8B, 0xD1
])
GUOBJECT_MASK = bytes([1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])


def rp(pm, addr):
    try:
        return struct.unpack("<Q", pm.read_bytes(addr, 8))[0]
    except Exception:
        return 0


def ru16(pm, addr):
    try:
        return struct.unpack("<H", pm.read_bytes(addr, 2))[0]
    except Exception:
        return 0


def ru32(pm, addr):
    try:
        return struct.unpack("<I", pm.read_bytes(addr, 4))[0]
    except Exception:
        return 0


def scan_guobject_array(pm):
    mod = pymem.process.module_from_name(pm.process_handle, MODULE_NAME)
    base = mod.lpBaseOfDll
    size = mod.SizeOfImage
    data = pm.read_bytes(base, size)
    pat_len = len(GUOBJECT_SIG)
    for i in range(size - pat_len):
        matched = True
        for j in range(pat_len):
            if GUOBJECT_MASK[j] and data[i + j] != GUOBJECT_SIG[j]:
                matched = False
                break
        if matched:
            addr = base + i
            rel = struct.unpack("<i", pm.read_bytes(addr + 3, 4))[0]
            return addr + 7 + rel
    return 0


def read_name_entry(pm, entry_addr, style):
    hdr = ru16(pm, entry_addr)
    if style == "ue4":
        is_wide = hdr & 1
        length = hdr >> 1
    else:
        length = hdr & 0x3FF
        is_wide = (hdr >> 10) & 1
    if length == 0 or length > 512:
        return None
    try:
        if is_wide:
            raw = pm.read_bytes(entry_addr + 2, length * 2)
            return raw.decode("utf-16-le", errors="ignore")
        else:
            raw = pm.read_bytes(entry_addr + 2, length)
            return raw.decode("latin-1")
    except Exception:
        return None


def resolve_at(pm, fname_pool, entry_id, table_off, style):
    block_idx = entry_id >> 16
    within = (entry_id & 0xFFFF) << 1
    block_addr = rp(pm, fname_pool + table_off + block_idx * 8)
    if not block_addr:
        return None
    return read_name_entry(pm, block_addr + within, style)


def main():
    pm = pymem.Pymem(PROCESS_NAME)
    guobj = scan_guobject_array(pm)
    fname_pool = guobj - FNAMEPOOL_DELTA
    print(f"GUObjectArray = 0x{guobj:X}")
    print(f"FNamePool     = 0x{fname_pool:X}")
    print(f"delta         = 0x{guobj - fname_pool:X}")

    print("\n--- FNamePool first 0x80 bytes ---")
    raw = pm.read_bytes(fname_pool, 0x80)
    for i in range(0, 0x80, 0x10):
        chunk = raw[i:i+0x10]
        print(f"  +{i:02x}: {chunk.hex()}")

    print("\n--- Probing block-table offsets / header styles for entry 0 ('None') ---")
    for off in range(0, 0x80, 0x8):
        val = rp(pm, fname_pool + off)
        if not val:
            continue
        # Interpret val as pointer to block table array
        first_block = rp(pm, val)
        if first_block and (first_block & 0xFFFF000000000000) == 0 and first_block > 0x10000:
            for style in ("ue5", "ue4"):
                name = read_name_entry(pm, first_block, style)
                if name:
                    print(f"  off=+{off:02x} indirect  style={style} -> entry0='{name}'")
        # Interpret val as first block directly
        for style in ("ue5", "ue4"):
            name = read_name_entry(pm, val, style)
            if name:
                print(f"  off=+{off:02x} direct    style={style} -> entry0='{name}'")

    print("\n--- Scanning FNamePool memory for 'None' string ---")
    # Read a large region around the pool and look for the ASCII string "None"
    try:
        region = pm.read_bytes(fname_pool, 0x200000)
        idx = region.find(b"None\x00")
        if idx >= 0:
            print(f"  found 'None' at FNamePool+0x{idx:X}")
        else:
            print("  'None' not found in first 2 MiB")
    except Exception as e:
        print(f"  read error: {e}")

    pm.close_process()


if __name__ == "__main__":
    main()
