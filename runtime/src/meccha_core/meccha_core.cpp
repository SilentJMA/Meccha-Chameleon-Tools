#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>
#include <psapi.h>
#pragma comment(lib, "psapi")
#pragma comment(lib, "kernel32")
#include <vector>
#include <string>
#include <unordered_map>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include "meccha_core.h"

// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
static HANDLE      g_handle  = nullptr;
static uint32_t    g_pid     = 0;
static uint64_t    g_base    = 0;
static uint64_t    g_fname_pool   = 0;
static uint64_t    g_obj_array    = 0;
static uint32_t    g_obj_count    = 0;
static HMODULE     g_module  = nullptr;

// FName block table cache
static const uint64_t* g_fname_blocks = nullptr;
static size_t          g_fname_nblocks = 0;
static uint64_t        g_fname_block_buf[1024];

// Offset cache
static std::unordered_map<std::string, int32_t> g_offset_cache;

// ---------------------------------------------------------------------------
// Process helpers
// ---------------------------------------------------------------------------
static uint32_t find_process(const char* name) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32W pe = { sizeof(pe) };
    if (Process32FirstW(snap, &pe)) {
        wchar_t wname[260];
        MultiByteToWideChar(CP_UTF8, 0, name, -1, wname, 260);
        for (auto p = wname; *p; ++p) *p = towlower(*p);
        do {
            wchar_t exe[260];
            wcscpy_s(exe, pe.szExeFile);
            for (auto p = exe; *p; ++p) *p = towlower(*p);
            if (wcscmp(exe, wname) == 0) {
                CloseHandle(snap);
                return pe.th32ProcessID;
            }
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    return 0;
}

static uint64_t module_base(HANDLE h, uint32_t pid) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    MODULEENTRY32W me = { sizeof(me) };
    uint64_t base = 0;
    if (Module32FirstW(snap, &me)) {
        if (me.modBaseAddr) base = (uint64_t)me.modBaseAddr;
    }
    CloseHandle(snap);
    return base;
}

static bool read_raw(uint64_t addr, void* buf, size_t size) {
    if (!g_handle) return false;
    SIZE_T read = 0;
    return ReadProcessMemory(g_handle, (LPCVOID)addr, buf, size, &read) && read == size;
}

// ---------------------------------------------------------------------------
// Pattern scanner
// ---------------------------------------------------------------------------
static uint64_t scan_pattern(HANDLE h, uint64_t base, uint64_t size,
                              const uint8_t* patt, const char* mask) {
    std::vector<uint8_t> buf(65536);
    for (uint64_t off = 0; off < size; off += 65536) {
        SIZE_T chunk = (size_t)min((uint64_t)buf.size(), size - off);
        SIZE_T read = 0;
        if (!ReadProcessMemory(h, (LPCVOID)(base + off), buf.data(), chunk, &read) || read == 0)
            continue;
        for (size_t i = 0; i < read; i++) {
            bool match = true;
            for (size_t j = 0; mask[j] && off + i + j < size; j++) {
                if (mask[j] == 'x' && buf[i + j] != patt[j]) { match = false; break; }
            }
            if (match) return base + off + i;
        }
    }
    return 0;
}

// ---------------------------------------------------------------------------
// FName
// ---------------------------------------------------------------------------
static const char* fname_block_ptr(uint32_t id) {
    if (!g_fname_blocks) return nullptr;
    if (id <= 1) return nullptr;
    uint32_t block_idx = id / 0x4000;
    uint32_t entry_idx = id % 0x4000;
    if (block_idx >= g_fname_nblocks || !g_fname_blocks[block_idx]) return nullptr;
    uint64_t entry_addr = g_fname_blocks[block_idx] + entry_idx * 2;
    static char buf[1024];
    uint16_t header = 0;
    if (!read_raw(entry_addr, &header, 2)) return nullptr;
    uint32_t len = header >> 1;
    if (len == 0) return nullptr;
    if (len > 1022) len = 1022;
    if (!read_raw(entry_addr + 2, buf, len)) return nullptr;
    buf[len] = 0;
    return buf;
}

