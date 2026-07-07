#!/usr/bin/env python3
"""
Core game reading engine for MECCA CHAMELEON (UE5.6) ESP.
Memory primitives, pattern scanning, FName resolution, object array,
offset resolution, and game state reading.
"""
import struct
import math
import os
import sys
import json
import time
import pymem
import ctypes
import subprocess as _subprocess

# ---------------------------------------------------------------------------
# Bootstrap offsets: stable UObject/UStruct/FField layout
# ---------------------------------------------------------------------------
OFFSETS = {
    "UObjectBase::ClassPrivate": 0x10,
    "UObjectBase::NamePrivate": 0x18,
    "UObjectBase::OuterPrivate": 0x20,
    "UStruct::SuperStruct": 0x40,
    "UStruct::ChildProperties": 0x50,
    "FField::Next": 0x18,
    "FField::NamePrivate": 0x20,
    "FProperty::Offset_Internal": 0x44,
    "UField::Next": 0x28,
    "UStruct::Children": 0x48,
    "FCameraCacheEntry::POV": 0x10,
    "FMinimalViewInfo::Location": 0x0,
    "FMinimalViewInfo::Rotation": 0x18,
    "FMinimalViewInfo::FOV": 0x30,
}

# ---------------------------------------------------------------------------
# Memory primitives — use C++ meccha-core.dll when available, fallback pymem
# ---------------------------------------------------------------------------
_USE_CORE = False
try:
    from meccha_chameleon_tools.memory_engine import (
        init as _mc_init, cleanup as _mc_cleanup, attached as _mc_attached,
        read_ptr as _mc_rp, read_u32 as _mc_ru32, read_u16 as _mc_ru16,
        read_float as _mc_rf, read_double as _mc_rd,
        write_float as _mc_wf, write_double as _mc_wd,
        read_vec3 as _mc_rv3, read_vec3_f as _mc_rv3f,
    )
    _USE_CORE = _mc_init()
except Exception:
    pass

def rp(pm, addr):
    if _USE_CORE:
        return _mc_rp(addr)
    try:
        return struct.unpack("<Q", pm.read_bytes(addr, 8))[0]
    except Exception:
        return 0

def ru32(pm, addr):
    if _USE_CORE:
        return _mc_ru32(addr)
    try:
        return struct.unpack("<I", pm.read_bytes(addr, 4))[0]
    except Exception:
        return 0

def ru16(pm, addr):
    if _USE_CORE:
        return _mc_ru16(addr)
    try:
        return struct.unpack("<H", pm.read_bytes(addr, 2))[0]
    except Exception:
        return 0

def rfloat(pm, addr):
    if _USE_CORE:
        return _mc_rf(addr)
    try:
        return struct.unpack("<f", pm.read_bytes(addr, 4))[0]
    except Exception:
        return 0.0

def rdouble(pm, addr):
    if _USE_CORE:
        return _mc_rd(addr)
    try:
        return struct.unpack("<d", pm.read_bytes(addr, 8))[0]
    except Exception:
        return 0.0

def wfloat(pm, addr, value):
    if _USE_CORE:
        return _mc_wf(addr, value)
    try:
        pm.write_bytes(addr, struct.pack("<f", value), 4)
        return True
    except Exception:
        return False

def rvec3(pm, addr):
    if _USE_CORE:
        return _mc_rv3(addr)
    try:
        return struct.unpack("<ddd", pm.read_bytes(addr, 24))
    except Exception:
        return (0.0, 0.0, 0.0)

def rvec3_f(pm, addr):
    if _USE_CORE:
        return _mc_rv3f(addr)
    try:
        return struct.unpack("<fff", pm.read_bytes(addr, 12))
    except Exception:
        return (0.0, 0.0, 0.0)

def rfquat(pm, addr):
    try:
        return struct.unpack("<dddd", pm.read_bytes(addr, 32))
    except Exception:
        return (0.0, 0.0, 0.0, 1.0)

def read_array(pm, addr):
    try:
        data = rp(pm, addr)
        count = ru32(pm, addr + 8)
        cap = ru32(pm, addr + 0x10)
        return data, count, cap
    except Exception:
        return 0, 0, 0

def read_tarray_ptr(pm, addr):
    try:
        data = rp(pm, addr)
        count = ru32(pm, addr + 8)
        return data, count
    except Exception:
        return 0, 0

def dist(a, b):
    return math.sqrt(
        (a[0] - b[0]) ** 2 +
        (a[1] - b[1]) ** 2 +
        (a[2] - b[2]) ** 2
    )

def dist_2d(a, b):
    return math.sqrt(
        (a[0] - b[0]) ** 2 +
        (a[2] - b[2]) ** 2
    )

