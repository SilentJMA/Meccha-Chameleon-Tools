"""C++ memory engine wrapper (meccha-core.dll) — replaces pymem for hot-path operations."""
import ctypes
import os
import sys
from ctypes import c_bool, c_uint8, c_uint16, c_uint32, c_uint64, c_float, c_double, c_int32
from ctypes import c_size_t, c_char, POINTER, byref, create_string_buffer

_me = None

def _dll_path():
    try:
        base = sys._MEIPASS
    except AttributeError:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "meccha-core.dll")

def _load():
    global _me
    if _me is not None:
        return True
    path = _dll_path()
    if not os.path.exists(path):
        return False
    try:
        _me = ctypes.CDLL(path)
    except Exception:
        return False
    _me.mc_init.restype = c_bool
    _me.mc_cleanup.restype = None
    _me.mc_is_attached.restype = c_bool
    _me.mc_pid.restype = c_uint32

    _me.mc_read.restype = c_bool
    _me.mc_read.argtypes = [c_uint64, ctypes.c_void_p, c_size_t]
    _me.mc_read_ptr.restype = c_uint64
    _me.mc_read_ptr.argtypes = [c_uint64]
    _me.mc_read_u32.restype = c_uint32
    _me.mc_read_u32.argtypes = [c_uint64]
    _me.mc_read_u16.restype = c_uint16
    _me.mc_read_u16.argtypes = [c_uint64]
    _me.mc_read_u8.restype = c_uint8
    _me.mc_read_u8.argtypes = [c_uint64]
    _me.mc_read_float.restype = c_float
    _me.mc_read_float.argtypes = [c_uint64]
    _me.mc_read_double.restype = c_double
    _me.mc_read_double.argtypes = [c_uint64]

    _me.mc_write.restype = c_bool
    _me.mc_write.argtypes = [c_uint64, ctypes.c_void_p, c_size_t]
    _me.mc_write_float.restype = c_bool
    _me.mc_write_float.argtypes = [c_uint64, c_float]
    _me.mc_write_double.restype = c_bool
    _me.mc_write_double.argtypes = [c_uint64, c_double]
    _me.mc_write_u32.restype = c_bool
    _me.mc_write_u32.argtypes = [c_uint64, c_uint32]

    _me.mc_pattern_scan.restype = c_uint64
    _me.mc_pattern_scan.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]

    _me.mc_fname_init.restype = None
    _me.mc_fname_init.argtypes = [c_uint64]
    _me.mc_fname_resolve.restype = c_uint32
    _me.mc_fname_resolve.argtypes = [c_uint32, POINTER(c_char), c_uint32]

    _me.mc_uobject_init.restype = None
    _me.mc_uobject_init.argtypes = [c_uint64, c_uint32]
    _me.mc_uobject_count.restype = c_uint32
    _me.mc_uobject_get.restype = c_uint64
    _me.mc_uobject_get.argtypes = [c_uint32]
    _me.mc_uobject_get_name.restype = c_uint32
    _me.mc_uobject_get_name.argtypes = [c_uint64, POINTER(c_char), c_uint32]
    _me.mc_uobject_class_name.restype = c_uint32
    _me.mc_uobject_class_name.argtypes = [c_uint64, POINTER(c_char), c_uint32]

    _me.mc_read_camera.restype = c_bool
    _me.mc_read_camera.argtypes = [POINTER(c_double * 3), POINTER(c_double * 3), POINTER(c_float)]
    _me.mc_read_players.restype = c_int32
    _me.mc_read_players.argtypes = [POINTER(c_uint64), c_int32]

    return True


def is_loaded():
    return _me is not None


def init():
    return _load() and _me.mc_init()


def cleanup():
    if _me:
        _me.mc_cleanup()


def attached():
    return _me and _me.mc_is_attached()


def pid():
    return _me.mc_pid() if _me else 0


def read(addr, size):
    buf = ctypes.create_string_buffer(size)
    if _me and _me.mc_read(c_uint64(addr), buf, c_size_t(size)):
        return buf.raw
    return None


def read_ptr(addr):
    return _me.mc_read_ptr(c_uint64(addr)) if _me else 0


def read_u32(addr):
    return _me.mc_read_u32(c_uint64(addr)) if _me else 0


def read_u16(addr):
    return _me.mc_read_u16(c_uint64(addr)) if _me else 0


def read_u8(addr):
    return _me.mc_read_u8(c_uint64(addr)) if _me else 0


def read_float(addr):
    return _me.mc_read_float(c_uint64(addr)) if _me else 0.0


def read_double(addr):
    return _me.mc_read_double(c_uint64(addr)) if _me else 0.0


def read_vec3(addr):
    arr = (c_double * 3)()
    if _me and _me.mc_read_vec3(c_uint64(addr), byref(arr)):
        return (arr[0], arr[1], arr[2])
    return (0, 0, 0)


def read_vec3_f(addr):
    arr = (c_float * 3)()
    if _me and _me.mc_read_vec3_f(c_uint64(addr), byref(arr)):
        return (arr[0], arr[1], arr[2])
    return (0, 0, 0)


def write_float(addr, val):
    return _me and _me.mc_write_float(c_uint64(addr), c_float(val))


def write_double(addr, val):
    return _me and _me.mc_write_double(c_uint64(addr), c_double(val))


def write_u32(addr, val):
    return _me and _me.mc_write_u32(c_uint64(addr), c_uint32(val))


def pattern_scan(module_name, pattern, mask):
    return _me.mc_pattern_scan(
        module_name.encode() if module_name else b"",
        pattern.encode(), mask.encode()
    ) if _me else 0


def fname_init(pool_addr):
    if _me:
        _me.mc_fname_init(c_uint64(pool_addr))


def fname_resolve(fname_id):
    if not _me:
        return ""
    buf = create_string_buffer(1024)
    n = _me.mc_fname_resolve(c_uint32(fname_id), buf, c_uint32(1024))
    return buf.value.decode("utf-8", errors="replace") if n else ""


def uobject_init(array_addr, count):
    if _me:
        _me.mc_uobject_init(c_uint64(array_addr), c_uint32(count))


def uobject_count():
    return _me.mc_uobject_count() if _me else 0


def uobject_get(idx):
    return _me.mc_uobject_get(c_uint32(idx)) if _me else 0


def uobject_get_name(obj):
    if not _me or not obj:
        return ""
    buf = create_string_buffer(256)
    _me.mc_uobject_get_name(c_uint64(obj), buf, c_uint32(256))
    return buf.value.decode("utf-8", errors="replace")


def uobject_class_name(obj):
    if not _me or not obj:
        return ""
    buf = create_string_buffer(256)
    _me.mc_uobject_class_name(c_uint64(obj), buf, c_uint32(256))
    return buf.value.decode("utf-8", errors="replace")


def read_camera():
    if not _me:
        return None
    loc = (c_double * 3)()
    rot = (c_double * 3)()
    fov = c_float()
    if _me.mc_read_camera(byref(loc), byref(rot), byref(fov)):
        return {
            "loc": (loc[0], loc[1], loc[2]),
            "rot": (rot[0], rot[1], rot[2]),
            "fov": fov.value,
        }
    return None


def read_players(max_count=64):
    if not _me:
        return []
    buf = (c_uint64 * max_count)()
    n = _me.mc_read_players(buf, c_int32(max_count))
    return [buf[i] for i in range(n)]