static void init_fname_blocks(uint64_t pool) {
    uint64_t header = 0;
    if (!read_raw(pool, &header, 8)) return;
    uint32_t block_count = 0;
    uint64_t blocks_ptr = 0;
    uint32_t* block_u32 = (uint32_t*)&header;
    uint64_t* block_u64 = (uint64_t*)&header;
    if (block_u32[0] <= 0x40 && block_u32[1] < 0x1000) {
        blocks_ptr = pool + 8;
        block_count = block_u32[0];
    } else if (block_u64[0] < 0x1000000) {
        blocks_ptr = pool + 8;
        block_count = (uint32_t)block_u64[0];
    } else {
        blocks_ptr = block_u64[0];
        block_count = block_u32[2];
    }
    if (block_count > 1024) block_count = 1024;
    memset(g_fname_block_buf, 0, sizeof(g_fname_block_buf));
    for (uint32_t i = 0; i < block_count; i++) {
        read_raw(blocks_ptr + i * 8, &g_fname_block_buf[i], 8);
    }
    g_fname_blocks = g_fname_block_buf;
    g_fname_nblocks = block_count;
}

// ---------------------------------------------------------------------------
// UObjectArray
// ---------------------------------------------------------------------------
static uint64_t obj_from_index(uint32_t idx) {
    if (idx >= g_obj_count || !g_obj_array) return 0;
    uint32_t chunk_idx = idx / 65536;
    uint32_t slot_idx   = idx % 65536;
    uint64_t chunks = 0;
    if (!read_raw(g_obj_array, &chunks, 8)) return 0;
    if (!chunks) return 0;
    uint64_t chunk = 0;
    if (!read_raw(chunks + chunk_idx * 8, &chunk, 8)) return 0;
    if (!chunk) return 0;
    uint64_t obj = 0;
    if (!read_raw(chunk + slot_idx * 8, &obj, 8)) return 0;
    return obj;
}

// ---------------------------------------------------------------------------
// API: Process
// ---------------------------------------------------------------------------
bool mc_init() {
    const char* names[] = {
        "PenguinHotel-Win64-Shipping.exe",
        "PenguinHotel-Win64-Shipping",
        nullptr
    };
    for (int i = 0; names[i]; i++) {
        g_pid = find_process(names[i]);
        if (g_pid) break;
    }
    if (!g_pid) return false;
    g_handle = OpenProcess(PROCESS_ALL_ACCESS, FALSE, g_pid);
    if (!g_handle) return false;
    g_base = module_base(g_handle, g_pid);
    return g_base != 0;
}

void mc_cleanup() {
    if (g_handle) { CloseHandle(g_handle); g_handle = nullptr; }
    g_pid = 0; g_base = 0; g_fname_pool = 0;
    g_obj_array = 0; g_obj_count = 0; g_fname_blocks = nullptr;
    g_offset_cache.clear();
    if (g_module) { FreeLibrary(g_module); g_module = nullptr; }
}

bool mc_is_attached() { return g_handle != nullptr; }
uint32_t mc_pid() { return g_pid; }

// ---------------------------------------------------------------------------
// API: Memory Read
// ---------------------------------------------------------------------------
bool mc_read(uint64_t addr, void* buf, size_t size) {
    return read_raw(addr, buf, size);
}

uint64_t mc_read_ptr(uint64_t addr) {
    uint64_t v = 0; read_raw(addr, &v, 8); return v;
}

uint32_t mc_read_u32(uint64_t addr) {
    uint32_t v = 0; read_raw(addr, &v, 4); return v;
}

uint16_t mc_read_u16(uint64_t addr) {
    uint16_t v = 0; read_raw(addr, &v, 2); return v;
}

uint8_t mc_read_u8(uint64_t addr) {
    uint8_t v = 0; read_raw(addr, &v, 1); return v;
}

float mc_read_float(uint64_t addr) {
    float v = 0; read_raw(addr, &v, 4); return v;
}

double mc_read_double(uint64_t addr) {
    double v = 0; read_raw(addr, &v, 8); return v;
}

bool mc_read_vec3(uint64_t addr, double out[3]) {
    return read_raw(addr, out, 24);
}

bool mc_read_vec3_f(uint64_t addr, float out[3]) {
    return read_raw(addr, out, 12);
}

bool mc_read_quat(uint64_t addr, double out[4]) {
    return read_raw(addr, out, 32);
}