# ---------------------------------------------------------------------------
# Pattern scanner
# ---------------------------------------------------------------------------
class PatternScanner:
    CHUNK_SIZE = 0x200000

    def __init__(self, pm, module_name):
        self.pm = pm
        self.module = pymem.process.module_from_name(pm.process_handle, module_name)
        if not self.module:
            raise RuntimeError(f"Module {module_name} not found")
        self.base = self.module.lpBaseOfDll
        self.size = self.module.SizeOfImage

    def _match_at(self, data, offset, pattern, mask):
        for j in range(len(pattern)):
            if mask[j] and data[offset + j] != pattern[j]:
                return False
        return True

    def scan_all(self, pattern, mask):
        pat_len = len(pattern)
        if pat_len == 0 or self.size == 0:
            return
        step = self.CHUNK_SIZE
        for start in range(0, self.size, step):
            end = min(start + step + pat_len, self.size)
            read_size = end - start
            try:
                data = self.pm.read_bytes(self.base + start, read_size)
            except Exception:
                continue
            scan_len = len(data) - pat_len
            for i in range(scan_len):
                if self._match_at(data, i, pattern, mask):
                    yield self.base + start + i

    def scan(self, pattern, mask):
        for addr in self.scan_all(pattern, mask):
            return addr
        return 0

# ---------------------------------------------------------------------------
# FName resolution
# ---------------------------------------------------------------------------
class FNameResolver:
    BLOCK_TABLE_OFFSETS = (
        0x8, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38,
        0x40, 0x48, 0x50, 0x58, 0x60, 0x68, 0x70,
    )

    def __init__(self, pm, fname_pool):
        self.pm = pm
        self.fname_pool = fname_pool
        self.block_table_off = 0x10
        self.header_style = "ue5"
        self._detect_layout()

    def _read_entry(self, entry_id, table_off, style):
        block_idx = entry_id >> 16
        within = (entry_id & 0xFFFF) << 1
        block_addr = rp(self.pm, self.fname_pool + table_off + block_idx * 8)
        if not block_addr:
            return None
        hdr = ru16(self.pm, block_addr + within)
        if style == "ue4":
            is_wide = hdr & 1
            length = hdr >> 1
        elif style == "custom":
            is_wide = hdr & 1
            length = (hdr >> 6) & 0x3FF
        else:
            length = hdr & 0x3FF
            is_wide = (hdr >> 10) & 1
        if length == 0 or length > 512:
            return None
        if is_wide:
            raw = self.pm.read_bytes(block_addr + within + 2, length * 2)
            return raw.decode("utf-16-le", errors="ignore")
        raw = self.pm.read_bytes(block_addr + within + 2, length)
        return raw.decode("latin-1")

    def _detect_layout(self):
        for off in self.BLOCK_TABLE_OFFSETS:
            for style in ("custom", "ue5", "ue4"):
                try:
                    if self._read_entry(0, off, style) == "None":
                        self.block_table_off = off
                        self.header_style = style
                        return
                except Exception:
                    continue

    def resolve(self, entry_id):
        try:
            name = self._read_entry(entry_id, self.block_table_off, self.header_style)
            if name is not None:
                return name
        except Exception:
            pass
        for off in self.BLOCK_TABLE_OFFSETS:
            for style in ("custom", "ue5", "ue4"):
                if off == self.block_table_off and style == self.header_style:
                    continue
                try:
                    name = self._read_entry(entry_id, off, style)
                    if name is not None:
                        self.block_table_off = off
                        self.header_style = style
                        return name
                except Exception:
                    continue
        return None

# ---------------------------------------------------------------------------
# UE Object array
# ---------------------------------------------------------------------------
class UObjectArray:
    def __init__(self, pm, guobject_array, fname_pool):
        self.pm = pm
        self.guobject_array = guobject_array
        self.fnames = FNameResolver(pm, fname_pool)
        self._meta_class_addr = None
        self._class_cache = {}

    def obj_name(self, obj):
        return self.fnames.resolve(ru32(self.pm, obj + OFFSETS["UObjectBase::NamePrivate"]))

    def obj_class(self, obj):
        return rp(self.pm, obj + OFFSETS["UObjectBase::ClassPrivate"])

    def class_name(self, obj):
        if not obj:
            return ""
        cls = self.obj_class(obj)
        return self.obj_name(cls) if cls else ""

    def iter_objects(self):
        ptr = rp(self.pm, self.guobject_array + 0x10)
        if not ptr:
            return
        for chunk_idx in range(64):
            chunk = rp(self.pm, ptr + chunk_idx * 8)
            if not chunk:
                break
            for within in range(0x10000):
                obj = rp(self.pm, chunk + within * 0x18)
                if obj:
                    yield obj

    def _meta_class(self):
        if self._meta_class_addr is None or not self._meta_class_addr:
            for obj in self.iter_objects():
                if self.obj_name(obj) == "Class":
                    self._meta_class_addr = obj
                    break
        return self._meta_class_addr

    def find_class(self, name):
        cached = self._class_cache.get(name)
        if cached:
            if self.obj_name(cached) == name:
                return cached
            del self._class_cache[name]
        meta = self._meta_class()
        if not meta:
            return 0
        for obj in self.iter_objects():
            if self.obj_class(obj) == meta and self.obj_name(obj) == name:
                self._class_cache[name] = obj
                return obj
        return 0

    def find_first_instance(self, class_name, skip_default=True):
        cls = self.find_class(class_name)
        if not cls:
            return 0
        for obj in self.iter_objects():
            if self.obj_class(obj) == cls:
                name = self.obj_name(obj)
                if skip_default and name and name.startswith("Default__"):
                    continue
                return obj
        return 0

    def find_instances(self, class_name, skip_default=True):
        cls = self.find_class(class_name)
        if not cls:
            return
        for obj in self.iter_objects():
            if self.obj_class(obj) == cls:
                name = self.obj_name(obj)
                if skip_default and name and name.startswith("Default__"):
                    continue
                yield obj

    def find_object_by_name(self, name):
        for obj in self.iter_objects():
            if self.obj_name(obj) == name:
                return obj
        return 0

    def find_objects_by_class_name(self, cls_name_part):
        for obj in self.iter_objects():
            cname = self.class_name(obj)
            if cls_name_part in cname:
                yield obj

