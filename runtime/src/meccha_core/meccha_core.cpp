#define WIN32_LEAN_AND_MEAN
#include <windows.h>

BOOL APIENTRY DllMain(HMODULE, DWORD, LPVOID) { return TRUE; }
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

// Engine globals (resolved at init)
static uint64_t g_gengine = 0;
static int32_t  off_GameViewport = -1;
static int32_t  off_World = -1;
static int32_t  off_OwningGameInstance = -1;
static int32_t  off_LocalPlayers = -1;
static int32_t  off_PlayerController = -1;
static int32_t  off_PlayerCameraManager = -1;
static int32_t  off_CameraCachePrivate = -1;
static int32_t  off_ActorRootComponent = -1;
static int32_t  off_RelativeLocation = -1;

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
// Engine init (matches Python MecchaESP.__init__)
// ---------------------------------------------------------------------------
static int scan_guobject_array() {
    const uint8_t sig[] = {0x48,0x8D,0x05,0x00,0x00,0x00,0x00,0x48,0x89,0x01,0x45,0x8B,0xD1};
    const char mask[] = "xxx????xxxxxx";
    const char* mod = "PenguinHotel-Win64-Shipping.exe";
    uint64_t addr = mc_pattern_scan(mod, (const char*)sig, mask);
    if (!addr) return -1;
    int32_t rel = 0;
    if (!read_raw(addr + 3, &rel, 4)) return -1;
    uint64_t obj_array = addr + 7 + rel;
    // Verify: read element count
    uint32_t num = mc_read_u32(obj_array + 0x14 + 0x10); // obj_array + 0x24 (offset to NumElements)
    if (num == 0 || num > 10000000) return -1;
    mc_uobject_init(obj_array, num);
    return 0;
}

static int scan_fname_pool(uint64_t guobject_addr) {
    // Try delta from GUObjectArray first
    uint64_t delta = guobject_addr - 0xE3B40;
    mc_fname_init(delta);
    char buf[256];
    bool ok = mc_fname_resolve(0, buf, 256) > 0 && strcmp(buf, "None") == 0;
    if (ok) return 0;

    // Try pattern scan
    const char* patterns[] = {
        "48 8D 0D ?? ?? ?? ?? E8 ?? ?? ?? ?? 48 8B 0D ?? ?? ?? ?? 48 8D 15 ?? ?? ?? ?? 48 8B 01 FF 50 68",
        "48 8D 3D ?? ?? ?? ?? 48 85 FF 74 0C",
        "48 8D 35 ?? ?? ?? ?? 8B D6 48 8D 0D",
        "48 8D 05 ?? ?? ?? ?? 48 89 44 24 ?? 48 8D 0D",
    };
    const char* masks[] = {
        "xxx????x????xxx????xxx????xxxxxxxx",
        "xxx????xxxxxx",
        "xxx????xxxxxxx?xxx??",
        "xxx????xxxxxxx????",
    };
    const char* mod = "PenguinHotel-Win64-Shipping.exe";
    for (int i = 0; i < 4; i++) {
        std::string sig_str;
        const char* p = patterns[i];
        while (*p) { if (*p != ' ') sig_str += *p; p++; }
        uint64_t addr = mc_pattern_scan(mod, sig_str.c_str(), masks[i]);
        if (!addr) continue;
        int32_t rel = 0;
        if (!read_raw(addr + 3, &rel, 4)) continue;
        uint64_t pool = addr + 7 + rel;
        mc_fname_init(pool);
        char b[256];
        if (mc_fname_resolve(0, b, 256) > 0 && strcmp(b, "None") == 0) return 0;
    }
    return -1;
}

int mc_init_engine(void) {
    // Step 1: Scan GUObjectArray
    if (scan_guobject_array() != 0) return -1;
    // Step 2: Scan FNamePool
    if (scan_fname_pool(g_obj_array) != 0) return -2;

    // Step 3: Find GEngine instance via UObjectArray
    g_gengine = 0;
    for (uint32_t i = 0; i < g_obj_count; i++) {
        uint64_t obj = obj_from_index(i);
        if (!obj) continue;
        char cn[64];
        if (mc_uobject_class_name(obj, cn, 64) > 0 && strcmp(cn, "GameEngine") == 0) {
            g_gengine = obj;
            break;
        }
    }
    if (!g_gengine) return -3;

    // Step 4: Resolve critical offsets (same as Python OFFSET_MAP)
    auto ro = [](const char* cls, const char* prop) -> int32_t {
        return mc_resolve_offset(cls, prop);
    };
    off_GameViewport       = ro("GameEngine", "GameViewport");
    off_World              = ro("GameViewportClient", "World");
    off_OwningGameInstance = ro("World", "OwningGameInstance");
    off_LocalPlayers       = ro("GameInstance", "LocalPlayers");
    off_PlayerController   = ro("Player", "PlayerController");
    off_PlayerCameraManager= ro("PlayerController", "PlayerCameraManager");
    off_CameraCachePrivate = ro("PlayerCameraManager", "CameraCachePrivate");
    off_ActorRootComponent = ro("Actor", "RootComponent");
    off_RelativeLocation   = ro("SceneComponent", "RelativeLocation");

    return 0;
}

uint64_t mc_get_engine(void) { return g_gengine; }

uint64_t mc_get_world(void) {
    if (!g_gengine || off_GameViewport < 0 || off_World < 0) return 0;
    uint64_t vp = mc_read_ptr(g_gengine + off_GameViewport);
    if (!vp) return 0;
    return mc_read_ptr(vp + off_World);
}