bool mc_read_tarray(uint64_t addr, uint64_t* data_ptr, uint32_t* count) {
    uint64_t d = 0; uint32_t c = 0, m = 0;
    if (!read_raw(addr, &d, 8)) return false;
    if (!read_raw(addr + 8, &c, 4)) return false;
    if (!read_raw(addr + 12, &m, 4)) return false;
    *data_ptr = d; *count = c; return true;
}

// ---------------------------------------------------------------------------
// API: Memory Write
// ---------------------------------------------------------------------------
bool mc_write(uint64_t addr, const void* buf, size_t size) {
    if (!g_handle) return false;
    SIZE_T written = 0;
    return WriteProcessMemory(g_handle, (LPVOID)addr, buf, size, &written) && written == size;
}

bool mc_write_float(uint64_t addr, float val) { return mc_write(addr, &val, 4); }
bool mc_write_double(uint64_t addr, double val) { return mc_write(addr, &val, 8); }
bool mc_write_u32(uint64_t addr, uint32_t val) { return mc_write(addr, &val, 4); }

// ---------------------------------------------------------------------------
// API: Pattern Scan
// ---------------------------------------------------------------------------
uint64_t mc_pattern_scan(const char* module_name, const char* pattern, const char* mask) {
    HMODULE mod = GetModuleHandleA(module_name);
    if (!mod) {
        wchar_t wname[260];
        MultiByteToWideChar(CP_UTF8, 0, module_name, -1, wname, 260);
        mod = GetModuleHandleW(wname);
        if (!mod) {
            // Try to find it in the process
            HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, g_pid);
            if (snap != INVALID_HANDLE_VALUE) {
                MODULEENTRY32W me = { sizeof(me) };
                if (Module32FirstW(snap, &me)) {
                    do {
                        wchar_t mname[260];
                        wcscpy_s(mname, me.szModule);
                        for (auto p = mname; *p; ++p) *p = towlower(*p);
                        wchar_t wneed[260];
                        MultiByteToWideChar(CP_UTF8, 0, module_name, -1, wneed, 260);
                        for (auto p = wneed; *p; ++p) *p = towlower(*p);
                        if (wcscmp(mname, wneed) == 0) {
                            mod = (HMODULE)me.modBaseAddr;
                            break;
                        }
                    } while (Module32NextW(snap, &me));
                }
                CloseHandle(snap);
            }
        }
    }
    if (!mod) {
        mod = (HMODULE)g_base;
    }

    MODULEINFO mi = {};
    if (mod && mod != (HMODULE)g_base) {
        GetModuleInformation(GetCurrentProcess(), mod, &mi, sizeof(mi));
    }
    uint64_t base = (uint64_t)mod;
    uint64_t size = 0;
    if (mod == (HMODULE)g_base) {
        // We need the .text section size. Use NT headers
        IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)g_base;
        if (dos->e_magic == IMAGE_DOS_SIGNATURE) {
            IMAGE_NT_HEADERS64* nt = (IMAGE_NT_HEADERS64*)(g_base + dos->e_lfanew);
            size = nt->OptionalHeader.SizeOfImage;
        }
    } else {
        size = mi.SizeOfImage;
    }

    if (!size) {
        MEMORY_BASIC_INFORMATION mbi = {};
        if (VirtualQueryEx(g_handle, (LPCVOID)base, &mbi, sizeof(mbi))) {
            size = mbi.RegionSize;
        }
    }

    size_t patt_len = strlen(mask);
    std::vector<uint8_t> patt_bytes(patt_len);
    for (size_t i = 0; i < patt_len; i++)
        patt_bytes[i] = (uint8_t)pattern[i];

    return scan_pattern(g_handle, base, size, patt_bytes.data(), mask);
}

// ---------------------------------------------------------------------------
// API: FName
// ---------------------------------------------------------------------------
void mc_fname_init(uint64_t pool_addr) {
    g_fname_pool = pool_addr;
    init_fname_blocks(pool_addr);
}

