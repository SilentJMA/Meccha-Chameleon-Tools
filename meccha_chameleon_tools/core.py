#!/usr/bin/env python3
"""
Core game reading engine for MECCA CHAMELEON (UE5.6) ESP.
Memory primitives, pattern scanning, FName resolution, object array,
offset resolution, and game state reading.
"""
import struct
import math
import pymem

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
    "FCameraCacheEntry::POV": 0x10,
    "FMinimalViewInfo::Location": 0x0,
    "FMinimalViewInfo::Rotation": 0x18,
    "FMinimalViewInfo::FOV": 0x30,
}

# ---------------------------------------------------------------------------
# Memory primitives
# ---------------------------------------------------------------------------
def rp(pm, addr):
    try:
        return struct.unpack("<Q", pm.read_bytes(addr, 8))[0]
    except Exception:
        return 0

def ru32(pm, addr):
    try:
        return struct.unpack("<I", pm.read_bytes(addr, 4))[0]
    except Exception:
        return 0

def ru16(pm, addr):
    try:
        return struct.unpack("<H", pm.read_bytes(addr, 2))[0]
    except Exception:
        return 0

def rfloat(pm, addr):
    try:
        return struct.unpack("<f", pm.read_bytes(addr, 4))[0]
    except Exception:
        return 0.0

def wfloat(pm, addr, value):
    try:
        pm.write_bytes(addr, struct.pack("<f", value), 4)
        return True
    except Exception:
        return False

def rvec3(pm, addr):
    try:
        return struct.unpack("<ddd", pm.read_bytes(addr, 24))
    except Exception:
        return (0.0, 0.0, 0.0)