# ---------------------------------------------------------------------------
# Offset resolver (resolves FField property chains)
# ---------------------------------------------------------------------------
class OffsetResolver:
    def __init__(self, pm, objects):
        self.pm = pm
        self.objects = objects
        self.cache = dict(OFFSETS)

    def field_name(self, field):
        return self.objects.fnames.resolve(
            ru32(self.pm, field + self.cache["FField::NamePrivate"])
        )

    def search_properties(self, cls, names):
        prop = rp(self.pm, cls + self.cache["UStruct::ChildProperties"])
        depth = 0
        while prop and depth < 512:
            name = self.field_name(prop)
            if name in names:
                return name, ru32(self.pm, prop + self.cache["FProperty::Offset_Internal"])
            prop = rp(self.pm, prop + self.cache["FField::Next"])
            depth += 1
        super_cls = rp(self.pm, cls + self.cache["UStruct::SuperStruct"])
        seen = {cls}
        while super_cls and super_cls not in seen:
            seen.add(super_cls)
            prop = rp(self.pm, super_cls + self.cache["UStruct::ChildProperties"])
            depth = 0
            while prop and depth < 512:
                name = self.field_name(prop)
                if name in names:
                    return name, ru32(self.pm, prop + self.cache["FProperty::Offset_Internal"])
                prop = rp(self.pm, prop + self.cache["FField::Next"])
                depth += 1
            super_cls = rp(self.pm, super_cls + self.cache["UStruct::SuperStruct"])
        return None, 0

    def _resolve_on_class(self, cls, prop_name):
        prop = rp(self.pm, cls + self.cache["UStruct::ChildProperties"])
        depth = 0
        while prop and depth < 512:
            name = self.field_name(prop)
            if name == prop_name:
                return ru32(self.pm, prop + self.cache["FProperty::Offset_Internal"])
            prop = rp(self.pm, prop + self.cache["FField::Next"])
            depth += 1
        return None

    def resolve(self, class_name, prop_name):
        key = f"{class_name}::{prop_name}"
        if key in self.cache:
            return self.cache[key]
        cls = self.objects.find_class(class_name)
        if not cls:
            return None
        offset = self._resolve_on_class(cls, prop_name)
        seen = {cls}
        while offset is None:
            super_cls = rp(self.pm, cls + self.cache["UStruct::SuperStruct"])
            if not super_cls or super_cls in seen:
                break
            seen.add(super_cls)
            offset = self._resolve_on_class(super_cls, prop_name)
        if offset is not None:
            self.cache[key] = offset
        return offset

    def resolve_map(self, mapping):
        out = {}
        for key, (cls, prop) in mapping.items():
            val = self.resolve(cls, prop)
            if val is None:
                raise RuntimeError(f"Could not resolve offset {key} ({cls}.{prop})")
            out[key] = val
        return out