uint32_t mc_fname_resolve(uint32_t id, char* out, uint32_t out_size) {
    if (!out || out_size == 0) return 0;
    if (id <= 1) { out[0] = 0; return 0; }
    uint32_t block_idx = id / 0x4000;
    uint32_t entry_idx = id % 0x4000;
    if (block_idx >= g_fname_nblocks || !g_fname_blocks[block_idx]) { out[0] = 0; return 0; }
    uint64_t entry_addr = g_fname_blocks[block_idx] + (uint64_t)entry_idx * 2;
    uint16_t header = 0;
    if (!read_raw(entry_addr, &header, 2)) { out[0] = 0; return 0; }
    uint32_t len = header >> 1;
    if (len == 0 && (header & 1)) {
        // Wide string stored at the end of the block
        uint64_t wide_ptr = g_fname_blocks[block_idx + 1];
        if (!wide_ptr) { out[0] = 0; return 0; }
        uint32_t wide_id = id - block_idx * 0x4000;
        // Read wide char
        wchar_t wc = 0;
        if (!read_raw(wide_ptr + wide_id * 2, &wc, 2)) { out[0] = 0; return 0; }
        len = 1;
        char c = (char)wc;
        if (len >= out_size) len = out_size - 1;
        out[0] = c; out[1] = 0;
        return 1;
    }
    if (len == 0) { out[0] = 0; return 0; }
    if (len > 4096) len = 4096;
    if (len >= out_size) len = out_size - 1;
    if (!read_raw(entry_addr + 2, out, len)) { out[0] = 0; return 0; }
    out[len] = 0;
    return len;
}

// ---------------------------------------------------------------------------
// API: UObjectArray
// ---------------------------------------------------------------------------
void mc_uobject_init(uint64_t array_addr, uint32_t num_elements) {
    g_obj_array = array_addr; g_obj_count = num_elements;
}

uint32_t mc_uobject_count() { return g_obj_count; }

uint64_t mc_uobject_get(uint32_t index) {
    return obj_from_index(index);
}

uint32_t mc_uobject_get_name(uint64_t obj, char* out, uint32_t out_size) {
    if (!obj || !out || out_size == 0) return 0;
    uint64_t name_ptr = mc_read_ptr(obj + OFF_UObject_NamePrivate);
    if (!name_ptr) { out[0] = 0; return 0; }
    uint32_t id = mc_read_u32(name_ptr);
    if (id == 0) { out[0] = 0; return 0; }
    return mc_fname_resolve(id, out, out_size);
}

uint64_t mc_uobject_get_class(uint64_t obj) {
    return mc_read_ptr(obj + OFF_UObject_ClassPrivate);
}

uint32_t mc_uobject_class_name(uint64_t obj, char* out, uint32_t out_size) {
    uint64_t cls = mc_uobject_get_class(obj);
    if (!cls) { out[0] = 0; return 0; }
    return mc_uobject_get_name(cls, out, out_size);
}

uint64_t mc_uobject_find_class(const char* name) {
    for (uint32_t i = 0; i < g_obj_count; i++) {
        uint64_t obj = obj_from_index(i);
        if (!obj) continue;
        char buf[256];
        if (mc_uobject_get_name(obj, buf, sizeof(buf)) > 0 && strcmp(buf, name) == 0)
            return obj;
    }
    return 0;
}

uint64_t mc_uobject_find_first(const char* class_name) {
    for (uint32_t i = 0; i < g_obj_count; i++) {
        uint64_t obj = obj_from_index(i);
        if (!obj) continue;
        char buf[256];
        if (mc_uobject_class_name(obj, buf, sizeof(buf)) > 0 && strcmp(buf, class_name) == 0)
            return obj;
    }
    return 0;
}

// ---------------------------------------------------------------------------
// API: Offset Resolution (simplified - walks ChildProperties chain)
// ---------------------------------------------------------------------------
int32_t mc_resolve_offset(const char* class_name, const char* prop_name) {
    std::string key = std::string(class_name) + "::" + prop_name;
    auto it = g_offset_cache.find(key);
    if (it != g_offset_cache.end()) return it->second;

    uint64_t cls = mc_uobject_find_class(class_name);
    if (!cls) { g_offset_cache[key] = -1; return -1; }

    // Walk SuperStruct chain
    uint64_t cur = cls;
    for (int depth = 0; depth < 32; depth++) {
        uint64_t child = mc_read_ptr(cur + OFF_UStruct_ChildProps);
        while (child) {
            char buf[256];
            uint32_t fname_id = mc_read_u32(child + OFF_FField_Name);
            if (mc_fname_resolve(fname_id, buf, sizeof(buf)) > 0 && strcmp(buf, prop_name) == 0) {
                int32_t off = (int32_t)mc_read_u32(child + OFF_FProperty_Offset);
                g_offset_cache[key] = off;
                return off;
            }
            child = mc_read_ptr(child + OFF_FField_Next);
        }
        cur = mc_read_ptr(cur + OFF_UStruct_SuperStruct);
        if (!cur) break;
    }

    g_offset_cache[key] = -1;
    return -1;
}

