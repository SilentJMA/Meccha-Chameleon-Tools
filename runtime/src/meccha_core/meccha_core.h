#pragma once
#include <cstdint>
#include <windows.h>

#define MECCHA_CORE_API __declspec(dllexport)

extern "C" {

// === Process ===
MECCHA_CORE_API bool  mc_init(void);
MECCHA_CORE_API void  mc_cleanup(void);
MECCHA_CORE_API bool  mc_is_attached(void);
MECCHA_CORE_API uint32_t mc_pid(void);

// === Memory Read ===
MECCHA_CORE_API bool       mc_read(uint64_t addr, void* buf, size_t size);
MECCHA_CORE_API uint64_t   mc_read_ptr(uint64_t addr);
MECCHA_CORE_API uint32_t   mc_read_u32(uint64_t addr);
MECCHA_CORE_API uint16_t   mc_read_u16(uint64_t addr);
MECCHA_CORE_API uint8_t    mc_read_u8(uint64_t addr);
MECCHA_CORE_API float      mc_read_float(uint64_t addr);
MECCHA_CORE_API double     mc_read_double(uint64_t addr);
MECCHA_CORE_API bool       mc_read_vec3(uint64_t addr, double out[3]);
MECCHA_CORE_API bool       mc_read_vec3_f(uint64_t addr, float out[3]);
MECCHA_CORE_API bool       mc_read_quat(uint64_t addr, double out[4]);
MECCHA_CORE_API bool       mc_read_tarray(uint64_t addr, uint64_t* data_ptr, uint32_t* count);

// === Memory Write ===
MECCHA_CORE_API bool  mc_write(uint64_t addr, const void* buf, size_t size);
MECCHA_CORE_API bool  mc_write_float(uint64_t addr, float val);
MECCHA_CORE_API bool  mc_write_double(uint64_t addr, double val);
MECCHA_CORE_API bool  mc_write_u32(uint64_t addr, uint32_t val);

// === Pattern Scan ===
MECCHA_CORE_API uint64_t mc_pattern_scan(const char* module_name, const char* pattern, const char* mask);

// === FName ===
MECCHA_CORE_API void  mc_fname_init(uint64_t pool_addr);
MECCHA_CORE_API uint32_t mc_fname_resolve(uint32_t id, char* out, uint32_t out_size);

// === UObjectArray ===
MECCHA_CORE_API void  mc_uobject_init(uint64_t array_addr, uint32_t num_elements);
MECCHA_CORE_API uint32_t mc_uobject_count(void);
MECCHA_CORE_API uint64_t mc_uobject_get(uint32_t index);
MECCHA_CORE_API uint32_t mc_uobject_get_name(uint64_t obj, char* out, uint32_t out_size);
MECCHA_CORE_API uint64_t mc_uobject_get_class(uint64_t obj);
MECCHA_CORE_API uint32_t mc_uobject_class_name(uint64_t obj, char* out, uint32_t out_size);
MECCHA_CORE_API uint64_t mc_uobject_find_class(const char* name);
MECCHA_CORE_API uint64_t mc_uobject_find_first(const char* class_name);

// === Offset Resolution ===
MECCHA_CORE_API int32_t mc_resolve_offset(const char* class_name, const char* prop_name);

// === Camera ===
MECCHA_CORE_API bool mc_read_camera(double loc[3], double rot[3], float* fov);

// === Players ===
MECCHA_CORE_API int32_t mc_read_players(uint64_t* buf, int32_t max_count);
MECCHA_CORE_API uint32_t mc_player_get_role(uint64_t player_state);
MECCHA_CORE_API float mc_player_get_health(uint64_t actor, uint64_t player_state);
MECCHA_CORE_API bool mc_player_get_invincible(uint64_t actor);
MECCHA_CORE_API bool mc_player_is_visible(uint64_t actor, uint64_t camera_manager);

// === Offsets (stable) ===
enum {
    OFF_UObject_ClassPrivate = 0x10,
    OFF_UObject_NamePrivate  = 0x18,
    OFF_UObject_OuterPrivate = 0x20,
    OFF_UStruct_SuperStruct  = 0x40,
    OFF_UStruct_ChildProps   = 0x50,
    OFF_FField_Next          = 0x18,
    OFF_FField_Name          = 0x20,
    OFF_FProperty_Offset     = 0x44,
    OFF_Camera_POV           = 0x10,
    OFF_POV_Location         = 0x00,
    OFF_POV_Rotation         = 0x18,
    OFF_POV_FOV              = 0x30,
};

}