int32_t mc_get_offset(const char* key) {
    if (strcmp(key, "GameViewport") == 0) return off_GameViewport;
    if (strcmp(key, "World") == 0) return off_World;
    if (strcmp(key, "OwningGameInstance") == 0) return off_OwningGameInstance;
    if (strcmp(key, "LocalPlayers") == 0) return off_LocalPlayers;
    if (strcmp(key, "PlayerController") == 0) return off_PlayerController;
    if (strcmp(key, "PlayerCameraManager") == 0) return off_PlayerCameraManager;
    if (strcmp(key, "CameraCachePrivate") == 0) return off_CameraCachePrivate;
    if (strcmp(key, "RootComponent") == 0) return off_ActorRootComponent;
    if (strcmp(key, "RelativeLocation") == 0) return off_RelativeLocation;
    return -1;
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
        // Read PE headers via ReadProcessMemory (not local dereference!)
        uint8_t header_buf[4096];
        if (read_raw(base, header_buf, sizeof(header_buf))) {
            IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)header_buf;
            if (dos->e_magic == IMAGE_DOS_SIGNATURE) {
                IMAGE_NT_HEADERS64* nt = (IMAGE_NT_HEADERS64*)(header_buf + dos->e_lfanew);
                size = nt->OptionalHeader.SizeOfImage;
            }
        }
        if (!size) {
            MEMORY_BASIC_INFORMATION mbi = {};
            if (VirtualQueryEx(g_handle, (LPCVOID)base, &mbi, sizeof(mbi))) {
                size = mbi.RegionSize;
            }
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
    // FName is stored inline at UObject+0x18: int32 ComparisonIndex + int32 Number
    uint32_t id = mc_read_u32(obj + OFF_UObject_NamePrivate);
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
// API: Camera (uses dynamic offsets from mc_init_engine)
// ---------------------------------------------------------------------------
bool mc_read_camera(double loc[3], double rot[3], float* fov) {
    uint64_t world = mc_get_world();
    if (!world) return false;
    if (off_OwningGameInstance < 0 || off_LocalPlayers < 0) return false;
    uint64_t gi = mc_read_ptr(world + off_OwningGameInstance);
    if (!gi) return false;
    uint64_t lp_data = mc_read_ptr(gi + off_LocalPlayers);
    if (!lp_data) return false;
    uint64_t lp = mc_read_ptr(lp_data);
    if (!lp) return false;
    if (off_PlayerController < 0) return false;
    uint64_t pc = mc_read_ptr(lp + off_PlayerController);
    if (!pc) return false;
    if (off_PlayerCameraManager < 0) return false;
    uint64_t cm = mc_read_ptr(pc + off_PlayerCameraManager);
    if (!cm) return false;
    // CameraCachePrivate: try pointer-based first, then direct offset
    uint64_t cc = 0;
    if (off_CameraCachePrivate >= 0) {
        cc = mc_read_ptr(cm + off_CameraCachePrivate + 0x10);
        if (!cc) cc = cm + off_CameraCachePrivate;
    } else {
        return false;
    }
    uint64_t pov = cc + OFF_Camera_POV;
    if (!read_raw(pov + OFF_POV_Location, loc, 24)) return false;
    if (!read_raw(pov + OFF_POV_Rotation, rot, 24)) return false;
    *fov = mc_read_float(pov + OFF_POV_FOV);
    return true;
}

// ---------------------------------------------------------------------------
// API: Players (via GameState->PlayerArray, matching Python)
// ---------------------------------------------------------------------------
int32_t mc_read_players(uint64_t* buf, int32_t max_count) {
    int32_t count = 0;
    uint64_t world = mc_get_world();
    if (!world) return 0;
    // Get GameState from world
    int32_t off_GameState = mc_resolve_offset("World", "GameState");
    if (off_GameState < 0) return 0;
    uint64_t gs = mc_read_ptr(world + off_GameState);
    if (!gs) return 0;
    // Get PlayerArray from GameState
    int32_t off_PlayerArray = mc_resolve_offset("GameStateBase", "PlayerArray");
    if (off_PlayerArray < 0) return 0;
    uint64_t pa_data = 0; uint32_t pa_count = 0;
    if (!mc_read_tarray(gs + off_PlayerArray, &pa_data, &pa_count)) return 0;
    if (pa_count > max_count) pa_count = (uint32_t)max_count;
    // Get PawnPrivate from each PlayerState
    int32_t off_PawnPrivate = mc_resolve_offset("PlayerState", "PawnPrivate");
    int32_t off_PlayerState = mc_resolve_offset("Controller", "PlayerState");
    int32_t off_AcknowledgedPawn = mc_resolve_offset("PlayerController", "AcknowledgedPawn");
    for (uint32_t i = 0; i < pa_count; i++) {
        uint64_t ps = mc_read_ptr(pa_data + (uint64_t)i * 8);
        if (!ps) continue;
        uint64_t actor = 0;
        if (off_PawnPrivate >= 0) actor = mc_read_ptr(ps + off_PawnPrivate);
        if (!actor && off_AcknowledgedPawn >= 0) {
            // Fallback: find controller via PlayerState, then AcknowledgedPawn
            for (uint32_t j = 0; j < g_obj_count && !actor; j++) {
                uint64_t obj = obj_from_index(j);
                if (!obj) continue;
                if (off_PlayerState < 0) break;
                uint64_t pstate = mc_read_ptr(obj + off_PlayerState);
                if (pstate == ps) { actor = mc_read_ptr(obj + off_AcknowledgedPawn); }
            }
        }
        if (actor) buf[count++] = actor;
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