// ---------------------------------------------------------------------------
// API: Camera
// ---------------------------------------------------------------------------
bool mc_read_camera(double loc[3], double rot[3], float* fov) {
    uint64_t world = mc_read_ptr(g_base + 0xE56860); // GWorld offset
    if (!world) return false;
    uint64_t owning_level = mc_read_ptr(world + 0x38);
    if (!owning_level) return false;
    uint64_t actors = mc_read_ptr(owning_level + 0x98);
    if (!actors) return false;
    uint32_t actor_count = mc_read_u32(owning_level + 0xA0);
    if (actor_count == 0) return false;
    // Find local player via GameInstance
    uint64_t game_instance = mc_read_ptr(world + 0x188);
    if (!game_instance) return false;
    uint64_t local_players = mc_read_ptr(game_instance + 0x38);
    if (!local_players) return false;
    uint64_t local_player = mc_read_ptr(local_players);
    if (!local_player) return false;
    uint64_t controller = mc_read_ptr(local_player + 0x30);
    if (!controller) return false;
    uint64_t camera_manager = mc_read_ptr(controller + 0x478);
    if (!camera_manager) return false;
    uint64_t camera_cache = mc_read_ptr(camera_manager + 0x1F0 + 0x10);
    if (!camera_cache) camera_cache = camera_manager + 0x1F0;
    uint64_t pov = camera_cache + OFF_Camera_POV;
    if (!read_raw(pov + OFF_POV_Location, loc, 24)) return false;
    if (!read_raw(pov + OFF_POV_Rotation, rot, 24)) return false;
    *fov = mc_read_float(pov + OFF_POV_FOV);
    return true;
}

// ---------------------------------------------------------------------------
// Player / role detection stubs (delegated to Python for now)
// ---------------------------------------------------------------------------
int32_t mc_read_players(uint64_t* buf, int32_t max_count) {
    // Simplified: basic player enumeration
    int32_t count = 0;
    uint64_t world = mc_read_ptr(g_base + 0xE56860);
    if (!world) return 0;
    uint64_t level = mc_read_ptr(world + 0x38);
    if (!level) return 0;
    uint64_t actors = mc_read_ptr(level + 0x98);
    if (!actors) return 0;
    uint32_t total = mc_read_u32(level + 0xA0);
    if (total > 1000) total = 1000;
    for (uint32_t i = 0; i < total && count < max_count; i++) {
        uint64_t actor = mc_read_ptr(actors + (uint64_t)i * 8);
        if (!actor) continue;
        // Check if it's a player (has PlayerState)
        uint64_t state = mc_read_ptr(actor + 0x2A8);
        if (state && mc_read_ptr(state + 0x10)) {
            buf[count++] = actor;
        }
    }
    return count;
}

uint32_t mc_player_get_role(uint64_t player_state) {
    char name[256];
    if (!player_state) return 0;
    uint64_t cls = mc_uobject_get_class(player_state);
    if (!cls) return 0;
    mc_uobject_get_name(cls, name, sizeof(name));
    if (strstr(name, "Hunter") || strstr(name, "hunter")) return 1;
    if (strstr(name, "Survivor") || strstr(name, "survivor")) return 2;
    return 0;
}

float mc_player_get_health(uint64_t actor, uint64_t player_state) {
    if (!actor) return 0;
    float health = mc_read_float(actor + 0x138);
    if (health <= 0 || health > 99999) health = mc_read_float(actor + 0x140);
    return health;
}

bool mc_player_get_invincible(uint64_t actor) {
    if (!actor) return false;
    uint32_t flags1 = mc_read_u32(actor + 0x174);
    uint32_t flags2 = mc_read_u32(actor + 0x1D8);
    return (flags1 & 0x2) || (flags2 & 0x4);
}

bool mc_player_is_visible(uint64_t actor, uint64_t camera_manager) {
    (void)actor; (void)camera_manager;
    return true; // Stub - proper LineTrace would require bridge
}