def rvec3_f(pm, addr):
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

    # -----------------------------------------------------------------------
    # Component walking
    # -----------------------------------------------------------------------
    def _owned_components_offset(self):
        key = "AActor::OwnedComponents"
        cached = getattr(self, "_owned_components_off", None)
        if cached is not None:
            return cached
        off = self.resolver.resolve("Actor", "OwnedComponents")
        if off is None:
            off = 0xD0
        self._owned_components_off = off
        return off

    def walk_owned_components(self, actor):
        off = self._owned_components_offset()
        oc_addr = actor + off
        data, count = read_tarray_ptr(self.pm, oc_addr)
        if not data or count == 0 or count > 512:
            return
        for i in range(count):
            comp = rp(self.pm, data + i * 8)
            if comp:
                yield comp

    def find_component_by_class(self, actor, class_name):
        cname_lower = class_name.lower()
        for comp in self.walk_owned_components(actor):
            cn = self.objects.class_name(comp)
            if cn.lower() == cname_lower:
                return comp
        return 0

    def find_component_by_class_partial(self, actor, name_part):
        for comp in self.walk_owned_components(actor):
            cn = self.objects.class_name(comp)
            if name_part in cn:
                return comp
        return 0

    # -----------------------------------------------------------------------
    # Bone / skeletal mesh reading
    # -----------------------------------------------------------------------
    BONE_CONNECTIONS = [
        ("root", "pelvis"),
        ("pelvis", "spine_01"),
        ("spine_01", "spine_02"),
        ("spine_02", "spine_03"),
        ("spine_03", "neck_01"),
        ("neck_01", "head"),
        ("clavicle_l", "upperarm_l"),
        ("upperarm_l", "lowerarm_l"),
        ("lowerarm_l", "hand_l"),
        ("clavicle_r", "upperarm_r"),
        ("upperarm_r", "lowerarm_r"),
        ("lowerarm_r", "hand_r"),
        ("pelvis", "thigh_l"),
        ("thigh_l", "calf_l"),
        ("calf_l", "foot_l"),
        ("pelvis", "thigh_r"),
        ("thigh_r", "calf_r"),
        ("calf_r", "foot_r"),
    ]

    COMMON_BONE_NAMES = [
        "root", "pelvis",
        "spine_01", "spine_02", "spine_03",
        "neck_01", "head",
        "clavicle_l", "upperarm_l", "lowerarm_l", "hand_l",
        "clavicle_r", "upperarm_r", "lowerarm_r", "hand_r",
        "thigh_l", "calf_l", "foot_l",
        "thigh_r", "calf_r", "foot_r",
    ]

    def _resolve_bone_indices(self, skeletal_mesh):
        """Try to map bone names -> indices via FName resolution on the skeleton."""
        # Get bone names from the skeleton
        # USkeletalMesh::RefSkeleton holds bone info
        # We try: USkeletalMeshComponent->SkeletalMesh->RefSkeleton->GetRefBoneInfo()
        mesh_ptr = rp(self.pm, skeletal_mesh + 0x4A0)
        if not mesh_ptr:
            return {}
        ref_skeleton = mesh_ptr + 0xA0
        bone_data, bone_count = read_tarray_ptr(self.pm, ref_skeleton)
        if not bone_data or bone_count == 0 or bone_count > 512:
            return {}
        name_to_idx = {}
        for i in range(bone_count):
            name_idx = ru32(self.pm, bone_data + i * 0x20)
            bone_name = self.objects.fnames.resolve(name_idx)
            if bone_name:
                name_to_idx[bone_name.lower()] = i
        return name_to_idx

    def get_skeletal_mesh(self, actor):
        """Find USkeletalMeshComponent on the actor. Tries multiple class name patterns."""
        # Try primary match first
        mesh = self.find_component_by_class_partial(actor, "SkeletalMeshComponent")
        if mesh:
            return mesh
        # Try broader patterns
        for pattern in ("SkinnedMeshComponent", "MeshComponent", "SkeletalMesh"):
            mesh = self.find_component_by_class_partial(actor, pattern)
            if mesh:
                return mesh
        return 0

    def get_bone_transforms(self, skeletal_mesh):
        """Read ComponentSpaceTransforms TArray<FTransform> from USkeletalMeshComponent."""
        if not skeletal_mesh:
            return None
        transforms_addr = skeletal_mesh + 0x5C0
        data, count = read_tarray_ptr(self.pm, transforms_addr)
        if not data or count == 0 or count > 1024:
            return None
        bones = []
        for i in range(count):
            offset = data + i * 0x50
            try:
                raw = self.pm.read_bytes(offset, 0x50)
                qx, qy, qz, qw = struct.unpack("<dddd", raw[0:32])
                tx, ty, tz = struct.unpack("<ddd", raw[32:56])
                bones.append(((tx, ty, tz), (qx, qy, qz, qw)))
            except Exception:
                bones.append(None)
        return bones

    def get_skeleton_positions(self, actor):
        """Return a dict of bone_name -> world_position for the actor."""
        mesh = self.get_skeletal_mesh(actor)
        if not mesh:
            return None
        transforms = self.get_bone_transforms(mesh)
        if not transforms:
            return None
        name_map = self._resolve_bone_indices(mesh)
        result = {}
        for bname in self.COMMON_BONE_NAMES:
            idx = name_map.get(bname.lower())
            if idx is not None and idx < len(transforms) and transforms[idx]:
                pos, _ = transforms[idx]
                result[bname] = pos
        return result

    def get_skeleton_positions_by_indices(self, actor, bone_indices):
        """Get bone positions by direct index map {name: index}."""
        mesh = self.get_skeletal_mesh(actor)
        if not mesh:
            return None
        transforms = self.get_bone_transforms(mesh)
        if not transforms:
            return None
        result = {}
        for name, idx in bone_indices.items():
            if idx < len(transforms) and transforms[idx]:
                pos, _ = transforms[idx]
                result[name] = pos
        return result

    # -----------------------------------------------------------------------
    # Player iteration (enhanced)
    # -----------------------------------------------------------------------
    def iter_players(self, include_local=False, team_filter=False):
        world = self._get_world()
        if not world:
            return
        gamestate = rp(self.pm, world + self.offsets["UWorld::GameState"])
        pc = self._get_local_controller(world)
        local_pawn = rp(self.pm, pc + self.offsets["APlayerController::AcknowledgedPawn"]) if pc else 0
        local_ps = rp(self.pm, pc + self.offsets["AController::PlayerState"]) if pc else 0
        local_pawn_cls = self.objects.class_name(local_pawn)

        if include_local and local_pawn:
            pos = self.get_actor_root_pos(local_pawn)
            if pos:
                yield {
                    "is_local": True,
                    "pos": pos,
                    "idx": 0,
                    "actor": local_pawn,
                    "player_state": local_ps,
                }

        yielded = 0
        if gamestate:
            pa_data, pa_count, _ = read_array(self.pm, gamestate + self.offsets["AGameStateBase::PlayerArray"])
            if pa_data and pa_count > 0:
                for i in range(pa_count):
                    ps = rp(self.pm, pa_data + i * 8)
                    if not ps or ps == local_ps:
                        continue
                    pawn = rp(self.pm, ps + self.offsets["APlayerState::PawnPrivate"])
                    if not pawn or pawn == local_pawn:
                        continue
                    pawn_cls = self.objects.class_name(pawn)
                    if not pawn_cls:
                        continue
                    if team_filter and local_pawn_cls:
                        if pawn_cls == local_pawn_cls:
                            continue
                        if "Spectate" in pawn_cls:
                            continue
                    pos = self.get_actor_root_pos(pawn)
                    if not pos:
                        continue
                    yielded += 1
                    yield {
                        "is_local": False,
                        "pos": pos,
                        "idx": i,
                        "actor": pawn,
                        "player_state": ps,
                    }

        if yielded == 0:
            persistent_level_off = self.resolver.resolve("World", "PersistentLevel") if hasattr(self, "resolver") else None
            if persistent_level_off is None:
                persistent_level_off = 0x30
            level = rp(self.pm, world + persistent_level_off)
            if level:
                actors_off = self.resolver.resolve("Level", "Actors") if hasattr(self, "resolver") else None
                if actors_off is None:
                    actors_off = 0x98
                actors_data, actors_count, _ = read_array(self.pm, level + actors_off)
                if actors_data and actors_count > 0:
                    for i in range(actors_count):
                        actor = rp(self.pm, actors_data + i * 8)
                        if not actor or actor == local_pawn:
                            continue
                        cls_name = self.objects.class_name(actor)
                        if not cls_name or "Character" not in cls_name:
                            continue
                        pos = self.get_actor_root_pos(actor)
                        if not pos:
                            continue
                        yielded += 1
                        yield {
                            "is_local": False,
                            "pos": pos,
                            "idx": i,
                            "actor": actor,
                            "player_state": 0,
                        }

    # -----------------------------------------------------------------------
    # Camouflage — 3D character color writing
    # -----------------------------------------------------------------------
    def _get_local_pawn(self):
        """Get the local player pawn address."""
        world = self._get_world()
        if not world:
            return 0
        pc = self._get_local_controller(world)
        if not pc:
            return 0
        return rp(self.pm, pc + self.offsets["APlayerController::AcknowledgedPawn"])

    def _find_materials_offset(self, mesh_component):
        """Brute-force find the Materials TArray offset on a mesh component."""
        for off in (0x4D0, 0x4E0, 0x4F0, 0x500, 0x510, 0x4C0, 0x4B0, 0x4A8):
            try:
                data, count = read_tarray_ptr(self.pm, mesh_component + off)
                if data and 0 < count <= 32:
                    first = rp(self.pm, data)
                    if first and first > 0x100000:
                        return off
            except Exception:
                continue
        return None

    def _get_mesh_materials(self, mesh_component):
        """Get material instance pointers from a mesh component.
        Tries a wide range of offsets for the Materials TArray."""
        # Broader offset range for Materials TArray
        for off in range(0x4A0, 0x550, 8):
            try:
                data, count = read_tarray_ptr(self.pm, mesh_component + off)
                if data and 1 <= count <= 32:
                    first = rp(self.pm, data)
                    if first and first > 0x100000:
                        mats = []
                        for i in range(count):
                            mat = rp(self.pm, data + i * 8)
                            if mat:
                                mats.append(mat)
                        if mats:
                            return mats
            except Exception:
                continue
        return []

    def _find_color_parameter(self, material):
        """Brute-force find a vector parameter with valid FLinearColor on a material instance.
        Only returns addresses verified to be within the TArray data bounds."""
        # Wider range of offsets for VectorParameterValues TArray
        for off in range(0x38, 0x140, 8):
            try:
                data, count = read_tarray_ptr(self.pm, material + off)
                if not data or count == 0 or count > 64:
                    continue
                # Try multiple struct strides
                for stride in (0x18, 0x20, 0x28, 0x30):
                    data_end = data + count * stride
                    for j in range(min(count, 32)):
                        param_addr = data + j * stride
                        # Try FLinearColor at known field offsets within the struct
                        for color_off in (0x10, 0x14, 0x18):
                            color_addr = param_addr + color_off
                            # CRITICAL: only accept addresses inside the TArray data range
                            if not (data <= color_addr < data_end and color_addr + 16 <= data_end):
                                continue
                            try:
                                raw = self.pm.read_bytes(color_addr, 16)
                                if len(raw) < 16:
                                    continue
                                r, g, b, a = struct.unpack("ffff", raw)
                                if (0.0 <= r <= 1.0 and 0.0 <= g <= 1.0 and 0.0 <= b <= 1.0 and
                                    0.0 <= a <= 1.0 and not (math.isnan(r) or math.isnan(g) or math.isnan(b) or math.isnan(a))):
                                    return color_addr, (r, g, b, a)
                            except Exception:
                                continue
            except Exception:
                continue
        return None, None

    # -----------------------------------------------------------------------
    # RuntimePaintableComponent helpers — texture-based paint
    # -----------------------------------------------------------------------
    def _find_runtime_paint_component(self, pawn):
        """Find RuntimePaintableComponent via GObjects scan (like the mod source).
        The mod uses FindObjects + GetOwner, NOT walking owned components."""
        # First search ALL objects globally for RuntimePaintableComponent
        for obj in self.objects.find_objects_by_class_name("RuntimePaintableComponent"):
            outer = rp(self.pm, obj + OFFSETS["UObjectBase::OuterPrivate"])
            if outer and outer == pawn:
                return obj
            # Also check if this component has the pawn as owner via Outer chain
            if outer:
                outer_cls = self.objects.class_name(outer)
                if outer_cls and "Character" in outer_cls:
                    return obj
        # Fallback: walk owned components (less reliable)
        for comp in self.walk_owned_components(pawn):
            cname = self.objects.class_name(comp)
            if cname and "RuntimePaintableComponent" in cname:
                return comp
        return 0

    def _find_texture_on_component(self, pawn):
        """By the mod source, the component stores paint textures.
        Walk ALL properties of RuntimePaintableComponent and find
        any that point to a UTexture."""
        comp = self._find_runtime_paint_component(pawn)
        if not comp:
            return 0
        cls = self.objects.obj_class(comp)
        if not cls:
            return 0
        # Walk ALL ChildProperties looking for object pointers to textures
        prop = rp(self.pm, cls + self.offsets["UStruct::ChildProperties"])
        while prop:
            try:
                off = ru32(self.pm, prop + self.offsets["FProperty::Offset_Internal"])
                if 0 < off < 0x600:
                    val = rp(self.pm, comp + off)
                    if val and val > 0x100000:
                        cname = self.objects.class_name(val)
                        if cname and "Texture" in cname:
                            return val
            except Exception:
                pass
            prop = rp(self.pm, prop + self.offsets["FField::Next"])
        return 0

    def _write_texture_flat(self, texture, r, g, b):
        """Write a uniform color to a UTexture2D mip 0 bulk data.
        Values 0.0-1.0, writes BGRA (common UE5 texture byte order)."""
        # Convert float [0,1] to byte [0,255] — BGRA order for UE5 paint textures
        b_val = max(0, min(255, int(b * 255.0)))
        g_val = max(0, min(255, int(g * 255.0)))
        r_val = max(0, min(255, int(r * 255.0)))
        for pd_off in range(0x1C0, 0x260, 8):
            try:
                pd = rp(self.pm, texture + pd_off)
                if not pd or pd < 0x100000:
                    continue
                for mips_off in (0x10, 0x18, 0x20, 0x28, 0x30, 0x38):
                    mips_data, mips_count = read_tarray_ptr(self.pm, pd + mips_off)
                    if not mips_data or mips_count != 1:
                        continue
                    mip = rp(self.pm, mips_data)
                    if not mip or mip < 0x100000:
                        continue
                    for data_off in (0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30,
                                     0x38, 0x40, 0x48, 0x50, 0x58):
                        data_ptr = rp(self.pm, mip + data_off)
                        if not data_ptr or data_ptr < 0x100000:
                            continue
                        test = self.pm.read_bytes(data_ptr, 4)
                        if len(test) < 4:
                            continue
                        for size_off in (0x08, 0x10, 0x18, 0x20):
                            try:
                                raw = self.pm.read_bytes(mip + size_off, 8)
                                if len(raw) < 8:
                                    continue
                                sz = struct.unpack("<Q", raw)[0]
                                if 256 <= sz <= 33554432:
                                    pixel_data = bytearray(sz)
                                    for i in range(0, sz, 4):
                                        pixel_data[i] = b_val
                                        pixel_data[i+1] = g_val
                                        pixel_data[i+2] = r_val
                                        pixel_data[i+3] = 255
                                    self.pm.write_bytes(data_ptr, bytes(pixel_data), sz)
                                    return True
                            except Exception:
                                continue
            except Exception:
                continue
        return False

    def _get_component_property_ptr(self, comp, prop_name):
        """Walk an object's class ChildProperties to find a named property,
        then read the pointer value at that offset on the instance."""
        cls = self.objects.obj_class(comp)
        if not cls:
            return 0
        prop = rp(self.pm, cls + self.offsets["UStruct::ChildProperties"])
        while prop:
            try:
                pname = self.objects.fnames.resolve(
                    ru32(self.pm, prop + self.offsets["FField::NamePrivate"]))
                if pname == prop_name:
                    off = ru32(self.pm, prop + self.offsets["FProperty::Offset_Internal"])
                    if off:
                        return rp(self.pm, comp + off)
            except Exception:
                pass
            prop = rp(self.pm, prop + self.offsets["FField::Next"])
        return 0

    def read_camouflage_color(self, actor):
        """Read the current color from the pawn's material."""
        try:
            mesh = self.get_skeletal_mesh(actor)
            if not mesh:
                return None
            for mat in self._get_mesh_materials(mesh):
                color_addr, orig = self._find_color_parameter(mat)
                if color_addr:
                    return (orig[0]*255, orig[1]*255, orig[2]*255)
            color_names = ["CharacterColor", "BodyColor", "CamouflageColor", "CurrentColor",
                           "SkinColor", "MeshColor", "PlayerColor", "TeamColor", "Color"]
            cls = self.objects.obj_class(actor)
            if cls:
                name, off = self.resolver.search_properties(cls, color_names)
                if name and off >= 0:
                    orig = struct.unpack("ffff", self.pm.read_bytes(actor + off, 16))
                    return (orig[0]*255, orig[1]*255, orig[2]*255)
            return None
        except Exception:
            return None

    def set_camouflage_color(self, actor, r, g, b):
        """Set camouflage color by writing directly to the paint texture.
        Falls back to material/property methods if texture not found."""
        r_lin = max(0.0, min(1.0, r / 255.0))
        g_lin = max(0.0, min(1.0, g / 255.0))
        b_lin = max(0.0, min(1.0, b / 255.0))
        col_packed = struct.pack("ffff", r_lin, g_lin, b_lin, 1.0)

        # -- Method 0: Write to DynamicMaterialInstance on component --
        try:
            comp = self._find_runtime_paint_component(actor)
            if comp:
                dyn_mat = self._get_component_property_ptr(comp, "DynamicMaterialInstance")
                if dyn_mat:
                    addr, _ = self._find_color_parameter(dyn_mat)
                    if addr:
                        self.pm.write_bytes(addr, col_packed, 16)
                        return True
        except Exception:
            pass

        # -- Method 1: Find paint texture on component and write directly --
        try:
            tex = self._find_texture_on_component(actor)
            if tex:
                if self._write_texture_flat(tex, r_lin, g_lin, b_lin):
                    return True
        except Exception:
            pass

        # -- Method 2: Mesh material vector parameters --
        try:
            mesh = self.get_skeletal_mesh(actor)
            if mesh:
                for mat in self._get_mesh_materials(mesh):
                    addr, _ = self._find_color_parameter(mat)
                    if addr:
                        self.pm.write_bytes(addr, col_packed, 16)
                        return True
        except Exception:
            pass

        # -- Method 3: Named color/tint properties on pawn/component --
        try:
            cls = self.objects.obj_class(actor)
            if cls:
                comp = self._find_runtime_paint_component(actor)
                if comp:
                    comp_cls = self.objects.obj_class(comp)
                    if comp_cls:
                        hints = ["color", "tint", "body", "skin", "paint", "base", "diffuse",
                                 "albedo", "mask", "channel", "rgb", "ambient", "emissive",
                                 "custom", "primary", "team", "character"]
                        name, off = self.resolver.search_properties(comp_cls, hints)
                        if name and off >= 0:
                            try:
                                self.pm.write_bytes(comp + off, col_packed, 16)
                                return True
                            except Exception:
                                pass
                            try:
                                col32 = struct.pack("BBBB", int(b_lin*255), int(g_lin*255), int(r_lin*255), 255)
                                self.pm.write_bytes(comp + off, col32, 4)
                                return True
                            except Exception:
                                pass
                name, off = self.resolver.search_properties(cls, hints)
                if name and off >= 0:
                    try:
                        self.pm.write_bytes(actor + off, col_packed, 16)
                        return True
                    except Exception:
                        pass
                    try:
                        col32 = struct.pack("BBBB", int(b_lin*255), int(g_lin*255), int(r_lin*255), 255)
                        self.pm.write_bytes(actor + off, col32, 4)
                        return True
                    except Exception:
                        pass
        except Exception:
            pass

        return False
