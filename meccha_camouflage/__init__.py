#!/usr/bin/env python3
"""
Meccha Chameleon Tools — ESP + Camouflage for MECCHA CHAMELEON (UE5).

Based on ecpp/meccha-esp — external box ESP, aimbot, and direct-memory camouflage.

Usage:
    pip install -r requirements.txt
    python -m meccha_camouflage

Controls
────────
  Insert / F1   — Toggle menu
  F10           — Sample screen centre (GDI) + write colour to player material
"""

from __future__ import annotations

import math
import struct
import sys
import time
import ctypes
import json
import os
from dataclasses import dataclass
from typing import Tuple

try:
    import pymem
except ImportError:
    print("Missing pymem.  Install: pip install -r requirements.txt")
    sys.exit(1)

from PyQt5.QtWidgets import (
    QApplication, QWidget, QCheckBox, QLabel,
    QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QColorDialog,
    QSpinBox, QDoubleSpinBox, QTabWidget, QGroupBox, QGridLayout,
    QComboBox,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QBrush

# ---------------------------------------------------------------------------
# Bootstrap offsets
# ---------------------------------------------------------------------------
try:
    import win32gui
except ImportError:
    win32gui = None
OFFSETS = {
    "UObjectBase::ClassPrivate": 0x10,
    "UObjectBase::NamePrivate": 0x18,
    "UObjectBase::OuterPrivate": 0x20,
    "UStruct::SuperStruct": 0x40,
    "UStruct::ChildProperties": 0x50,
    "FField::Next": 0x18,
    "FField::NamePrivate": 0x20,
    "FProperty::Offset_Internal": 0x44,
    "FCameraCacheEntry::POV": 0x10,
    "FMinimalViewInfo::Location": 0x0,
    "FMinimalViewInfo::Rotation": 0x18,
    "FMinimalViewInfo::FOV": 0x30,
}

PROCESS_NAME = "PenguinHotel-Win64-Shipping.exe"
MODULE_NAME = "PenguinHotel-Win64-Shipping.exe"

GUOBJECT_SIG = bytes([
    0x48, 0x8D, 0x05, 0x00, 0x00, 0x00, 0x00,
    0x48, 0x89, 0x01, 0x45, 0x8B, 0xD1,
])
GUOBJECT_MASK = bytes([1, 1, 1, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1])
FNAMEPOOL_DELTA = 0xE3B40

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

# ---------------------------------------------------------------------------
# Memory primitives
# ---------------------------------------------------------------------------
def rp(pm, addr):
    try: return struct.unpack("<Q", pm.read_bytes(addr, 8))[0]
    except: return 0

def ru32(pm, addr):
    try: return struct.unpack("<I", pm.read_bytes(addr, 4))[0]
    except: return 0

def ru16(pm, addr):
    try: return struct.unpack("<H", pm.read_bytes(addr, 2))[0]
    except: return 0

def rfloat(pm, addr):
    try: return struct.unpack("<f", pm.read_bytes(addr, 4))[0]
    except: return 0.0

def wfloat(pm, addr, val):
    try:
        pm.write_bytes(addr, struct.pack("<f", val), 4)
        return True
    except: return False

def rvec3(pm, addr):
    try: return struct.unpack("<ddd", pm.read_bytes(addr, 24))
    except: return (0.0, 0.0, 0.0)

def read_array(pm, addr):
    try:
        return rp(pm, addr), ru32(pm, addr + 8), ru32(pm, addr + 0x10)
    except: return 0, 0, 0

def dist(a, b):
    return math.sqrt((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2)

# ---------------------------------------------------------------------------
# PatternScanner
# ---------------------------------------------------------------------------
class PatternScanner:
    CHUNK_SIZE = 0x200000
    def __init__(self, pm, module_name):
        self.pm = pm
        mod = pymem.process.module_from_name(pm.process_handle, module_name)
        if not mod: raise RuntimeError(f"Module {module_name} not found")
        self.base = mod.lpBaseOfDll
        self.size = mod.SizeOfImage

    def _match_at(self, data, offset, pattern, mask):
        for j in range(len(pattern)):
            if mask[j] and data[offset + j] != pattern[j]:
                return False
        return True

    def scan_all(self, pattern, mask):
        plen = len(pattern)
        if plen == 0 or self.size == 0:
            return
        step = self.CHUNK_SIZE
        for start in range(0, self.size, step):
            end = min(start + step + plen, self.size)
            read_size = end - start
            try:
                data = self.pm.read_bytes(self.base + start, read_size)
            except Exception:
                continue
            scan_len = len(data) - plen
            for i in range(scan_len):
                if self._match_at(data, i, pattern, mask):
                    yield self.base + start + i

    def scan(self, pattern, mask):
        for addr in self.scan_all(pattern, mask):
            return addr
        return 0

# ---------------------------------------------------------------------------
# FNameResolver
# ---------------------------------------------------------------------------
class FNameResolver:
    BLOCK_OFFSETS = (0x8, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38,
                     0x40, 0x48, 0x50, 0x58, 0x60, 0x68, 0x70)

    def __init__(self, pm, pool):
        self.pm = pm
        self.pool = pool
        self.table_off = 0x10
        self.style = "ue5"
        self._detect()

    def _entry(self, eid, off, style):
        bi = eid >> 16
        wi = (eid & 0xFFFF) << 1
        ba = rp(self.pm, self.pool + off + bi * 8)
        if not ba: return None
        h = ru16(self.pm, ba + wi)
        if style == "ue4":
            w = h & 1; ln = h >> 1
        elif style == "custom":
            w = h & 1; ln = (h >> 6) & 0x3FF
        else:
            ln = h & 0x3FF; w = (h >> 10) & 1
        if not (1 <= ln <= 512): return None
        r = self.pm.read_bytes(ba + wi + 2, ln * (2 if w else 1))
        return r.decode("utf-16-le" if w else "latin-1", errors="replace")

    def _detect(self):
        for off in self.BLOCK_OFFSETS:
            for s in ("custom", "ue5", "ue4"):
                try:
                    if self._entry(0, off, s) == "None":
                        self.table_off = off; self.style = s; return
                except: pass

    def resolve(self, eid):
        try:
            n = self._entry(eid, self.table_off, self.style)
            if n: return n
        except: pass
        for off in self.BLOCK_OFFSETS:
            for s in ("custom", "ue5", "ue4"):
                if off == self.table_off and s == self.style: continue
                try:
                    n = self._entry(eid, off, s)
                    if n: self.table_off = off; self.style = s; return n
                except: pass
        return None

# ---------------------------------------------------------------------------
# UObjectArray
# ---------------------------------------------------------------------------
class UObjectArray:
    def __init__(self, pm, guobj, fname_pool):
        self.pm = pm; self.guobj = guobj
        self.fnames = FNameResolver(pm, fname_pool)
        self._meta = None; self._cache = {}

    def obj_name(self, obj):
        idx = ru32(self.pm, obj + OFFSETS["UObjectBase::NamePrivate"])
        n = self.fnames.resolve(idx)
        if n:
            if "/" in n: n = n.rsplit("/", 1)[-1]
            if "." in n: n = n.rsplit(".", 1)[-1]
            if n.startswith("Default__"): n = n[9:]
        return n

    def obj_class(self, obj):
        return rp(self.pm, obj + OFFSETS["UObjectBase::ClassPrivate"])

    def iter_objects(self):
        ptr = rp(self.pm, self.guobj + 0x10)
        if not ptr: return
        for ci in range(64):
            c = rp(self.pm, ptr + ci * 8)
            if not c: break
            for wi in range(65536):
                o = rp(self.pm, c + wi * 0x18)
                if o: yield o

    def find_class(self, name):
        cached = self._cache.get(name)
        if cached and self.obj_name(cached) == name: return cached
        if cached: del self._cache[name]
        meta = self._meta_class()
        if not meta: return 0
        for o in self.iter_objects():
            if self.obj_class(o) == meta and self.obj_name(o) == name:
                self._cache[name] = o; return o
        return 0

    def find_first_instance(self, cls_name):
        cls = self.find_class(cls_name)
        if not cls: return 0
        for o in self.iter_objects():
            if self.obj_class(o) == cls:
                n = self.obj_name(o)
                if n and n.startswith("Default__"): continue
                return o
        return 0

    def _meta_class(self):
        if self._meta is None or not self._meta:
            for o in self.iter_objects():
                if self.obj_name(o) == "Class":
                    self._meta = o; break
        return self._meta or 0

# ---------------------------------------------------------------------------
# OffsetResolver
# ---------------------------------------------------------------------------
class OffsetResolver:
    def __init__(self, pm, objects):
        self.pm = pm; self.objects = objects
        self.cache = dict(OFFSETS)

    def resolve_map(self, mapping):
        resolved = {}
        for key, (cls_name, prop_name) in mapping.items():
            val = self.resolve(cls_name, prop_name)
            if val is None:
                raise RuntimeError(f"Could not resolve offset {key} ({cls_name}.{prop_name})")
            resolved[key] = val
        return resolved

    def resolve(self, cls_name, prop_name):
        key = f"{cls_name}::{prop_name}"
        if key in self.cache: return self.cache[key]
        cls = self.objects.find_class(cls_name)
        if not cls: return None
        prop = rp(self.pm, cls + self.cache["UStruct::ChildProperties"])
        depth = 0
        while prop and depth < 512:
            ni = ru32(self.pm, prop + self.cache["FField::NamePrivate"])
            fn = self.objects.fnames.resolve(ni)
            if fn == prop_name:
                off = ru32(self.pm, prop + self.cache["FProperty::Offset_Internal"])
                self.cache[key] = off; return off
            prop = rp(self.pm, prop + self.cache["FField::Next"])
            depth += 1
        seen = {cls}
        while cls:
            sup = rp(self.pm, cls + self.cache["UStruct::SuperStruct"])
            if not sup or sup in seen: break
            seen.add(sup); cls = sup
            prop = rp(self.pm, cls + self.cache["UStruct::ChildProperties"])
            depth = 0
            while prop and depth < 512:
                ni = ru32(self.pm, prop + self.cache["FField::NamePrivate"])
                fn = self.objects.fnames.resolve(ni)
                if fn == prop_name:
                    off = ru32(self.pm, prop + self.cache["FProperty::Offset_Internal"])
                    self.cache[key] = off; return off
                prop = rp(self.pm, prop + self.cache["FField::Next"])
                depth += 1
        return None

# ---------------------------------------------------------------------------
# GameReader
# ---------------------------------------------------------------------------
class GameReader:
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

    def __init__(self):
        self.pm = pymem.Pymem(PROCESS_NAME)
        self.guobj = self._scan_guobj()
        if not self.guobj: raise RuntimeError("GUObjectArray not found")
        self.fname_pool = self._scan_fname_pool()
        if not self.fname_pool: raise RuntimeError("FNamePool not found")
        self.objects = UObjectArray(self.pm, self.guobj, self.fname_pool)
        self._globals_ok = self._verify_globals()
        self.resolver = OffsetResolver(self.pm, self.objects)
        self.offsets = self.resolver.resolve_map(self.OFFSET_MAP)
        for k in ("FCameraCacheEntry::POV", "FMinimalViewInfo::Location",
                  "FMinimalViewInfo::Rotation", "FMinimalViewInfo::FOV"):
            self.offsets[k] = OFFSETS[k]
        self.gengine = self.objects.find_first_instance("GameEngine")
        if not self.gengine: raise RuntimeError("GEngine not found")

    def _scan_guobj(self):
        s = PatternScanner(self.pm, MODULE_NAME)
        a = s.scan(GUOBJECT_SIG, GUOBJECT_MASK)
        if not a: return 0
        rel = struct.unpack("<i", self.pm.read_bytes(a + 3, 4))[0]
        return a + 7 + rel

    def _scan_fname_pool(self):
        delta_candidate = self.guobj - FNAMEPOOL_DELTA
        if self._verify_fname_pool(delta_candidate):
            return delta_candidate
        scanner = PatternScanner(self.pm, MODULE_NAME)
        for sig, mask in FNAMEPOOL_PATTERNS:
            for addr in scanner.scan_all(sig, mask):
                rel = struct.unpack("<i", self.pm.read_bytes(addr + 3, 4))[0]
                candidate = addr + 7 + rel
                if self._verify_fname_pool(candidate):
                    return candidate
        return delta_candidate

    def _verify_fname_pool(self, pool_addr):
        r = FNameResolver(self.pm, pool_addr)
        if r.resolve(0) == "None":
            return True
        for probe in (0, 1, 2, 3, 4, 5):
            name = r.resolve(probe)
            if name and 0 < len(name) <= 128 and name.isprintable():
                return True
        return False

    def _verify_globals(self):
        obj_array = self.guobj + 0x10
        num = ru32(self.pm, obj_array + 0x14)
        max_chunks = ru32(self.pm, obj_array + 0x18)
        if num == 0 or num > 10_000_000 or max_chunks == 0 or max_chunks > 64:
            return False
        return self.objects.find_class("Class") != 0

    def _get_world(self):
        vp = rp(self.pm, self.gengine + self.offsets["UEngine::GameViewport"])
        if not vp: return 0
        return rp(self.pm, vp + self.offsets["UGameViewportClient::World"])

    def _get_local_controller(self, world):
        if not world: return 0
        gi = rp(self.pm, world + self.offsets["UWorld::OwningGameInstance"])
        if not gi: return 0
        d, c, _ = read_array(self.pm, gi + self.offsets["UGameInstance::LocalPlayers"])
        if not d or not c: return 0
        lp = rp(self.pm, d)
        if not lp: return 0
        return rp(self.pm, lp + self.offsets["UPlayer::PlayerController"])

    def get_camera(self):
        w = self._get_world()
        pc = self._get_local_controller(w)
        if not pc: return None
        cam = rp(self.pm, pc + self.offsets["APlayerController::PlayerCameraManager"])
        if not cam: return None
        cc = cam + self.offsets["APlayerCameraManager::CameraCachePrivate"]
        pov = cc + self.offsets["FCameraCacheEntry::POV"]
        loc = rvec3(self.pm, pov + self.offsets["FMinimalViewInfo::Location"])
        rot = rvec3(self.pm, pov + self.offsets["FMinimalViewInfo::Rotation"])
        fov = rfloat(self.pm, pov + self.offsets["FMinimalViewInfo::FOV"])
        return {"loc": loc, "rot": rot, "fov": fov}

    def _class_name(self, obj):
        if not obj: return ""
        cls = self.obj_class(obj) if hasattr(self, 'obj_class') else rp(self.pm, obj + OFFSETS["UObjectBase::ClassPrivate"])
        return self.objects.obj_name(cls) if cls else ""

    def iter_players(self, include_local=False, team_filter=False):
        w = self._get_world()
        if not w: return
        gs = rp(self.pm, w + self.offsets["UWorld::GameState"])
        pc = self._get_local_controller(w)
        lp = rp(self.pm, pc + self.offsets["APlayerController::AcknowledgedPawn"]) if pc else 0
        lps = rp(self.pm, pc + self.offsets["AController::PlayerState"]) if pc else 0
        lpc = self._class_name(lp)

        if include_local and lp:
            rt = rp(self.pm, lp + self.offsets["AActor::RootComponent"])
            if rt:
                yield True, rvec3(self.pm, rt + self.offsets["USceneComponent::RelativeLocation"]), 0, lp

        yielded = 0
        if gs:
            d, c, _ = read_array(self.pm, gs + self.offsets["AGameStateBase::PlayerArray"])
            if d and c:
                for i in range(c):
                    ps = rp(self.pm, d + i * 8)
                    if not ps or ps == lps: continue
                    pn = rp(self.pm, ps + self.offsets["APlayerState::PawnPrivate"])
                    if not pn or pn == lp: continue
                    pnc = self._class_name(pn)
                    if not pnc: continue
                    if team_filter and lpc and pnc == lpc: continue
                    if "Spectate" in pnc: continue
                    rt = rp(self.pm, pn + self.offsets["AActor::RootComponent"])
                    if not rt: continue
                    yielded += 1
                    yield False, rvec3(self.pm, rt + self.offsets["USceneComponent::RelativeLocation"]), i, pn

        if yielded == 0:
            pl_off = self.resolver.resolve("World", "PersistentLevel") or 0x30
            lv = rp(self.pm, w + pl_off)
            if lv:
                ac_off = self.resolver.resolve("Level", "Actors") or 0x98
                d, c, _ = read_array(self.pm, lv + ac_off)
                if d and c:
                    for i in range(c):
                        a = rp(self.pm, d + i * 8)
                        if not a or a == lp: continue
                        cn = self._class_name(a)
                        if not cn or "Character" not in cn: continue
                        rt = rp(self.pm, a + self.offsets["AActor::RootComponent"])
                        if not rt: continue
                        yield False, rvec3(self.pm, rt + self.offsets["USceneComponent::RelativeLocation"]), i, a

    def find_player_pawn(self):
        w = self._get_world()
        pc = self._get_local_controller(w)
        if not pc: return 0
        return rp(self.pm, pc + self.offsets["APlayerController::AcknowledgedPawn"])

    def find_player_class(self):
        for name in ("ChameleonCharacter", "BP_Chameleon", "ChameleonPlayer",
                      "BP_ChameleonCharacter", "Character"):
            if self.objects.find_class(name): return name
        return None

    def _lazy_offset(self, cls, prop):
        return self.resolver.resolve(cls, prop)

    def read_health(self, pawn):
        off = self._lazy_offset(self.find_player_class() or "Character", "Health")
        if off is None:
            off = self._lazy_offset("BP_ChameleonCharacter_C", "Health")
        if off is None:
            off = self._lazy_offset("ChameleonCharacter_C", "Health")
        if off: return rfloat(self.pm, pawn + off)
        return None

    def read_shield(self, pawn):
        for cls in ("BP_ChameleonCharacter", "ChameleonCharacter", "BP_ChameleonCharacter_C", "Character"):
            off = self._lazy_offset(cls, "Shield")
            if off is not None: return rfloat(self.pm, pawn + off)
        return None

    def find_skel_mesh(self, pawn):
        return CamoApplier._find_mesh_static(self.pm, pawn, self.offsets, self.resolver)

    def read_weapon_name(self, pawn):
        mesh = self.find_skel_mesh(pawn)
        if not mesh: return None
        for cls in ("SkeletalMeshComponent", "SkinnedMeshComponent", "MeshComponent"):
            off = self._lazy_offset(cls, "WeaponName")
            if off:
                try:
                    data, cnt, _ = read_array(self.pm, mesh + off)
                    if data and cnt:
                        raw = self.pm.read_bytes(data, cnt * 2)
                        return raw.decode("utf-16-le", errors="ignore").rstrip("\x00")
                except: pass
        return None

# ---------------------------------------------------------------------------
# Lightweight screen pixel capture via GDI (no DXGI, avoids GPU stall)
# ---------------------------------------------------------------------------
def sample_screen_center(hwnd):
    if not hwnd or win32gui is None:
        return None
    try:
        dc = win32gui.GetWindowDC(hwnd)
        w, h = win32gui.GetClientRect(hwnd)[2], win32gui.GetClientRect(hwnd)[3]
        pixel = win32gui.GetPixel(dc, w // 2, h // 2)
        win32gui.ReleaseDC(hwnd, dc)
        return ((pixel & 0xFF) / 255.0, ((pixel >> 8) & 0xFF) / 255.0, ((pixel >> 16) & 0xFF) / 255.0)
    except Exception:
        return None

# ---------------------------------------------------------------------------
# Camouflage applier — writes colour directly into material memory via pymem
# ---------------------------------------------------------------------------
class CamoApplier:
    def __init__(self, reader: GameReader):
        self.reader = reader
        self._vp_off = None
        self._resolve()

    def _resolve(self):
        r = self.reader.resolver
        self._vp_off = r.resolve("MaterialInterface", "VectorParameterValues")
        if not self._vp_off:
            self._vp_off = r.resolve("MaterialInstance", "VectorParameterValues")

    def apply(self, r, g, b, a=1.0):
        if self._vp_off is None:
            return False
        pm = self.reader.pm
        pawn = self.reader.find_player_pawn()
        if not pawn:
            return False
        mesh = self._find_mesh(pawn)
        if not mesh:
            return False
        mat_off = self.reader.resolver.resolve("MeshComponent", "Materials")
        if mat_off is None:
            mat_off = self.reader.resolver.resolve("SkinnedMeshComponent", "Materials")
        if mat_off is None:
            return False
        data_ptr = rp(pm, mesh + mat_off)
        count = ru32(pm, mesh + mat_off + 8)
        if not data_ptr or count == 0:
            return False
        ok = False
        for i in range(min(count, 8)):
            mat = rp(pm, data_ptr + i * 8)
            if mat:
                try:
                    if self._write_mat(pm, mat, r, g, b, a):
                        ok = True
                except Exception:
                    continue
        return ok

    @staticmethod
    def _find_mesh_static(pm, pawn, offsets, resolver=None):
        root = rp(pm, pawn + offsets.get("AActor::RootComponent", 0))
        if not root:
            return 0
        off = resolver.resolve("SceneComponent", "AttachChildren") if resolver else offsets.get("AActor::RootComponent", 0)
        if not off:
            return 0
        data, cnt, _ = read_array(pm, root + off)
        if data and cnt:
            for i in range(cnt):
                comp = rp(pm, data + i * 8)
                if comp:
                    cls_name = resolver and resolver.objects.obj_name(resolver.objects.obj_class(comp))
                    if cls_name and ("Skeletal" in cls_name or "Mesh" in cls_name):
                        return comp
        return 0

    def _find_mesh(self, pawn):
        return self._find_mesh_static(self.reader.pm, pawn, self.reader.offsets, self.reader.resolver)

    def _write_mat(self, pm, mat, r, g, b, a):
        off = self._vp_off
        data, cnt, _ = read_array(pm, mat + off)
        if not data or cnt == 0:
            return False
        entry_base = data
        for color_start in (16, 20, 24, 28, 32):
            try:
                raw = pm.read_bytes(entry_base + color_start, 16)
                floats = struct.unpack("<ffff", raw)
                if all(0.0 <= v <= 1.0 for v in floats):
                    pm.write_bytes(entry_base + color_start, struct.pack("<ffff", r, g, b, a), 16)
                    return True
                if all(0 <= v <= 255 for v in floats):
                    pm.write_bytes(entry_base + color_start, struct.pack("<ffff", r*255, g*255, b*255, a*255), 16)
                    return True
            except Exception:
                continue
        return False

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
@dataclass
class Config:
    # ESP
    esp_enabled: bool = True
    esp_style: str = "dot"          # "dot" | "box" | "both"
    corner_box: bool = False
    skeleton_esp: bool = False
    show_local: bool = True
    show_names: bool = True
    show_distance: bool = True
    show_health: bool = False
    show_shield: bool = False
    show_weapon: bool = False
    snap_lines: bool = True
    team_filter: bool = True
    max_distance: int = 0           # 0 = unlimited
    enemy_color: Tuple[int, int, int] = (255, 0, 0)
    local_color: Tuple[int, int, int] = (0, 255, 0)
    box_height_world: float = 100.0
    dot_radius: int = 8
    box_y_offset: int = 0

    # Camouflage
    camo_enabled: bool = True
    camo_default_r: float = 0.3
    camo_default_g: float = 0.7
    camo_default_b: float = 0.3
    camo_key: int = 0x79  # F10

    # Aimbot
    aimbot_enabled: bool = False
    aimbot_key: str = "MB5"
    aimbot_fov: int = 150
    aimbot_smooth: float = 0.30
    aimbot_target_offset: float = 90.0
    aimbot_show_fov: bool = True

    # State (not saved)
    camo_last_color: Tuple[float, float, float] = (0.3, 0.7, 0.3)
    camo_last_time: float = 0.0
    camo_status: str = "Ready"

    _SAVE_KEYS = {
        "esp_enabled", "esp_style", "corner_box", "skeleton_esp",
        "show_local", "show_names", "show_distance", "show_health",
        "show_shield", "show_weapon", "snap_lines", "team_filter",
        "max_distance", "enemy_color", "local_color", "box_height_world",
        "dot_radius", "box_y_offset",
        "camo_enabled", "camo_default_r", "camo_default_g", "camo_default_b",
        "camo_key", "aimbot_enabled", "aimbot_key", "aimbot_fov",
        "aimbot_smooth", "aimbot_target_offset", "aimbot_show_fov",
    }

    @property
    def _config_path(self) -> str:
        d = os.path.join(os.environ.get("APPDATA", "."), "MecchaCamouflage")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, "config.json")

    def save(self):
        data = {}
        for k in self._SAVE_KEYS:
            v = getattr(self, k)
            if isinstance(v, tuple):
                data[k] = list(v)
            else:
                data[k] = v
        with open(self._config_path, "w") as f:
            json.dump(data, f, indent=2)

    def load(self):
        try:
            with open(self._config_path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return
        for k, v in data.items():
            if k in self._SAVE_KEYS:
                if k in ("enemy_color", "local_color") and isinstance(v, list):
                    v = tuple(v)
                setattr(self, k, v)

# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------
VK_NAMES = {
    0x01: "LMB", 0x02: "RMB", 0x04: "MMB", 0x05: "MB4", 0x06: "MB5",
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift",
    0x11: "Ctrl", 0x12: "Alt", 0x13: "Pause", 0x1B: "Esc", 0x20: "Space",
    0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2D: "Insert", 0x2E: "Delete",
    0x30: "0", 0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4",
    0x35: "5", 0x36: "6", 0x37: "7", 0x38: "8", 0x39: "9",
    0x41: "A", 0x42: "B", 0x43: "C", 0x44: "D", 0x45: "E", 0x46: "F",
    0x47: "G", 0x48: "H", 0x49: "I", 0x4A: "J", 0x4B: "K", 0x4C: "L",
    0x4D: "M", 0x4E: "N", 0x4F: "O", 0x50: "P", 0x51: "Q", 0x52: "R",
    0x53: "S", 0x54: "T", 0x55: "U", 0x56: "V", 0x57: "W", 0x58: "X",
    0x59: "Y", 0x5A: "Z",
    0x60: "Num0", 0x61: "Num1", 0x62: "Num2", 0x63: "Num3", 0x64: "Num4",
    0x65: "Num5", 0x66: "Num6", 0x67: "Num7", 0x68: "Num8", 0x69: "Num9",
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5",
    0x75: "F6", 0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10",
    0x7A: "F11", 0x7B: "F12",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}

class Menu(QWidget):
    def __init__(self, config: Config):
        super().__init__()
        self.config = config
        self.setWindowTitle("Meccha Chameleon Tools")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None
        self._build_ui()
        self.setFixedSize(360, 680)

    def _make_group(self, title, color):
        g = QGroupBox(title)
        g.setStyleSheet(f"""
            QGroupBox {{
                color: {color};
                font-size: 13px; font-weight: bold;
                border: 1px solid #555; border-radius: 6px;
                margin-top: 14px; padding-top: 10px;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                left: 10px; padding: 0 6px;
            }}
        """)
        return g

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        container = QFrame(self)
        container.setStyleSheet("""
            QFrame#main { background: rgba(16,16,16,230); border: 1px solid #444; border-radius: 8px; }
            QLabel { color: #ddd; font-size: 12px; }
            QCheckBox { color: #ddd; font-size: 12px; spacing: 8px; }
            QCheckBox::indicator { width: 16px; height: 16px; }
            QComboBox { background: #2a2a2a; color: #ddd; border: 1px solid #555; padding: 3px 6px; border-radius: 3px; }
            QSpinBox, QDoubleSpinBox { background: #2a2a2a; color: #ddd; border: 1px solid #555; padding: 2px 4px; border-radius: 3px; }
            QPushButton { background: #333; color: #eee; border: 1px solid #555; padding: 5px 10px; border-radius: 4px; }
            QPushButton:hover { background: #444; }
        """)
        container.setObjectName("main")

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Meccha Chameleon Tools")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #0f0;")
        header.addWidget(title)
        header.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            "QPushButton { background: #500; color: #fff; border: none; border-radius: 4px; font-weight: bold; }"
            "QPushButton:hover { background: #a00; }"
        )
        close_btn.clicked.connect(self.hide)
        header.addWidget(close_btn)
        layout.addLayout(header)

        tabs = QTabWidget()
        tabs.setStyleSheet("""
            QTabWidget::pane { border: 1px solid #444; border-radius: 4px; background: transparent; }
            QTabBar::tab { background: #222; color: #aaa; padding: 6px 14px; border: 1px solid #444; border-bottom: none; border-radius: 4px 4px 0 0; margin-right: 2px; }
            QTabBar::tab:selected { background: #333; color: #0f0; }
        """)
        tabs.addTab(self._build_esp_tab(), "ESP")
        tabs.addTab(self._build_camo_tab(), "Camouflage")
        tabs.addTab(self._build_aim_tab(), "Aimbot")
        layout.addWidget(tabs)

        hint = QLabel("✕ close  |  Insert/F1: show  |  F10: camouflage")
        hint.setStyleSheet("color: #888; font-size: 10px; padding-top: 4px;")
        layout.addWidget(hint)

        outer.addWidget(container)
        self.setLayout(outer)

    def _sc(self, attr, value):
        setattr(self.config, attr, value)
        self.config.save()

    def _chk(self, text, attr, parent):
        cb = QCheckBox(text)
        cb.setChecked(getattr(self.config, attr))
        cb.stateChanged.connect(lambda s, a=attr: self._sc(a, bool(s)))
        if parent: parent.addWidget(cb)
        return cb

    def _build_esp_tab(self):
        w = QWidget(); lo = QVBoxLayout(w); lo.setSpacing(6)
        g = self._make_group("Display", "#0f0")
        gl = QVBoxLayout(g); gl.setSpacing(4)
        self._chk("ESP Enabled", "esp_enabled", gl)

        style_row = QHBoxLayout()
        style_row.addWidget(QLabel("Style:"))
        cb = QComboBox()
        cb.addItems(["Dot", "2D Box", "Both"])
        cb.setCurrentIndex({"dot": 0, "box": 1, "both": 2}.get(self.config.esp_style, 0))
        cb.currentTextChanged.connect(lambda t, a="esp_style": self._sc(a, {"Dot": "dot", "2D Box": "box", "Both": "both"}.get(t, "dot")))
        style_row.addWidget(cb)
        gl.addLayout(style_row)

        self._chk("Corner Box", "corner_box", gl)
        self._chk("Skeleton", "skeleton_esp", gl)
        self._chk("Show Local Player", "show_local", gl)
        self._chk("Snap Lines", "snap_lines", gl)
        self._chk("Team Filter (Hunters)", "team_filter", gl)
        lo.addWidget(g)

        g2 = self._make_group("Labels", "#0f0")
        gl2 = QVBoxLayout(g2); gl2.setSpacing(4)
        self._chk("Names", "show_names", gl2)
        self._chk("Distance", "show_distance", gl2)
        self._chk("Health", "show_health", gl2)
        self._chk("Shield", "show_shield", gl2)
        self._chk("Weapon", "show_weapon", gl2)
        lo.addWidget(g2)

        g3 = self._make_group("Appearance", "#0f0")
        gl3 = QGridLayout(g3); gl3.setSpacing(4)
        gl3.addWidget(QLabel("Model Height:"), 0, 0)
        sp0 = QSpinBox(); sp0.setRange(50, 300); sp0.setValue(int(self.config.box_height_world))
        sp0.valueChanged.connect(lambda v: self._sc("box_height_world", float(v)))
        gl3.addWidget(sp0, 0, 1)

        gl3.addWidget(QLabel("Dot Radius:"), 1, 0)
        sp = QSpinBox(); sp.setRange(2, 32); sp.setValue(self.config.dot_radius)
        sp.valueChanged.connect(lambda v: self._sc("dot_radius", v))
        gl3.addWidget(sp, 1, 1)

        gl3.addWidget(QLabel("Y Offset:"), 2, 0)
        sp2 = QSpinBox(); sp2.setRange(-50, 50); sp2.setValue(self.config.box_y_offset)
        sp2.valueChanged.connect(lambda v: self._sc("box_y_offset", v))
        gl3.addWidget(sp2, 2, 1)

        gl3.addWidget(QLabel("Max Dist (m):"), 3, 0)
        sp3 = QSpinBox(); sp3.setRange(0, 10000); sp3.setValue(self.config.max_distance)
        sp3.setSuffix(" m"); sp3.setSpecialValueText("Off")
        sp3.valueChanged.connect(lambda v: self._sc("max_distance", v))
        gl3.addWidget(sp3, 3, 1)

        hr = QHBoxLayout()
        b1 = QPushButton("Enemy Color"); b1.clicked.connect(lambda: self._pick_color("enemy_color"))
        b2 = QPushButton("Local Color"); b2.clicked.connect(lambda: self._pick_color("local_color"))
        hr.addWidget(b1); hr.addWidget(b2)
        gl3.addLayout(hr, 4, 0, 1, 2)
        lo.addWidget(g3)
        lo.addStretch()
        return w

    def _build_camo_tab(self):
        w = QWidget(); lo = QVBoxLayout(w); lo.setSpacing(6)
        g = self._make_group("Active Camouflage", "#ff0")
        gl = QVBoxLayout(g); gl.setSpacing(4)
        self._chk("Enabled", "camo_enabled", gl)
        gl.addWidget(QLabel("F10 captures screen centre (GDI) or uses preset colour below."))
        gl.addWidget(QLabel("Colour is written directly to player material via pymem."))
        lo.addWidget(g)

        g3 = self._make_group("Preset Colour (fallback)", "#ff0")
        gl3 = QVBoxLayout(g3); gl3.setSpacing(4)
        gr2 = QGridLayout()
        for i, (ch, attr) in enumerate([("R", "camo_default_r"), ("G", "camo_default_g"), ("B", "camo_default_b")]):
            gr2.addWidget(QLabel(f"{ch}:"), i, 0)
            ds = QDoubleSpinBox(); ds.setRange(0, 1); ds.setSingleStep(0.05)
            ds.setValue(getattr(self.config, attr))
            ds.valueChanged.connect(lambda v, a=attr: self._sc(a, v))
            gr2.addWidget(ds, i, 1)
        gl3.addLayout(gr2)
        lo.addWidget(g3)

        self._camo_status = QLabel("Status: Ready")
        self._camo_status.setStyleSheet("color: #888; font-size: 11px; padding: 4px;")
        lo.addWidget(self._camo_status)
        lo.addStretch()
        return w

    def _build_aim_tab(self):
        w = QWidget(); lo = QVBoxLayout(w); lo.setSpacing(6)
        g = self._make_group("Aimbot", "#f0f")
        gl = QVBoxLayout(g); gl.setSpacing(4)
        self._chk("Aimbot Enabled", "aimbot_enabled", gl)
        self._chk("Show FOV Circle", "aimbot_show_fov", gl)

        krow = QHBoxLayout()
        self._lbl_key = QLabel(f"Aim Key: {self.config.aimbot_key}")
        btn = QPushButton("Record Key")
        btn.clicked.connect(self._record_key)
        krow.addWidget(self._lbl_key); krow.addWidget(btn)
        gl.addLayout(krow)

        gr = QGridLayout(); gr.setSpacing(4)
        gr.addWidget(QLabel("FOV:"), 0, 0)
        sp = QSpinBox(); sp.setRange(10, 600); sp.setValue(self.config.aimbot_fov)
        sp.valueChanged.connect(lambda v: self._sc("aimbot_fov", v))
        gr.addWidget(sp, 0, 1)

        gr.addWidget(QLabel("Smooth:"), 1, 0)
        ds = QDoubleSpinBox(); ds.setRange(0.01, 1.0); ds.setSingleStep(0.05); ds.setValue(self.config.aimbot_smooth)
        ds.valueChanged.connect(lambda v: self._sc("aimbot_smooth", v))
        gr.addWidget(ds, 1, 1)

        gr.addWidget(QLabel("Offset:"), 2, 0)
        sp2 = QSpinBox(); sp2.setRange(-200, 200); sp2.setValue(int(self.config.aimbot_target_offset))
        sp2.valueChanged.connect(lambda v: self._sc("aimbot_target_offset", float(v)))
        gr.addWidget(sp2, 2, 1)
        gl.addLayout(gr)
        lo.addWidget(g)
        lo.addStretch()
        return w

    def _pick_color(self, attr):
        c = getattr(self.config, attr)
        c2 = QColorDialog.getColor(QColor(*c), self)
        if c2.isValid():
            self._sc(attr, (c2.red(), c2.green(), c2.blue()))

    def _record_key(self):
        self._rec_btn = self.sender()
        self._rec_btn.setEnabled(False)
        self._rec_btn.setText("Press any key...")
        self._rec_start = ctypes.windll.kernel32.GetTickCount()
        self._rec_timer = QTimer(self)
        self._rec_timer.timeout.connect(self._poll_key)
        self._rec_timer.start(50)

    def _poll_key(self):
        if ctypes.windll.kernel32.GetTickCount() - self._rec_start < 300: return
        for vk in range(1, 0x100):
            if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                name = VK_NAMES.get(vk, f"VK_{vk:02X}")
                self._sc("aimbot_key", name)
                self._lbl_key.setText(f"Aim Key: {name}")
                self._rec_timer.stop()
                self._rec_btn.setEnabled(True); self._rec_btn.setText("Record Key")
                return
        if ctypes.windll.kernel32.GetTickCount() - self._rec_start > 5000:
            self._rec_timer.stop()
            self._rec_btn.setEnabled(True); self._rec_btn.setText("Record Key")

    def update_camo_status(self, text):
        self._camo_status.setText(f"Status: {text}")
        self._camo_status.setStyleSheet(
            "color: #0f0; font-size: 11px; padding: 4px;"
            if "OK" in text or "Ready" in text
            else "color: #f00; font-size: 11px; padding: 4px;"
        )

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.LeftButton:
            self.move(e.globalPos() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------
class Overlay(QWidget):
    AIM_KEY_VK = {
        "LMB": 0x01, "RMB": 0x02, "MMB": 0x04, "MB4": 0x05, "MB5": 0x06,
        "Backspace": 0x08, "Tab": 0x09, "Enter": 0x0D, "Shift": 0x10,
        "Ctrl": 0x11, "Alt": 0x12, "Pause": 0x13, "Esc": 0x1B, "Space": 0x20,
        "PageUp": 0x21, "PageDown": 0x22, "End": 0x23, "Home": 0x24,
        "Left": 0x25, "Up": 0x26, "Right": 0x27, "Down": 0x28,
        "Insert": 0x2D, "Delete": 0x2E,
        "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
        "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
        "A": 0x41, "B": 0x42, "C": 0x43, "D": 0x44, "E": 0x45, "F": 0x46,
        "G": 0x47, "H": 0x48, "I": 0x49, "J": 0x4A, "K": 0x4B, "L": 0x4C,
        "M": 0x4D, "N": 0x4E, "O": 0x4F, "P": 0x50, "Q": 0x51, "R": 0x52,
        "S": 0x53, "T": 0x54, "U": 0x55, "V": 0x56, "W": 0x57, "X": 0x58,
        "Y": 0x59, "Z": 0x5A,
        "Num0": 0x60, "Num1": 0x61, "Num2": 0x62, "Num3": 0x63, "Num4": 0x64,
        "Num5": 0x65, "Num6": 0x66, "Num7": 0x67, "Num8": 0x68, "Num9": 0x69,
        "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
        "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
        "F11": 0x7A, "F12": 0x7B,
        ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
        "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    }

    def __init__(self, reader: GameReader, config: Config, menu: Menu):
        super().__init__()
        self.reader = reader
        self.config = config
        self.menu = menu
        self.applier = CamoApplier(reader) if reader else None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
            | Qt.Tool | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

        self._find_game_window()
        self._resize_to_game()

    def _find_game_window(self):
        try:
            self._hwnd = win32gui.FindWindow(None, "Chameleon  ")
        except: self._hwnd = 0

    def _resize_to_game(self):
        try:
            if self._hwnd:
                r = win32gui.GetClientRect(self._hwnd)
                tl = win32gui.ClientToScreen(self._hwnd, (r[0], r[1]))
                br = win32gui.ClientToScreen(self._hwnd, (r[2], r[3]))
                self.setGeometry(tl[0], tl[1], br[0]-tl[0], br[1]-tl[1])
        except: pass

    def _tick(self):
        self._resize_to_game()
        self.update()

    def _do_camouflage(self):
        if not self.config.camo_enabled:
            return
        try:
            color = sample_screen_center(self._hwnd)
            if color is None:
                color = (self.config.camo_default_r,
                         self.config.camo_default_g,
                         self.config.camo_default_b)
            self.config.camo_last_color = color
            self.config.camo_last_time = time.time()

            ok = False
            if self.applier:
                ok = self.applier.apply(*color)

            rgb = tuple(int(c * 255) for c in color)
            if ok:
                self.config.camo_status = f"OK  RGB({rgb[0]},{rgb[1]},{rgb[2]})"
            else:
                self.config.camo_status = f"Write failed (RGB {rgb[0]},{rgb[1]},{rgb[2]})"
        except Exception as e:
            self.config.camo_status = f"Error: {e}"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(QFont("Consolas", 10))
        w, h = self.width(), self.height()

        if not self.config.esp_enabled and not self.config.camo_enabled:
            p.setPen(QPen(QColor(255,255,255)))
            p.drawText(10, 20, "DISABLED")
            return

        # Camouflage notification
        if self.config.camo_enabled and self.config.camo_last_time:
            age = time.time() - self.config.camo_last_time
            if age < 3.0:
                c = self.config.camo_last_color
                qc = QColor(int(c[0]*255), int(c[1]*255), int(c[2]*255))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(qc))
                p.drawRect(w - 50, 10, 30, 30)
                p.setPen(QPen(QColor(255,255,255)))
                p.drawText(w - 110, 28, f"{self.config.camo_status}")

        if not self.config.esp_enabled:
            return

        # ESP rendering
        cam = self.reader.get_camera() if self.reader else None
        if not cam:
            p.setPen(QPen(QColor(255,255,255)))
            p.drawText(10, 20, "NO CAMERA")
            return

        count = 0
        for is_local, pos, idx, pawn in self.reader.iter_players(
                include_local=self.config.show_local,
                team_filter=self.config.team_filter):
            s = self._project(pos, cam, w, h)
            if not s: continue
            sx, sy = s
            col = self.config.local_color if is_local else self.config.enemy_color
            style = self.config.esp_style

            # Distance culling
            pdist = int(dist(pos, cam["loc"]) / 100)
            if self.config.max_distance > 0 and pdist > self.config.max_distance:
                continue

            # Dot
            if style in ("dot", "both"):
                self._draw_dot(p, int(sx), int(sy), col, self.config.dot_radius)

            # 2D Box / Corner Box
            if style in ("box", "both"):
                head = (pos[0], pos[1], pos[2] + self.config.box_height_world)
                sh = w2s(head, cam, w, h)
                if sh:
                    if self.config.corner_box:
                        self._draw_corner_box(p, int(sh[0]), int(sh[1]), int(sx), int(sy), col, self.config.box_y_offset)
                    else:
                        self._draw_2d_box(p, int(sh[0]), int(sh[1]), int(sx), int(sy), col, self.config.box_y_offset)

            # Skeleton
            if self.config.skeleton_esp and not is_local and pawn:
                self._render_skeleton(p, pawn, pos, cam, w, h, col)

            # Snap lines
            if self.config.snap_lines:
                p.setPen(QPen(QColor(*col), 1))
                p.drawLine(int(w/2), int(h), int(sx), int(sy))

            # Labels
            parts = []
            if self.config.show_names:
                parts.append("YOU" if is_local else f"E{idx}")
            if self.config.show_distance:
                parts.append(f"{pdist}m")
            if self.config.show_health and pawn:
                hp = self.reader.read_health(pawn)
                if hp is not None:
                    parts.append(f"HP:{hp:.0f}")
            if self.config.show_shield and pawn:
                sh = self.reader.read_shield(pawn)
                if sh is not None:
                    parts.append(f"SD:{sh:.0f}")
            if self.config.show_weapon and pawn:
                wpn = self.reader.read_weapon_name(pawn)
                if wpn:
                    parts.append(f"[{wpn}]")
            if parts:
                label_x = sx + self.config.dot_radius + 4
                label_y = sy
                if style in ("box", "both"):
                    head_px = w2s((pos[0], pos[1], pos[2] + self.config.box_height_world), cam, w, h)
                    if head_px:
                        label_y = int(head_px[1]) - 8
                p.setPen(QPen(QColor(*col)))
                p.drawText(int(label_x), label_y, " | ".join(parts))
            count += 1

        p.setPen(QPen(QColor(255,255,255)))
        p.drawText(10, 20, f"Players: {count}")
        if self.config.camo_enabled and self.config.camo_last_time:
            if time.time() - self.config.camo_last_time < 3.0:
                p.drawText(10, 36, f"Camo: {self.config.camo_status}")

        if self.config.aimbot_enabled:
            cx, cy = w/2, h/2
            if self.config.aimbot_show_fov:
                p.setPen(QPen(QColor(255,255,255,80), 1))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(int(cx - self.config.aimbot_fov),
                              int(cy - self.config.aimbot_fov),
                              self.config.aimbot_fov * 2,
                              self.config.aimbot_fov * 2)
            target = self._best_target(cam, w, h)
            if target and self._aim_held():
                self._aim_at(target)

    def _project(self, pos, cam, sw, sh):
        return w2s(pos, cam, sw, sh)

    def _draw_dot(self, p, x, y, color, radius):
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(*color))
        p.drawEllipse(x - radius, y - radius, radius * 2, radius * 2)

    def _draw_2d_box(self, p, head_x, head_y, foot_x, foot_y, color, y_offset):
        foot_y += y_offset
        head_y += y_offset
        box_h = foot_y - head_y
        if box_h <= 4: return
        half_w = int(box_h * 0.35)
        l = int(min(head_x, foot_x)) - half_w
        r = int(max(head_x, foot_x)) + half_w
        t = int(head_y)
        b = int(foot_y)
        c = QColor(*color)
        p.setPen(QPen(c, 2))
        p.setBrush(Qt.NoBrush)
        p.drawRect(l, t, r - l, b - t)

    def _draw_corner_box(self, p, head_x, head_y, foot_x, foot_y, color, y_offset):
        foot_y += y_offset
        head_y += y_offset
        box_h = foot_y - head_y
        if box_h <= 4: return
        half_w = int(box_h * 0.35)
        l = int(min(head_x, foot_x)) - half_w
        r = int(max(head_x, foot_x)) + half_w
        t = int(head_y)
        b = int(foot_y)
        cor = max(6, int(box_h * 0.12))
        c = QColor(*color)
        pen = QPen(c, 2)
        p.setPen(pen)
        # top-left
        p.drawLine(l, t, l + cor, t)
        p.drawLine(l, t, l, t + cor)
        # top-right
        p.drawLine(r, t, r - cor, t)
        p.drawLine(r, t, r, t + cor)
        # bottom-left
        p.drawLine(l, b, l + cor, b)
        p.drawLine(l, b, l, b - cor)
        # bottom-right
        p.drawLine(r, b, r - cor, b)
        p.drawLine(r, b, r, b - cor)

    def _render_skeleton(self, p, pawn, actor_pos, cam, sw, sh, color):
        foot_s = self._project(actor_pos, cam, sw, sh)
        head_s = w2s((actor_pos[0], actor_pos[1], actor_pos[2] + self.config.box_height_world), cam, sw, sh)
        if not foot_s or not head_s: return
        fx, fy = foot_s
        hx, hy = head_s
        box_h = fy - hy
        if box_h < 10: return
        cx = int(fx)
        sh_w = int(box_h * 0.22)
        arm_y = int(hy + box_h * 0.30)
        hand_y = int(hy + box_h * 0.60)
        leg_sp = int(box_h * 0.12)
        knee_y = int(fy - box_h * 0.40)
        c = QColor(*color)
        pen = QPen(c, 2)
        p.setPen(pen)
        # Spine
        p.drawLine(cx, int(hy), cx, int(fy))
        # Shoulders
        p.drawLine(cx - sh_w, arm_y, cx + sh_w, arm_y)
        # Arms
        p.drawLine(cx - sh_w, arm_y, cx - sh_w - 4, hand_y)
        p.drawLine(cx + sh_w, arm_y, cx + sh_w + 4, hand_y)
        # Hips
        p.drawLine(cx - leg_sp, int(fy - box_h * 0.15), cx + leg_sp, int(fy - box_h * 0.15))
        # Legs
        p.drawLine(cx - leg_sp, int(fy - box_h * 0.15), cx - leg_sp - 3, int(knee_y))
        p.drawLine(cx - leg_sp - 3, int(knee_y), cx - leg_sp - 3, int(fy))
        p.drawLine(cx + leg_sp, int(fy - box_h * 0.15), cx + leg_sp + 3, int(knee_y))
        p.drawLine(cx + leg_sp + 3, int(knee_y), cx + leg_sp + 3, int(fy))

    def _aim_held(self):
        vk = self.AIM_KEY_VK.get(self.config.aimbot_key, 0x06)
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

    def _best_target(self, cam, sw, sh):
        world = self.reader._get_world()
        local_pc = self.reader._get_local_controller(world) if world else 0
        local_pawn = rp(self.reader.pm, local_pc + self.reader.offsets["APlayerController::AcknowledgedPawn"]) if local_pc else 0
        local_pos = None
        if local_pawn:
            root = rp(self.reader.pm, local_pawn + self.reader.offsets["AActor::RootComponent"])
            if root:
                local_pos = rvec3(self.reader.pm, root + self.reader.offsets["USceneComponent::RelativeLocation"])

        cx, cy = sw/2, sh/2; best_d = float("inf"); best = None
        cam_loc = cam["loc"]
        for is_local, pos, idx, _ in self.reader.iter_players(include_local=False, team_filter=self.config.team_filter):
            if is_local: continue
            if local_pos:
                dself = math.sqrt((pos[0] - local_pos[0])**2 + (pos[1] - local_pos[1])**2 + (pos[2] - local_pos[2])**2)
                if dself < 50.0: continue
            dcam = math.sqrt((pos[0] - cam_loc[0])**2 + (pos[1] - cam_loc[1])**2 + (pos[2] - cam_loc[2])**2)
            if dcam < 50.0: continue
            ap = (pos[0], pos[1], pos[2] + self.config.aimbot_target_offset)
            s = w2s(ap, cam, sw, sh)
            if not s: continue
            d = math.sqrt((s[0]-cx)**2 + (s[1]-cy)**2)
            if d <= self.config.aimbot_fov and d < best_d:
                best_d = d; best = ap
        return best

    def _vector_to_rotation(self, vec):
        x, y, z = vec
        ln = math.sqrt(x*x + y*y + z*z)
        if ln == 0: return (0.0, 0.0, 0.0)
        return (math.degrees(math.asin(z/ln)), math.degrees(math.atan2(y, x)), 0.0)

    def _read_control_rotation(self):
        world = self.reader._get_world()
        if not world: return None
        pc = self.reader._get_local_controller(world)
        if not pc: return None
        addr = pc + self.reader.offsets["AController::ControlRotation"]
        return (rfloat(self.reader.pm, addr), rfloat(self.reader.pm, addr+4), rfloat(self.reader.pm, addr+8))

    def _write_control_rotation(self, rot):
        world = self.reader._get_world()
        if not world: return False
        pc = self.reader._get_local_controller(world)
        if not pc: return False
        addr = pc + self.reader.offsets["AController::ControlRotation"]
        wfloat(self.reader.pm, addr, rot[0])
        wfloat(self.reader.pm, addr+4, rot[1])
        wfloat(self.reader.pm, addr+8, rot[2])
        return True

    def _aim_at(self, target):
        cam = self.reader.get_camera()
        if not cam: return
        current = self._read_control_rotation()
        if current is None: return
        dx = target[0] - cam["loc"][0]; dy = target[1] - cam["loc"][1]; dz = target[2] - cam["loc"][2]
        target_rot = self._vector_to_rotation((dx, dy, dz))
        s = self.config.aimbot_smooth
        self._write_control_rotation((
            current[0] + (target_rot[0] - current[0]) * s,
            current[1] + (target_rot[1] - current[1]) * s,
            current[2]
        ))

# ---------------------------------------------------------------------------
# World-to-screen
# ---------------------------------------------------------------------------
def rotation_to_axes(rot):
    p, y, r = [math.radians(x) for x in rot]
    sp, cp = math.sin(p), math.cos(p)
    sy, cy = math.sin(y), math.cos(y)
    sr, cr = math.sin(r), math.cos(r)
    return ((cp*cy, cp*sy, sp),
            (sr*sp*cy - cr*sy, sr*sp*sy + cr*cy, -sr*cp),
            (-(cr*sp*cy + sr*sy), cy*sr - cr*sp*sy, cr*cp))

def w2s(wp, cam, sw, sh):
    cl = cam["loc"]; fwd, right, up = rotation_to_axes(cam["rot"])
    dx = wp[0]-cl[0]; dy = wp[1]-cl[1]; dz = wp[2]-cl[2]
    vx = dx*fwd[0] + dy*fwd[1] + dz*fwd[2]
    vy = dx*right[0] + dy*right[1] + dz*right[2]
    vz = dx*up[0] + dy*up[1] + dz*up[2]
    if vx <= 0.1: return None
    asp = sw/sh; th = math.tan(math.radians(cam["fov"])/2)
    nx = vy/(vx*th); ny = vz/(vx*th/asp)
    sx = (1+nx)*sw/2; sy = (1-ny)*sh/2
    return (sx, sy) if (0 <= sx <= sw and 0 <= sy <= sh) else None

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def _dpi():
    try: ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except:
        try: ctypes.windll.user32.SetProcessDPIAware()
        except: pass

def main():
    _dpi()
    app = QApplication(sys.argv)
    config = Config()
    config.load()

    try:
        reader = GameReader()
        player_class = reader.find_player_class()
        print(f"  Game: {PROCESS_NAME} attached")
        if player_class: print(f"  Player class: {player_class}")
    except Exception as e:
        print(f"  Game attach failed: {e}")
        print("  ESP, aimbot, and camouflage require game access — exiting.")
        return

    menu = Menu(config)
    overlay = Overlay(reader, config, menu)
    overlay.show()
    menu.show()

    VK_INSERT, VK_F1, VK_F10 = 0x2D, 0x70, 0x79
    key_states = {"ins": False, "f1": False, "f10": False}

    def poll():
        for vk, name in [(VK_INSERT, "ins"), (VK_F1, "f1"), (VK_F10, "f10")]:
            state = bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)
            if name == "f10":
                if state and not key_states[name]:
                    overlay._do_camouflage()
                    if hasattr(menu, 'update_camo_status'):
                        menu.update_camo_status(config.camo_status)
                key_states[name] = state
            else:
                if state and not key_states[name]:
                    menu.setVisible(not menu.isVisible())
                key_states[name] = state

    kt = QTimer()
    kt.timeout.connect(poll)
    kt.start(50)

    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