# ---------------------------------------------------------------------------
# Game reader
# ---------------------------------------------------------------------------
class MecchaESP:
    PROCESS_NAME = "PenguinHotel-Win64-Shipping.exe"
    MODULE_NAME = "PenguinHotel-Win64-Shipping.exe"

    GUOBJECT_SIG = bytes([
        0x48, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00,
        0x48, 0x89, 0x01, 0x45, 0x8B, 0xD1,
    ])
    GUOBJECT_MASK = bytes([1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])

    FNAMEPOOL_PATTERNS = (
        (bytes([0x48, 0x8D, 0x0D, 0x00, 0x00, 0x00, 0x00,
                0xE8, 0x00, 0x00, 0x00, 0x00,
                0x4C, 0x8B, 0xC0]),
         bytes([1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1, 1])),
        (bytes([0x48, 0x8D, 0x0D, 0x00, 0x00, 0x00, 0x00,
                0xE8, 0x00, 0x00, 0x00, 0x00,
                0x48, 0x8B]),
         bytes([1, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 1])),
        (bytes([0x48, 0x8D, 0x35, 0x00, 0x00, 0x00, 0x00]),
         bytes([1, 1, 1, 0, 0, 0, 0])),
        (bytes([0x48, 0x8D, 0x3D, 0x00, 0x00, 0x00, 0x00]),
         bytes([1, 1, 1, 0, 0, 0, 0])),
    )
    FNAMEPOOL_DELTA = 0xE3B40

    OFFSET_MAP = {
        "UWorld::GameState": ("World", "GameState"),
        "UWorld::OwningGameInstance": ("World", "OwningGameInstance"),
        "UGameInstance::LocalPlayers": ("GameInstance", "LocalPlayers"),
        "UPlayer::PlayerController": ("Player", "PlayerController"),
        "UEngine::GameViewport": ("Engine", "GameViewport"),
        "UGameViewportClient::World": ("GameViewportClient", "World"),
        "AGameStateBase::PlayerArray": ("GameStateBase", "PlayerArray"),
        "APlayerState::PawnPrivate": ("PlayerState", "PawnPrivate"),
        "AController::PlayerState": ("Controller", "PlayerState"),
        "AController::ControlRotation": ("Controller", "ControlRotation"),
        "APlayerController::AcknowledgedPawn": ("PlayerController", "AcknowledgedPawn"),
        "APlayerController::PlayerCameraManager": ("PlayerController", "PlayerCameraManager"),
        "APlayerCameraManager::CameraCachePrivate": ("PlayerCameraManager", "CameraCachePrivate"),
        "AActor::RootComponent": ("Actor", "RootComponent"),
        "USceneComponent::RelativeLocation": ("SceneComponent", "RelativeLocation"),
    }
    # Dynaimc property names to try for health
    HEALTH_PROP_NAMES = ("Health", "CurrentHealth", "HP", "HealthPoints", "HitPoints")
    SHIELD_PROP_NAMES = ("Shield", "Armor", "ShieldHealth", "ExtraHealth", "ArmorHealth")

    def __init__(self):
        self.pm = pymem.Pymem(self.PROCESS_NAME)
        self.guobject_array = self._scan_guobject_array()
        if not self.guobject_array:
            raise RuntimeError("Could not find GUObjectArray via pattern scan")
        self.fname_pool = self._scan_fname_pool()
        if not self.fname_pool:
            raise RuntimeError("Could not find FNamePool")
        self.objects = UObjectArray(self.pm, self.guobject_array, self.fname_pool)
        self._globals_ok = self._verify_globals()
        self.resolver = OffsetResolver(self.pm, self.objects)
        self.offsets = self.resolver.resolve_map(self.OFFSET_MAP)
        for key in ("FCameraCacheEntry::POV", "FMinimalViewInfo::Location",
                     "FMinimalViewInfo::Rotation", "FMinimalViewInfo::FOV",
                     "UStruct::ChildProperties", "FField::Next",
                     "FProperty::Offset_Internal", "FField::NamePrivate"):
            self.offsets[key] = OFFSETS[key]
        self.gengine = self.objects.find_first_instance("GameEngine")
        if not self.gengine:
            raise RuntimeError("Could not find GEngine instance")
        self._health_offsets = None
        self._shield_offsets = None
        self._bone_cache = {}
        # Pymem 1.14 compatibility aliases
        self.read_u64 = self.pm.read_longlong
        self.read_u32 = self.pm.read_ulong
        self.read_u16 = lambda a: struct.unpack("<H", self.pm.read_bytes(a, 2))[0]
        self.read_float = lambda a: struct.unpack("<f", self.pm.read_bytes(a, 4))[0]
        self.write_u64 = lambda a, v: self.pm.write_bytes(a, struct.pack("<Q", v), 8)

    def _scan_guobject_array(self):
        scanner = PatternScanner(self.pm, self.MODULE_NAME)
        addr = scanner.scan(self.GUOBJECT_SIG, self.GUOBJECT_MASK)
        if not addr:
            return 0
        rel = struct.unpack("<i", self.pm.read_bytes(addr + 3, 4))[0]
        return addr + 7 + rel

    def _scan_fname_pool(self):
        delta_candidate = self.guobject_array - self.FNAMEPOOL_DELTA
        if self._verify_fname_pool(delta_candidate):
            return delta_candidate
        scanner = PatternScanner(self.pm, self.MODULE_NAME)
        for sig, mask in self.FNAMEPOOL_PATTERNS:
            for addr in scanner.scan_all(sig, mask):
                rel = struct.unpack("<i", self.pm.read_bytes(addr + 3, 4))[0]
                candidate = addr + 7 + rel
                if self._verify_fname_pool(candidate):
                    return candidate
        return delta_candidate

    def _verify_fname_pool(self, pool_addr):
        resolver = FNameResolver(self.pm, pool_addr)
        if resolver.resolve(0) == "None":
            return True
        for probe in (0, 1, 2, 3, 4, 5):
            name = resolver.resolve(probe)
            if name and 0 < len(name) <= 128 and name.isprintable():
                return True
        return False

    def _verify_globals(self):
        obj_array = self.guobject_array + 0x10
        num = ru32(self.pm, obj_array + 0x14)
        max_chunks = ru32(self.pm, obj_array + 0x18)
        if num == 0 or num > 10_000_000 or max_chunks == 0 or max_chunks > 64:
            return False
        return self.objects.find_class("Class") != 0

    def globals_ok(self):
        return self._globals_ok

    def _get_world(self):
        viewport = rp(self.pm, self.gengine + self.offsets["UEngine::GameViewport"])
        if not viewport:
            return 0
        return rp(self.pm, viewport + self.offsets["UGameViewportClient::World"])

    def _get_local_controller(self, world):
        if not world:
            return 0
        gi = rp(self.pm, world + self.offsets["UWorld::OwningGameInstance"])
        if not gi:
            return 0
        lp_data, lp_count, _ = read_array(self.pm, gi + self.offsets["UGameInstance::LocalPlayers"])
        if not lp_data or lp_count == 0:
            return 0
        local_player = rp(self.pm, lp_data)
        if not local_player:
            return 0
        return rp(self.pm, local_player + self.offsets["UPlayer::PlayerController"])

    def get_camera(self):
        world = self._get_world()
        if not world:
            return None
        pc = self._get_local_controller(world)
        if not pc:
            return None
        cam = rp(self.pm, pc + self.offsets["APlayerController::PlayerCameraManager"])
        if not cam:
            return None
        cc = cam + self.offsets["APlayerCameraManager::CameraCachePrivate"]
        pov = cc + self.offsets["FCameraCacheEntry::POV"]
        loc = rvec3(self.pm, pov + self.offsets["FMinimalViewInfo::Location"])
        rot = rvec3(self.pm, pov + self.offsets["FMinimalViewInfo::Rotation"])
        fov = rfloat(self.pm, pov + self.offsets["FMinimalViewInfo::FOV"])
        return {"loc": loc, "rot": rot, "fov": fov}

    def get_actor_root_pos(self, actor):
        root = rp(self.pm, actor + self.offsets["AActor::RootComponent"])
        if not root:
            return None
        return rvec3(self.pm, root + self.offsets["USceneComponent::RelativeLocation"])

    def get_actor_root_rotation(self, actor):
        """Read root component relative rotation (pitch, yaw, roll in degrees)."""
        root = rp(self.pm, actor + self.offsets["AActor::RootComponent"])
        if not root:
            return None
        rot_addr = root + 0x80
        return rvec3_f(self.pm, rot_addr)

    def _resolve_health(self, actor, ps):
        """Resolve health/shield offsets on the pawn class once, cache them."""
        if self._health_offsets is not None:
            return self._health_offsets
        cls = self.objects.obj_class(actor)
        if cls == 0 and ps:
            cls = self.objects.obj_class(ps)
        if not cls:
            self._health_offsets = ("", -1, "", -1)
            return self._health_offsets
        h_name, h_off = self.resolver.search_properties(cls, self.HEALTH_PROP_NAMES)
        s_name, s_off = self.resolver.search_properties(cls, self.SHIELD_PROP_NAMES)
        self._health_offsets = (h_name, h_off, s_name, s_off)
        return self._health_offsets

    def get_health(self, actor, player_state):
        h_name, h_off, s_name, s_off = self._resolve_health(actor, player_state)
        health = None
        if h_name and h_off >= 0 and actor:
            health = rfloat(self.pm, actor + h_off)
        shield = None
        if s_name and s_off >= 0 and actor:
            shield = rfloat(self.pm, actor + s_off)
        elif s_name and s_off >= 0 and player_state:
            shield = rfloat(self.pm, player_state + s_off)
        if health is not None:
            return max(0, health), max(0, shield or 0)
        return None, None

    def get_actor_bounds(self, actor):
        """Read FBoxSphereBounds from the root component (Origin, BoxExtent, SphereRadius)."""
        root = rp(self.pm, actor + self.offsets["AActor::RootComponent"])
        if not root:
            return None
        bounds_addr = root + 0x140
        origin = rvec3(self.pm, bounds_addr)
        extent = rvec3(self.pm, bounds_addr + 0x18)
        radius = rfloat(self.pm, bounds_addr + 0x30)
        return origin, extent, radius

    def _detect_role(self, pawn):
        """Return ('Hunter', True, False) or ('Survivor', False, True) or ('Unknown', False, False)."""
        try:
            name = self.objects.class_name(pawn) or ""
            name_lower = name.lower()
            if "hunter" in name_lower:
                return "Hunter", True, False
            if "survivor" in name_lower:
                return "Survivor", False, True
        except Exception:
            pass
        return "Unknown", False, False

    def get_invincible(self, actor):
        """Check if actor has invincibility god-mode flag enabled."""
        try:
            inv = ru32(self.pm, actor + 0x174)
            if inv == 1:
                return True
            inv = ru32(self.pm, actor + 0x1D8)
            if inv == 1:
                return True
        except Exception:
            pass
        return False

    def get_actor_class_canonical(self, actor):
        """Return readable class name for draw-all."""
        try:
            return self.objects.class_name(actor)
        except Exception:
            return ""

    def iter_actors(self, max_actors=2000, class_filter=None):
        """Iterate all non-player actors in the world (items, chunks, etc)."""
        world = self._get_world()
        if not world:
            return
        gs = rp(self.pm, world + self.offsets.get("UWorld::GameState", 0))
        if not gs:
            return
        pa_data, pa_count, _ = read_array(self.pm, gs + self.offsets["AGameStateBase::PlayerArray"])
        seen_pawns = set()
        if pa_data:
            for i in range(pa_count):
                ps = rp(self.pm, pa_data + i * 8)
                if ps:
                    pawn = rp(self.pm, ps + self.offsets["APlayerState::PawnPrivate"])
                    if pawn:
                        seen_pawns.add(pawn)
        count = 0
        for obj in self.objects.iter_objects():
            if count >= max_actors:
                break
            try:
                cls_name = self.objects.class_name(obj)
                if not cls_name:
                    continue
                if cls_name.startswith("Default__"):
                    continue
                if obj in seen_pawns:
                    continue
                if class_filter:
                    if class_filter not in cls_name:
                        continue
                else:
                    if "Collectible" not in cls_name and "Item" not in cls_name and "Chunk" not in cls_name:
                        continue
                root = rp(self.pm, obj + self.offsets.get("AActor::RootComponent", 0))
                if not root:
                    continue
                pos = rvec3(self.pm, root + self.offsets.get("USceneComponent::RelativeLocation", 0))
                if pos is None or (pos[0] == 0 and pos[1] == 0 and pos[2] == 0):
                    continue
                count += 1
                yield {"actor": obj, "pos": pos, "class_name": cls_name}
            except Exception:
                continue

    # Terrain scanning disabled (not functional)
    # def scan_terrain(self, ...):
    #     pass

    def _is_visible(self, actor):
        """Approximate visibility check: read body/sphere visibility flag if available."""
        try:
            try:
                root = rp(self.pm, actor + self.offsets["AActor::RootComponent"])
                if root:
                    vis = ru32(self.pm, root + 0x258)
                    if vis == 0:
                        return False
            except Exception:
                pass
            try:
                vis = ru32(self.pm, actor + self.offsets.get("AActor::bHidden", 0x178))
                if vis == 1:
                    return False
            except Exception:
                pass
        except Exception:
            pass
        return True

    def _find_spectate_target(self, cam_pos, players_list):
        if not cam_pos or (cam_pos[0] == 0 and cam_pos[1] == 0 and cam_pos[2] == 0):
            return None
        best_idx = None
        best_dist = 999999.0
        for i, (pawn, ps, pos) in enumerate(players_list):
            if not pos:
                continue
            d = dist_2d(cam_pos, pos)
            if d < best_dist:
                best_dist = d
                best_idx = i
        return best_idx

    # ------
    def iter_players(self, include_local=True, team_filter=False, enemy_only=False):
        world = self._get_world()
        if not world:
            return
        gs = rp(self.pm, world + self.offsets.get("UWorld::GameState", 0))
        if not gs:
            return
        pa_data, pa_count, _ = read_array(self.pm, gs + self.offsets["AGameStateBase::PlayerArray"])
        if not pa_data or pa_count == 0:
            return
        local_pawn = 0
        try:
            local_pc = self._get_local_controller(world)
            if local_pc:
                local_pawn = rp(self.pm, local_pc + self.offsets["APlayerController::AcknowledgedPawn"])
        except Exception:
            pass
        local_cam = self.get_camera()
        cam_pos = local_cam["loc"] if local_cam else None
        raw_players = []
        seen = set()
        for i in range(pa_count):
            try:
                ps = rp(self.pm, pa_data + i * 8)
                if not ps or ps in seen:
                    continue
                seen.add(ps)
                pawn = rp(self.pm, ps + self.offsets["APlayerState::PawnPrivate"])
                if not pawn:
                    continue
                pos = self.get_actor_root_pos(pawn)
                if pos is None:
                    continue
            except Exception:
                continue
            raw_players.append((pawn, ps, pos))
        ref_is_hunter, ref_is_survivor = False, False
        is_spectating = False
        try:
            if local_pawn:
                local_class = self.objects.class_name(local_pawn) or ""
                # If spectating (pawn class has 'Spectate'), find nearest real player for reference
                if "Spectate" in local_class and raw_players:
                    spec_idx = self._find_spectate_target(cam_pos, raw_players) if cam_pos else 0
                    if spec_idx is None and raw_players:
                        spec_idx = 0
                    if spec_idx is not None:
                        spec_pawn = raw_players[spec_idx][0]
                        _, ref_is_hunter, ref_is_survivor = self._detect_role(spec_pawn)
                        is_spectating = True
                else:
                    _, ref_is_hunter, ref_is_survivor = self._detect_role(local_pawn)
            elif raw_players:
                spec_idx = self._find_spectate_target(cam_pos, raw_players) if cam_pos else 0
                if spec_idx is None and raw_players:
                    spec_idx = 0
                if spec_idx is not None:
                    spec_pawn = raw_players[spec_idx][0]
                    _, ref_is_hunter, ref_is_survivor = self._detect_role(spec_pawn)
                    is_spectating = True
        except Exception:
            pass
        for i, (pawn, ps, pos) in enumerate(raw_players):
            if not include_local and pawn == local_pawn:
                continue
            role, is_hunter, is_survivor = self._detect_role(pawn)
            is_enemy = False
            if is_hunter or is_survivor:
                if ref_is_hunter and is_survivor:
                    is_enemy = True
                elif ref_is_survivor and is_hunter:
                    is_enemy = True
            if enemy_only and not is_enemy:
                continue
            if cam_pos and dist(cam_pos, pos) > 50000:
                continue
            yield {
                "is_local": pawn == local_pawn,
                "is_spectating": is_spectating,
                "pos": pos,
                "actor": pawn,
                "player_state": ps,
                "idx": i,
                "role": role,
                "is_hunter": is_hunter,
                "is_survivor": is_survivor,
                "is_enemy": is_enemy,
            }

    def get_skeleton_positions(self, actor):
        return None

    def get_skeleton_positions_by_indices(self, actor, indices):
        return None

    # ------
    # Camouflage via bundled EXE (extracted to stable %APPDATA% path)
    DLL_NAME = "runtime-bridge.dll"
    EXE_NAME = "runtime-injector.exe"
    INJECTOR_NAME = "runtime-injector.exe"
    BRIDGE_HOST = "127.0.0.1"
    BRIDGE_PORT = 50262
    CAMO_DIR = os.path.join(os.environ.get("APPDATA", "."), "MecchaCamouflage")

    @staticmethod
    def _get_dll_path():
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, MecchaESP.DLL_NAME)

    @staticmethod
    def _get_exe_path():
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, MecchaESP.EXE_NAME)

    @staticmethod
    def _get_stable_exe_path():
        return os.path.join(MecchaESP.CAMO_DIR, MecchaESP.EXE_NAME)

    @staticmethod
    def _get_injector_path():
        if getattr(sys, "frozen", False):
            base = sys._MEIPASS
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base, MecchaESP.INJECTOR_NAME)

    @staticmethod
    def _get_stable_dll_path():
        return os.path.join(MecchaESP.CAMO_DIR, MecchaESP.DLL_NAME)

    @staticmethod
    def _get_stable_injector_path():
        return os.path.join(MecchaESP.CAMO_DIR, MecchaESP.INJECTOR_NAME)

    @staticmethod
    def _bridge_request(command, payload=None, timeout=30):
        import socket as _socket
        import time as _time
        msg = json.dumps({
            "type": command,
            "request_id": f"{os.urandom(8).hex()}{int(_time.time())}",
            "timestamp_utc": int(_time.time()),
            "payload": payload or {},
        }) + "\n"
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((MecchaESP.BRIDGE_HOST, MecchaESP.BRIDGE_PORT))
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

    def is_process_alive(self):
        """Return True if the attached game process is still running."""
        try:
            pid = self.pm.process_id
            if not pid:
                return False
            handle = ctypes.windll.kernel32.OpenProcess(
                0x400, False, pid
            )
            if not handle:
                return False
            exit_code = ctypes.c_uint32(0)
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == 259  # STILL_ACTIVE
        except Exception:
            return False

    def cleanup(self):
        proc = getattr(self, "_bridge_proc", None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            self._bridge_proc = None

    def _ensure_bridge(self):
        pid = self.pm.process_id
        if not pid:
            return False
        ping = MecchaESP._bridge_request("ping")
        if ping.get("success"):
            return True
        # Ensure stable directory exists and all 3 files are extracted
        try:
            os.makedirs(MecchaESP.CAMO_DIR, exist_ok=True)
            src_exe = self._get_exe_path()
            dst_exe = self._get_stable_exe_path()
            src_dll = self._get_dll_path()
            dst_dll = self._get_stable_dll_path()
            src_inj = self._get_injector_path()
            dst_inj = self._get_stable_injector_path()
            import shutil
            if os.path.isfile(src_exe):
                shutil.copy2(src_exe, dst_exe)
            if os.path.isfile(src_dll):
                shutil.copy2(src_dll, dst_dll)
            if os.path.isfile(src_inj):
                shutil.copy2(src_inj, dst_inj)
        except Exception as e:
            print(f"[CAMO] extract failed: {e}")
        exe_path = self._get_stable_exe_path()
        if not os.path.isfile(exe_path):
            print(f"[CAMO] EXE not found at {exe_path}")
            return False
        print(f"[CAMO] launching EXE: {exe_path}")
        try:
            self._bridge_proc = _subprocess.Popen(
                [exe_path],
                cwd=os.path.dirname(exe_path),
            )
        except Exception as e:
            print(f"[CAMO] failed to launch EXE: {e}")
            return False
        # Wait for EXE to inject and settle, then trigger F10 to start bridge
        import time as _t
        _t.sleep(2.0)
        # Simulate F10 keypress multiple times to trigger the EXE's hotkey handler
        try:
            user32 = ctypes.windll.user32
            VK_F10 = 0x79
            for attempt in range(5):
                user32.keybd_event(VK_F10, 0, 0, 0)
                _t.sleep(0.05)
                user32.keybd_event(VK_F10, 0, 2, 0)
                _t.sleep(0.1)
                # Check if bridge came alive
                ping = MecchaESP._bridge_request("ping")
                if ping.get("success"):
                    print(f"[CAMO] bridge ready after F10 attempt {attempt+1}")
                    return True
            print("[CAMO] sent 5x F10 to trigger bridge")
        except Exception as e:
            print(f"[CAMO] F10 send failed (will wait for manual): {e}")
        for i in range(160):
            _t.sleep(0.25)
            if self._bridge_proc.poll() is not None:
                print(f"[CAMO] EXE exited early with code {self._bridge_proc.poll()}")
                return False
            ping = MecchaESP._bridge_request("ping")
            if ping.get("success"):
                print(f"[CAMO] bridge ready after {(i+1)*0.25 + 2:.1f}s")
                return True
            # Retry F10 every 10 seconds in case user needs to press manually
            if i > 0 and i % 40 == 39:
                print(f"[CAMO] retrying F10... ({i//40 + 1})")
                try:
                    user32.keybd_event(VK_F10, 0, 0, 0)
                    _t.sleep(0.05)
                    user32.keybd_event(VK_F10, 0, 2, 0)
                except Exception:
                    pass
            if i % 16 == 15:
                print(f"[CAMO] waiting for bridge... ({(i+1)//16}/10)")
        print("[CAMO] bridge never came alive")
        return False

    def teleport(self, x, y, z):
        """Teleport local player to world coordinates via bridge."""
        print(f"[CAMO] teleporting to ({x:.1f}, {y:.1f}, {z:.1f})...")
        resp = MecchaESP._bridge_request("teleport", {"x": x, "y": y, "z": z}, timeout=30)
        ok = resp.get("success", False)
        print(f"[CAMO] teleport {'ok' if ok else 'failed'}: {resp}")
        return ok

    def set_fov(self, fov):
        """Override camera FOV via bridge."""
        print(f"[CAMO] setting FOV to {fov}...")
        resp = MecchaESP._bridge_request("set_fov", {"fov": fov}, timeout=30)
        ok = resp.get("success", False)
        print(f"[CAMO] set_fov {'ok' if ok else 'failed'}: {resp}")
        return ok

    def kill(self, enemies=False):
        """Kill local player (or enemies) via bridge."""
        target = "enemies" if enemies else "self"
        print(f"[CAMO] killing {target}...")
        resp = MecchaESP._bridge_request("kill", {"enemies": enemies}, timeout=30)
        ok = resp.get("success", False)
        print(f"[CAMO] kill {'ok' if ok else 'failed'}: {resp}")
        return ok

    def teleport_collectible(self, key="Y"):
        """Teleport nearest collectible/item to local player via bridge."""
        print(f"[CAMO] teleporting collectible (key={key})...")
        resp = MecchaESP._bridge_request("teleport_collectible", {"key": key}, timeout=30)
        ok = resp.get("success", False)
        print(f"[CAMO] teleport_collectible {'ok' if ok else 'failed'}: {resp}")
        return ok

    def player_mod(self, speed_mult=1.0, jump_mult=1.0):
        """Set player speed/jump multipliers via bridge."""
        print(f"[CAMO] player_mod speed={speed_mult}x jump={jump_mult}x...")
        resp = MecchaESP._bridge_request("player_mod", {"speed_mult": speed_mult, "jump_mult": jump_mult}, timeout=30)
        ok = resp.get("success", False)
        print(f"[CAMO] player_mod {'ok' if ok else 'failed'}: {resp}")
        return ok
