#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d2d1.h>
#include <dwrite.h>
#include <shlwapi.h>
#include <string>
#include <vector>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <sstream>
#include <unordered_map>
#include <thread>
#include <atomic>
#pragma comment(lib, "d2d1")
#pragma comment(lib, "dwrite")
#pragma comment(lib, "ole32")
#pragma comment(lib, "shlwapi")

#pragma comment(lib, "runtime\\.build\\bin\\meccha-core.lib")
#include "../meccha_core/meccha_core.h"

// =========================== Constants ===========================
constexpr int    TARGET_FPS      = 60;
constexpr int    TICK_MS         = 1000 / TARGET_FPS;
constexpr int    DATA_UPDATE_HZ  = 20;
constexpr int    DATA_TICK_MS    = 1000 / DATA_UPDATE_HZ;
constexpr float  PI              = 3.14159265f;
const wchar_t*   GAME_WINDOW     = L"Chameleon  ";
const wchar_t*   OVERLAY_CLASS   = L"MecchaOverlay";

// =========================== D2D Globals ==========================
static ID2D1Factory*          g_d2d    = nullptr;
static IDWriteFactory*        g_dwrite = nullptr;
static ID2D1HwndRenderTarget* g_rt     = nullptr;
static IDWriteTextFormat*     g_font   = nullptr;
static IDWriteTextFormat*     g_font_small = nullptr;
static ID2D1SolidColorBrush*  g_brush  = nullptr;
static HWND  g_overlay = nullptr;
static HWND  g_game    = nullptr;
static RECT  g_rect    = {};
static std::atomic<bool> g_running{true};
static int   g_data_tick = 0;

// =========================== Config ==============================
struct ColorRGB { float r, g, b; };
struct EspConfig {
    bool  enabled          = true;
    bool  dot_esp          = true;
    bool  box_esp          = false;
    bool  corner_box       = false;
    bool  skeleton_esp     = false;
    bool  snap_lines       = true;
    bool  show_local       = true;
    bool  show_names       = true;
    bool  show_roles       = true;
    bool  show_distance    = true;
    bool  health_bar       = true;
    bool  shield_bar       = true;
    bool  team_filter      = false;
    bool  enemy_only       = false;
    bool  distance_scaling = true;
    bool  invincible_detect= true;
    bool  disable_buried   = true;
    bool  draw_all         = false;
    bool  draw_all_names   = true;
    bool  background_geo   = false;
    bool  show_cursor      = false;
    bool  radar_enabled    = false;
    bool  radar_terrain    = false;
    bool  aimbot_enabled   = false;
    bool  aimbot_show_fov  = true;
    bool  aimbot_visible_check = false;
    bool  magnet_enabled   = false;
    bool  hunter_esp       = true;
    bool  survivor_esp     = true;
    bool  hypervision_enabled = false;
    bool  hv_show_paths    = true;
    bool  hv_show_exposure = true;
    bool  hv_test_sphere   = false;
    bool  filter_hide_enemy= false;
    bool  filter_hide_self = false;
    bool  filter_hide_teammate = false;
    bool  filter_hide_unknown = false;
    int   esp_fps          = 30;
    int   dot_radius       = 8;
    float box_height_world = 100.0f;
    int   box_y_offset     = 0;
    int   line_thickness   = 1;
    int   point_size       = 2;
    float scale_ref_dist   = 1500.0f;
    float draw_all_max_dist= 3000.0f;
    int   radar_size       = 180;
    float radar_range      = 5000.0f;
    int   radar_opacity    = 160;
    int   radar_z_level    = 0;
    int   aimbot_fov       = 150;
    float aimbot_smooth    = 0.30f;
    float aimbot_target_offset = 90.0f;
    float magnet_strength  = 1.0f;
    int   magnet_fov       = 90;
    float hv_test_x=500, hv_test_y=0, hv_test_z=0;
    int   hv_path_count    = 3;
    std::string color_mode = "hybrid";
    std::string hv_quality = "high";
    std::string hv_mode    = "auto";
    std::string aimbot_key = "MB5";
    std::string magnet_hold_key = "MB4";
    ColorRGB enemy_color     = {1,0,0};
    ColorRGB teammate_color  = {1,1,0};
    ColorRGB local_color     = {0,1,0};
    ColorRGB unknown_color   = {0,0.31f,0.71f};
    ColorRGB hunter_color    = {1,0.24f,0.24f};
    ColorRGB survivor_color  = {0.24f,0.71f,1};
    ColorRGB visible_color   = {0,1,0};
    ColorRGB not_visible_color = {0.5f,0,0.5f};
    ColorRGB invincible_color  = {1,0.84f,0};
    ColorRGB radar_color    = {1,1,1};
    ColorRGB skeleton_color = {0,1,1};
    ColorRGB box_color      = {1,1,1};
};
static EspConfig g_cfg;

// =========================== JSON Config Parser ==================
static std::string json_str(const std::string& t, const std::string& k) {
    auto p = t.find("\"" + k + "\"");
    if (p == std::string::npos) return "";
    p = t.find(':', p); if (p == std::string::npos) return "";
    p = t.find_first_of("\"tf0-9[", p+1); if (p == std::string::npos) return "";
    if (t[p] == '\"') { auto e = t.find('\"', p+1); return e==std::string::npos ? "" : t.substr(p+1, e-p-1); }
    if (t[p] == '[') { auto e = t.find(']', p); return e==std::string::npos ? "" : t.substr(p, e-p+1); }
    auto e = t.find_first_of(",}\n\r", p+1); return t.substr(p, e-p);
}
static bool json_bool(const std::string& t, const std::string& k) { return json_str(t,k) == "true"; }
static int  json_int(const std::string& t, const std::string& k) { auto v = json_str(t,k); return v.empty() ? 0 : atoi(v.c_str()); }
static float json_float(const std::string& t, const std::string& k) { auto v = json_str(t,k); return v.empty() ? 0 : (float)atof(v.c_str()); }
static ColorRGB json_color(const std::string& t, const std::string& k) {
    auto v = json_str(t,k);
    if (v.empty() || v[0] != '[') return {1,1,1};
    auto n = v.substr(1, v.size()-2);
    auto c1 = n.find(','); auto c2 = n.find(',', c1+1);
    if (c1==std::string::npos||c2==std::string::npos) return {1,1,1};
    return {(float)atof(n.substr(0,c1).c_str())/255, (float)atof(n.substr(c1+1,c2-c1-1).c_str())/255, (float)atof(n.substr(c2+1).c_str())/255};
}

static void load_config() {
    wchar_t path[512]; GetEnvironmentVariableW(L"APPDATA", path, 512);
    PathAppendW(path, L"MecchaCamouflage\\esp_config.json");
    std::ifstream f(path); if (!f.is_open()) return;
    std::stringstream ss; ss << f.rdbuf(); auto t = ss.str();

    g_cfg.enabled        = json_bool(t,"enabled");
    g_cfg.dot_esp        = json_bool(t,"dot_esp");
    g_cfg.box_esp        = json_bool(t,"box_esp");
    g_cfg.corner_box     = json_bool(t,"corner_box");
    g_cfg.skeleton_esp   = json_bool(t,"skeleton_esp");
    g_cfg.snap_lines     = json_bool(t,"snap_lines");
    g_cfg.show_local     = json_bool(t,"show_local");
    g_cfg.show_names     = json_bool(t,"show_names");
    g_cfg.show_roles     = json_bool(t,"show_roles");
    g_cfg.show_distance  = json_bool(t,"show_distance");
    g_cfg.health_bar     = json_bool(t,"health_bar");
    g_cfg.shield_bar     = json_bool(t,"shield_bar");
    g_cfg.team_filter    = json_bool(t,"team_filter");
    g_cfg.enemy_only     = json_bool(t,"enemy_only");
    g_cfg.distance_scaling = json_bool(t,"distance_scaling");
    g_cfg.invincible_detect = json_bool(t,"invincible_detect");
    g_cfg.disable_buried = json_bool(t,"disable_buried");
    g_cfg.draw_all       = json_bool(t,"draw_all");
    g_cfg.draw_all_names = json_bool(t,"draw_all_names");
    g_cfg.background_geo = json_bool(t,"show_background_geo");
    g_cfg.show_cursor    = json_bool(t,"show_cursor");
    g_cfg.radar_enabled  = json_bool(t,"radar_enabled");
    g_cfg.radar_terrain  = json_bool(t,"radar_terrain");
    g_cfg.aimbot_enabled = json_bool(t,"aimbot_enabled");
    g_cfg.aimbot_show_fov= json_bool(t,"aimbot_show_fov");
    g_cfg.aimbot_visible_check = json_bool(t,"aimbot_visible_check");
    g_cfg.magnet_enabled = json_bool(t,"magnet_enabled");
    g_cfg.hunter_esp     = json_bool(t,"hunter_esp");
    g_cfg.survivor_esp   = json_bool(t,"survivor_esp");
    g_cfg.hypervision_enabled = json_bool(t,"hypervision_enabled");
    g_cfg.hv_show_paths  = json_bool(t,"hv_show_paths");
    g_cfg.hv_show_exposure = json_bool(t,"hv_show_exposure");
    g_cfg.hv_test_sphere = json_bool(t,"hv_test_sphere");
    g_cfg.filter_hide_enemy = json_bool(t,"filter_hide_enemy");
    g_cfg.filter_hide_self = json_bool(t,"filter_hide_self");
    g_cfg.filter_hide_teammate = json_bool(t,"filter_hide_teammate");
    g_cfg.filter_hide_unknown = json_bool(t,"filter_hide_unknown");
    g_cfg.color_mode     = json_str(t,"color_mode");
    g_cfg.hv_quality     = json_str(t,"hv_quality");
    g_cfg.hv_mode        = json_str(t,"hv_mode");
    g_cfg.aimbot_key     = json_str(t,"aimbot_key");
    g_cfg.magnet_hold_key = json_str(t,"magnet_hold_key");
    g_cfg.dot_radius     = json_int(t,"dot_radius");
    g_cfg.box_height_world = json_float(t,"box_height_world");
    g_cfg.box_y_offset   = json_int(t,"box_y_offset");
    g_cfg.line_thickness = json_int(t,"line_thickness");
    g_cfg.point_size     = json_int(t,"point_size");
    g_cfg.scale_ref_dist = json_float(t,"scale_reference_dist");
    g_cfg.draw_all_max_dist = json_float(t,"draw_all_max_distance");
    g_cfg.radar_size     = std::max(80, std::min(400, json_int(t,"radar_size")));
    g_cfg.radar_range    = json_float(t,"radar_range");
    g_cfg.radar_opacity  = std::max(0, std::min(255, json_int(t,"radar_opacity")));
    g_cfg.radar_z_level  = json_int(t,"radar_z_level");
    g_cfg.aimbot_fov     = json_int(t,"aimbot_fov");
    g_cfg.aimbot_smooth  = json_float(t,"aimbot_smooth");
    g_cfg.aimbot_target_offset = json_float(t,"aimbot_target_offset");
    g_cfg.magnet_strength= json_float(t,"magnet_strength");
    g_cfg.magnet_fov     = json_int(t,"magnet_fov");
    g_cfg.hv_test_x      = json_float(t,"hv_test_x");
    g_cfg.hv_test_y      = json_float(t,"hv_test_y");
    g_cfg.hv_test_z      = json_float(t,"hv_test_z");
    g_cfg.hv_path_count  = json_int(t,"hv_path_count");
    g_cfg.enemy_color    = json_color(t,"enemy_color");
    g_cfg.teammate_color = json_color(t,"teammate_color");
    g_cfg.local_color    = json_color(t,"local_color");
    g_cfg.unknown_color  = json_color(t,"unknown_color");
    g_cfg.hunter_color   = json_color(t,"hunter_visual_color");
    g_cfg.survivor_color = json_color(t,"survivor_visual_color");
    g_cfg.visible_color  = json_color(t,"visible_color");
    g_cfg.not_visible_color = json_color(t,"not_visible_color");
    g_cfg.invincible_color = json_color(t,"invincible_color");
    g_cfg.radar_color    = json_color(t,"radar_color");
    g_cfg.skeleton_color = json_color(t,"skeleton_color");
    g_cfg.box_color      = json_color(t,"box_color");
}

// =========================== D2D Init ============================
static bool init_d2d(HWND hwnd) {
    if (FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, &g_d2d))) return false;
    if (FAILED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory), (IUnknown**)&g_dwrite))) return false;
    RECT rc; GetClientRect(hwnd, &rc);
    if (FAILED(g_d2d->CreateHwndRenderTarget(
        D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_HARDWARE,
            D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED)),
        D2D1::HwndRenderTargetProperties(hwnd, D2D1::SizeU(rc.right-rc.left, rc.bottom-rc.top)), &g_rt)))
        return false;
    g_rt->CreateSolidColorBrush(D2D1::ColorF(1,1,1,1), &g_brush);
    g_dwrite->CreateTextFormat(L"Consolas", nullptr, DWRITE_FONT_WEIGHT_NORMAL,
        DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 12.0f, L"en-us", &g_font);
    g_dwrite->CreateTextFormat(L"Consolas", nullptr, DWRITE_FONT_WEIGHT_NORMAL,
        DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 10.0f, L"en-us", &g_font_small);
    return true;
}

// =========================== Game Data ===========================
struct PlayerData {
    uint64_t actor, player_state;
    double pos[3], head[3];
    float health, shield;
    bool  invincible, is_local, is_enemy, is_hunter, is_survivor, is_unknown;
    int   role; // 0=unknown 1=hunter 2=survivor
    char  name[64];
    float dist;
    bool  on_screen;
    float sx, sy; // screen position
};

struct CameraData { double loc[3], rot[3]; float fov; bool valid; };
struct ActorItem { double x,y,z; char name[64]; };
struct HVPathPt { double x,y,z; };

static std::vector<PlayerData> g_players;
static std::vector<ActorItem>  g_actors;
static CameraData g_cam = {};
static int g_status = 0; // 0=waiting, 1=attached, 2=in-game

// HV overlay data (bridgeless fallback or from C++ bridge)
static std::vector<std::vector<double>> g_hv_cloud;
static std::vector<std::vector<HVPathPt>> g_hv_paths;

static HWND find_game() { return FindWindowW(GAME_WINDOW, nullptr); }

static void read_game_data() {
    g_data_tick++;
    bool do_read = (g_data_tick % (TARGET_FPS / DATA_UPDATE_HZ) == 0);

    CameraData cam = {};
    cam.valid = mc_read_camera(cam.loc, cam.rot, &cam.fov);
    if (cam.valid) { g_cam = cam; g_status = 2; }
    else if (g_cam.valid) g_status = 1;
    else g_status = 0;

    if (!do_read) return;
    load_config();

    // Players
    std::vector<PlayerData> players;
    uint64_t buf[64];
    int32_t n = mc_read_players(buf, 64);
    for (int32_t i = 0; i < n; i++) {
        PlayerData p = {};
        p.actor = buf[i];
        float pf[3];
        if (!mc_read_vec3_f(buf[i] + 0x128, pf)) continue;
        p.pos[0]=pf[0]; p.pos[1]=pf[1]; p.pos[2]=pf[2];
        p.head[0]=pf[0]; p.head[1]=pf[1]; p.head[2]=pf[2]+80;
        p.health = mc_player_get_health(buf[i], 0);
        p.shield = mc_read_float(buf[i] + 0x140);
        p.invincible = mc_player_get_invincible(buf[i]) && g_cfg.invincible_detect;
        p.role = mc_player_get_role(buf[i]);
        p.is_hunter = (p.role == 1); p.is_survivor = (p.role == 2);
        mc_uobject_get_name(buf[i], p.name, sizeof(p.name));
        p.is_local = (i == 0); p.is_enemy = (i > 0);
        p.player_state = mc_read_ptr(buf[i] + 0x2A8);
        if (p.health < 0.01f) continue;
        p.dist = (float)sqrt(pow(p.pos[0]-g_cam.loc[0],2)+pow(p.pos[1]-g_cam.loc[1],2)+pow(p.pos[2]-g_cam.loc[2],2));
        p.is_unknown = !p.is_hunter && !p.is_survivor && !p.is_local && !p.is_enemy;
        players.push_back(p);
    }
    // Sort by distance
    std::sort(players.begin(), players.end(), [](auto& a, auto& b){ return a.dist < b.dist; });
    g_players = players;

    // Draw All: actors
    if (g_cfg.draw_all) {
        std::vector<ActorItem> actors;
        uint32_t total = mc_uobject_count();
        uint32_t scanned = 0;
        for (uint32_t i = 0; i < total && scanned < 500; i++) {
            uint64_t obj = mc_uobject_get(i);
            if (!obj) continue;
            char cn[64];
            if (mc_uobject_class_name(obj, cn, 64) == 0) continue;
            if (!strstr(cn, "Collectible") && !strstr(cn, "StaticMesh")) continue;
            if (mc_uobject_get_name(obj, cn, 64) == 0) continue;
            if (strstr(cn, "Default__")) continue;
            float pf[3];
            if (!mc_read_vec3_f(obj + 0x128, pf)) continue;
            double dx=pf[0]-g_cam.loc[0], dy=pf[1]-g_cam.loc[1], dz=pf[2]-g_cam.loc[2];
            if (sqrt(dx*dx+dy*dy+dz*dz) > g_cfg.draw_all_max_dist) continue;
            ActorItem a = {pf[0], pf[1], pf[2]};
            strncpy_s(a.name, cn, 63);
            actors.push_back(a);
            scanned++;
        }
        g_actors = actors;
    }

    // HyperVision fallback
    if (g_cfg.hypervision_enabled && g_cam.valid && !g_players.empty()) {
        // Find an enemy target
        double tx=0, ty=0, tz=0;
        bool found = false;
        if (g_cfg.hv_test_sphere) {
            tx = g_cfg.hv_test_x; ty = g_cfg.hv_test_y; tz = g_cfg.hv_test_z;
            found = true;
        } else {
            for (auto& p : g_players) {
                if (!p.is_local && p.is_enemy) {
                    tx = p.pos[0]; ty = p.pos[1]; tz = p.pos[2];
                    found = true; break;
                }
            }
        }
        if (found) {
            // Build simple exposure cloud (line of sight disk)
            g_hv_cloud.clear();
            for (int dx = -200; dx <= 200; dx += 100) {
                for (int dy = -200; dy <= 200; dy += 100) {
                    for (int dz = -100; dz <= 100; dz += 100) {
                        g_hv_cloud.push_back({tx+dx, ty+dy, tz+dz});
                    }
                }
            }
            // Build path line from player to target
            g_hv_paths.clear();
            std::vector<HVPathPt> path;
            int steps = 10;
            for (int i = 0; i <= steps; i++) {
                double t = double(i) / steps;
                path.push_back({g_cam.loc[0] + (tx-g_cam.loc[0])*t,
                                g_cam.loc[1] + (ty-g_cam.loc[1])*t,
                                g_cam.loc[2] + (tz-g_cam.loc[2])*t});
            }
            g_hv_paths.push_back(path);
        }
    }
}

// =========================== World to Screen ====================
static bool w2s(const double pos[3], const CameraData& cam, UINT sw, UINT sh, float& sx, float& sy) {
    if (!cam.valid || cam.fov <= 0) return false;
    float p = (float)(cam.rot[0]*PI/180), y = (float)(cam.rot[1]*PI/180), r = (float)(cam.rot[2]*PI/180);
    float sp=sinf(p), cp=cosf(p), sy_=sinf(y), cy_=cosf(y), sr=sinf(r), cr=cosf(r);
    double fwd[3]={cp*cy_, cp*sy_, sp};
    double rgt[3]={sr*sp*cy_-cr*sy_, sr*sp*sy_+cr*cy_, -sr*cp};
    double up[3]={-(cr*sp*cy_+sr*sy_), cy_*sr-cr*sp*sy_, cr*cp};
    double dx=pos[0]-cam.loc[0], dy=pos[1]-cam.loc[1], dz=pos[2]-cam.loc[2];
    double vx=dx*fwd[0]+dy*fwd[1]+dz*fwd[2];
    double vy=dx*rgt[0]+dy*rgt[1]+dz*rgt[2];
    double vz=dx*up[0]+dy*up[1]+dz*up[2];
    if (vx <= 0.1) return false;
    float thf = tanf(cam.fov*PI/360); if (thf <= 0.001f) return false;
    float ndc_x = float(vy/(vx*thf)), ndc_y = float(vz/(vx*thf/(float(sw)/float(sh))));
    if (fabsf(ndc_x) > 1.5f || fabsf(ndc_y) > 1.5f) return false;
    sx = (1+ndc_x)*sw/2; sy = (1-ndc_y)*sh/2;
    return true;
}

// =========================== Draw Helpers =======================
static D2D1_COLOR_F to_c(const ColorRGB& c, float a=1) { return {c.r,c.g,c.b,a}; }
static D2D1_COLOR_F to_c_rgb(int r, int g, int b, float a=1) { return {r/255.0f,g/255.0f,b/255.0f,a}; }

static float scl(float d) {
    if (!g_cfg.distance_scaling) return 1;
    return std::max(0.3f, std::min(3.0f, g_cfg.scale_ref_dist/std::max(100.0f,d)));
}

static void txt(const wchar_t* t, float x, float y, float w, float h, D2D1_COLOR_F c) {
    g_brush->SetColor(c); g_rt->DrawText(t, (UINT32)wcslen(t), g_font, D2D1::RectF(x,y,x+w,y+h), g_brush);
}
static void txt_s(const wchar_t* t, float x, float y, D2D1_COLOR_F c) { txt(t,x,y,300,20,c); }
static void txt_sm(const wchar_t* t, float x, float y, D2D1_COLOR_F c) {
    g_brush->SetColor(c); g_rt->DrawText(t, (UINT32)wcslen(t), g_font_small, D2D1::RectF(x,y,x+300,y+20), g_brush);
}

static void fc(float cx, float cy, float r, D2D1_COLOR_F c) { g_brush->SetColor(c); g_rt->FillEllipse({cx,cy,r,r},g_brush); }
static void dc(float cx, float cy, float r, D2D1_COLOR_F c, float w=1) { g_brush->SetColor(c); g_rt->DrawEllipse({cx,cy,r,r},g_brush,w); }
static void dl(float x1,float y1,float x2,float y2,D2D1_COLOR_F c,float w=1) { g_brush->SetColor(c); g_rt->DrawLine({x1,y1},{x2,y2},g_brush,w); }
static void dr(float x,float y,float w,float h,D2D1_COLOR_F c,float lw=1) { g_brush->SetColor(c); g_rt->DrawRectangle(D2D1::RectF(x-w/2,y-h,x+w/2,y+h),g_brush,lw); }

static void bar(float x, float y, float w, float h, float pct, D2D1_COLOR_F c) {
    if (pct<0)pct=0; if(pct>1)pct=1;
    g_brush->SetColor({0.1f,0.1f,0.1f,0.5f}); g_rt->FillRectangle(D2D1::RectF(x,y,x+w,y+h),g_brush);
    if (pct > 0.01f) { g_brush->SetColor(c); g_rt->FillRectangle(D2D1::RectF(x,y,x+w*pct,y+h),g_brush); }
}

// =========================== Player Colors ======================
static D2D1_COLOR_F team_col(const PlayerData& p) {
    if (p.is_local) return to_c(g_cfg.local_color);
    if (p.is_unknown) return to_c(g_cfg.unknown_color);
    if (p.is_enemy) return g_cfg.enemy_only ? to_c(g_cfg.visible_color) : to_c(g_cfg.enemy_color);
    return to_c(g_cfg.teammate_color);
}
static D2D1_COLOR_F role_col(const PlayerData& p) {
    if (p.is_hunter) return to_c(g_cfg.hunter_color);
    if (p.is_survivor) return to_c(g_cfg.survivor_color);
    return to_c(g_cfg.unknown_color);
}
static D2D1_COLOR_F final_col(const PlayerData& p) {
    auto cm = g_cfg.color_mode;
    if (cm == "role") { auto c = role_col(p); return c.a>0?c:team_col(p); }
    return team_col(p);
}

// =========================== Render - ESP ======================
static void ren_dot(float sx, float sy, float d, const PlayerData& p) {
    float r = std::max(2.0f, g_cfg.dot_radius * scl(d));
    auto team = team_col(p), role = role_col(p);
    bool hybrid = g_cfg.color_mode == "hybrid" && (p.is_hunter || p.is_survivor);
    if (p.invincible) {
        fc(sx, sy, r, to_c(g_cfg.invincible_color));
        dc(sx, sy, r, team, 2.0f);
        // Gold X
        g_brush->SetColor(to_c(g_cfg.invincible_color));
        float o = r*0.4f;
        g_rt->DrawLine({sx-o,sy-o},{sx+o,sy+o},g_brush,std::max(1.0f,r/2));
        g_rt->DrawLine({sx+o,sy-o},{sx-o,sy+o},g_brush,std::max(1.0f,r/2));
    } else if (hybrid) {
        fc(sx, sy, r-1, team);       // fill = team
        dc(sx, sy, r, role, 2.5f);   // outline = role
    } else {
        fc(sx, sy, r, team);
    }
}

static void ren_box(float sx, float sy, float d, const PlayerData& p) {
    float s = scl(d);
    float h = g_cfg.box_height_world * 500.0f / std::max(100.0f, d) * s;
    float w = h * 0.5f;
    dr(sx, sy+g_cfg.box_y_offset, w, h, to_c(g_cfg.box_color), (float)g_cfg.line_thickness);
}
static void ren_corner_box(float sx, float sy, float d, const PlayerData& p) {
    float s = scl(d);
    float h = 100.0f * 500.0f / std::max(100.0f, d) * s, w = h*0.5f, l=6;
    auto col = to_c(g_cfg.box_color); float lt = (float)g_cfg.line_thickness;
    float y = sy, xl = sx-w, xr = sx+w;
    dl(xl, y, xl+l, y, col, lt); dl(xl, y, xl, y+l, col, lt);
    dl(xr, y, xr-l, y, col, lt); dl(xr, y, xr, y+l, col, lt);
    dl(xl, y+h, xl+l, y+h, col, lt); dl(xl, y+h, xl, y+h-l, col, lt);
    dl(xr, y+h, xr-l, y+h, col, lt); dl(xr, y+h, xr, y+h-l, col, lt);
}
static void ren_skel(float sx, float sy, float d, const PlayerData& p) {
    float s = scl(d);
    float h = 70.0f * 500.0f / std::max(100.0f, d) * s, aw = h*0.4f, lw = h*0.35f;
    auto col = to_c(g_cfg.skeleton_color); float lt = (float)g_cfg.line_thickness;
    float py = sy + h, sh_y = sy + h*0.25f;
    dl(sx, sy, sx, py, col, lt);
    dl(sx-aw, sh_y, sx+aw, sh_y, col, lt);
    dl(sx-aw, sh_y, sx-aw, sh_y+h*0.15f, col, lt);
    dl(sx+aw, sh_y, sx+aw, sh_y+h*0.15f, col, lt);
    dl(sx, py, sx-lw, py+h*0.5f, col, lt);
    dl(sx, py, sx+lw, py+h*0.5f, col, lt);
}
static void ren_snap(float sx, float sy, UINT sw, UINT sh, const PlayerData& p) {
    auto team = team_col(p), role = role_col(p);
    bool hybrid = g_cfg.color_mode == "hybrid" && (p.is_hunter || p.is_survivor);
    float lt = (float)g_cfg.line_thickness;
    float x0 = sw/2.0f, y0 = (float)sh;
    float x1 = sx, y1 = sy;
    float dx = x1-x0, dy = y1-y0;
    float total = sqrtf(dx*dx+dy*dy);
    if (total < 1) return;
    if (hybrid) {
        float seg_len = 8.0f;
        int n_seg = (int)(total/seg_len);
        for (int i = 0; i < n_seg; i++) {
            float t0 = i*seg_len/total, t1 = std::min((i+1)*seg_len,total)/total;
            dl(x0+dx*t0, y0+dy*t0, x0+dx*t1, y0+dy*t1, (i%2)?role:team, lt);
        }
    } else {
        dl(x0, y0, x1, y1, team, lt);
    }
}
static D2D1_COLOR_F health_grad(float pct) {
    if (pct > 0.5f) return { (1-pct)*2, 1, 0, 1 }; // yellow→green
    return { 1, pct*2, 0, 1 }; // red→yellow
}
static void ren_hbar(float sx, float sy, float d, const PlayerData& p) {
    float s = scl(d);
    float w = 24*s, h = 4*s, x = sx - w/2;
    float y = sy - 20*s; // Above player
    bar(x, y, w, h, p.health/100.0f, health_grad(p.health/100.0f));
    if (g_cfg.shield_bar && p.shield > 0) {
        float sh = (float)(p.shield / 100.0);
        bar(x, y-h-2, w, h, std::min(1.0f,sh), {0,0.47f,1,0.86f});
    }
}
static void ren_info(float sx, float sy, float d, const PlayerData& p) {
    wchar_t buf[256];
    float r = std::max(2.0f, g_cfg.dot_radius * scl(d));
    float ox = sx + r + 4;
    float y = sy;
    std::vector<D2D1_COLOR_F> cols;
    std::vector<std::wstring> parts;

    if (g_cfg.show_names) {
        if (p.is_local) {
            parts.push_back(L"YOU");
        } else if (p.is_enemy) {
            int idx = 0; for (auto& op : g_players) { if (&op == &p) break; if (!op.is_local && op.is_enemy) idx++; }
            swprintf_s(buf, L"Enemy %d", idx+1);
            parts.push_back(buf);
        } else {
            parts.push_back(L"Teammate");
        }
        cols.push_back(role_col(p));
    }
    if (g_cfg.show_roles && (p.is_hunter||p.is_survivor)) {
        parts.push_back(p.is_hunter ? L"Hunter" : L"Survivor");
        cols.push_back(role_col(p));
    }
    if (p.invincible) {
        parts.push_back(L"[INV]");
        cols.push_back(to_c(g_cfg.invincible_color));
    }
    if (g_cfg.show_distance && !p.is_local) {
        swprintf_s(buf, L"%dm", (int)(p.dist/100));
        parts.push_back(buf);
        cols.push_back(cols.empty()?role_col(p):cols.back());
    }
    if (parts.empty()) return;

    float cx = ox;
    bool hybrid = g_cfg.color_mode=="hybrid";
    for (size_t i = 0; i < parts.size(); i++) {
        bool is_role = (g_cfg.show_roles && i == (size_t)(g_cfg.show_names?1:0));
        auto c = (hybrid && is_role) ? role_col(p) : (i==0?team_col(p):cols[i]);
        auto& s = parts[i];
        g_brush->SetColor(c);
        g_rt->DrawText(s.c_str(), (UINT32)s.size(), g_font_small, D2D1::RectF(cx,y,cx+300,y+20), g_brush);
        cx += (float)s.size() * 7.5f + 4;
        // Write separator
        if (i+1 < parts.size()) {
            g_brush->SetColor({0.5f,0.5f,0.5f,0.5f});
            g_rt->DrawText(L"|", 1, g_font_small, D2D1::RectF(cx-4,y,cx+10,y+20), g_brush);
        }
    }
}

// =========================== Render - Radar =====================
static void ren_radar(UINT sw, UINT sh) {
    if (!g_cfg.radar_enabled) return;
    int rs = g_cfg.radar_size, rx = sw - rs - 20, ry = 20;
    float cx = (float)(rx + rs/2), cy = (float)(ry + rs/2);
    float range = std::max(g_cfg.radar_range, 1000.0f), half_rs = rs/2.0f;
    float scale = (half_rs - 8.0f) / range;
    float cyaw = cosf(g_cam.rot[1]*PI/180), syaw = sinf(g_cam.rot[1]*PI/180);

    // Background + border
    g_brush->SetColor({0,0,0, g_cfg.radar_opacity/255.0f});
    g_rt->FillEllipse({cx,cy,half_rs,half_rs}, g_brush);
    dc(cx, cy, half_rs, {0.3f,0.3f,0.4f,1}, 1);

    // Crosshair lines
    dl(cx-half_rs, cy, cx+half_rs, cy, {0.3f,0.3f,0.4f,0.5f}, 1);
    dl(cx, cy-half_rs, cx, cy+half_rs, {0.3f,0.3f,0.4f,0.5f}, 1);

    // Center dot (local) - always visible
    fc(cx, cy, 2.5f, to_c(g_cfg.local_color));

    // Player dots (camera-relative rotation)
    for (auto& p : g_players) {
        if (p.is_local) continue;
        float dx = (float)(p.pos[0] - g_cam.loc[0]);
        float dz = (float)(p.pos[2] - g_cam.loc[2]);
        // Rotate by camera yaw so heading is "up"
        float rx = (dx * cyaw - dz * syaw) * scale;
        float ry_ = (dx * syaw + dz * cyaw) * scale;
        if (fabsf(rx) > half_rs-4 || fabsf(ry_) > half_rs-4) continue;
        fc(cx+rx, cy-ry_, 2.5f, team_col(p));
    }

    dc(cx, cy, half_rs, to_c(g_cfg.radar_color), 1);
}

// =========================== Render - Aimbot Assist =============
static void ren_aimbot_fov(UINT sw, UINT sh) {
    if (!g_cfg.aimbot_enabled || !g_cfg.aimbot_show_fov) return;
    float r = (float)g_cfg.aimbot_fov;
    dc((float)sw/2, (float)sh/2, r, {1,1,1,1}, 1);
}

// =========================== Render - HyperVision ===============
static void ren_hypervision(UINT sw, UINT sh) {
    if (!g_cfg.hypervision_enabled || !g_cam.valid) return;
    // Exposure cloud
    if (g_cfg.hv_show_exposure) {
        for (auto& pt : g_hv_cloud) {
            double pos[3] = {pt[0], pt[1], pt[2]};
            float sx, sy;
            if (w2s(pos, g_cam, sw, sh, sx, sy))
                fc(sx, sy, 6, {0,1,0.4f,0.15f});
        }
    }
    // Paths
    if (g_cfg.hv_show_paths) {
        for (auto& path : g_hv_paths) {
            std::vector<std::pair<float,float>> pts;
            for (auto& wp : path) {
                double pos[3] = {wp.x, wp.y, wp.z};
                float sx, sy;
                if (w2s(pos, g_cam, sw, sh, sx, sy))
                    pts.push_back({sx,sy});
            }
            for (size_t i = 0; i+1 < pts.size(); i++)
                dl(pts[i].first, pts[i].second, pts[i+1].first, pts[i+1].second, {0,1,0.2f,0.7f}, 2);
            if (!pts.empty())
                fc(pts.back().first, pts.back().second, 4, {0,1,0.2f,0.7f});
        }
    }
}

// =========================== Render - Draw All ==================
static void ren_draw_all(UINT sw, UINT sh) {
    if (!g_cfg.draw_all) return;
    int count = 0;
    for (auto& a : g_actors) {
        double pos[3] = {a.x, a.y, a.z};
        float sx, sy;
        if (!w2s(pos, g_cam, sw, sh, sx, sy)) continue;
        count++;
        fc(sx, sy, 2, {0.4f,1,0.4f,1});
        if (g_cfg.draw_all_names) {
            wchar_t wn[64]; MultiByteToWideChar(CP_UTF8,0,a.name,-1,wn,64);
            txt_sm(wn, sx+4, sy, {0.4f,1,0.4f,0.8f});
        }
    }
    if (count > 0) {
        wchar_t st[64]; swprintf_s(st, L"Items: %d", count);
        txt_s(st, (float)sw-160, 50, {0.6f,1,0.6f,1});
    }
}

// =========================== Main Render ========================
static void render_frame() {
    if (!g_rt || g_overlay != GetForegroundWindow()) return;
    RECT rc; GetClientRect(g_overlay, &rc);
    UINT sw = (UINT)(rc.right-rc.left), sh = (UINT)(rc.bottom-rc.top);
    if (sw == 0 || sh == 0) return;

    g_rt->BeginDraw();
    g_rt->Clear({0,0,0,0});

    if (g_status == 0) {
        txt_s(L"Waiting for game...", (float)sw/2-80, (float)sh/2, {0.5f,0.5f,0.5f,1});
    } else {
        // Pre-compute screen positions
        for (auto& p : g_players) {
            double aim_pos[3] = {p.pos[0], p.pos[1], p.pos[2] + g_cfg.aimbot_target_offset};
            p.on_screen = w2s(aim_pos, g_cam, sw, sh, p.sx, p.sy);
        }

        // Render each player
        for (auto& p : g_players) {
            if (!p.on_screen) continue;
            if (p.is_local && !g_cfg.show_local) continue;
            if (g_cfg.enemy_only && !p.is_enemy) continue;
            if (g_cfg.disable_buried && p.dist < 50) continue;
            if (p.is_hunter && !g_cfg.hunter_esp) continue;
            if (p.is_survivor && !g_cfg.survivor_esp) continue;
            // Filters
            if (p.is_local && g_cfg.filter_hide_self) continue;
            if (!p.is_local && p.is_enemy && g_cfg.filter_hide_enemy) continue;
            if (!p.is_local && !p.is_enemy && !p.is_unknown && g_cfg.filter_hide_teammate) continue;
            if (p.is_unknown && g_cfg.filter_hide_unknown) continue;

            float sx=p.sx, sy=p.sy;

            if (!p.is_local && g_cfg.snap_lines) ren_snap(sx, sy, sw, sh, p);
            if (g_cfg.dot_esp)    ren_dot(sx, sy, p.dist, p);
            if (g_cfg.box_esp)    ren_box(sx, sy, p.dist, p);
            if (g_cfg.corner_box) ren_corner_box(sx, sy, p.dist, p);
            if (g_cfg.skeleton_esp) ren_skel(sx, sy, p.dist, p);
            if (g_cfg.health_bar) ren_hbar(sx, sy+5, p.dist, p);
            if (g_cfg.show_names || g_cfg.show_roles) ren_info(sx, sy+10, p.dist, p);
        }

        // HyperVision
        ren_hypervision(sw, sh);

        // Draw All items
        ren_draw_all(sw, sh);

        // Aimbot FOV
        ren_aimbot_fov(sw, sh);

        // Radar
        ren_radar(sw, sh);

        // Status line
        wchar_t st[256];
        int non_local = 0;
        for (auto& p : g_players) if (!p.is_local) non_local++;
        swprintf_s(st, L"Players: %d | Attached", non_local);
        txt_s(st, 10, 20, {1,1,1,1});
    }

    // Watermark
    g_brush->SetColor({1,1,1,0.16f});
    g_rt->DrawText(L"Meccha Chameleon Tools", 22, g_font_small,
        D2D1::RectF((float)sw-165,(float)sh-13,(float)sw,(float)sh), g_brush);

    g_rt->EndDraw();
}

// =========================== Aimbot Logic =======================
static void do_aimbot() {
    if (!g_cam.valid || g_players.empty()) return;
    // Find best target
    auto pc = mc_read_ptr(mc_read_ptr(mc_read_ptr(mc_read_ptr(mc_read_ptr(0)+0x188)+0x38))+0x30);
    (void)pc; // used for ControlRotation
    // Read ControlRotation
    UINT sw = 1920, sh = 1080;
    RECT rc; if (GetClientRect(g_overlay, &rc)) { sw = rc.right-rc.left; sh = rc.bottom-rc.top; }
    float cx = sw/2.0f, cy = sh/2.0f;
    float best_dist = 1e9f;
    const PlayerData* best = nullptr;
    for (auto& p : g_players) {
        if (p.is_local || !p.is_enemy) continue;
        if (p.on_screen) {
            float d = sqrtf((p.sx-cx)*(p.sx-cx)+(p.sy-cy)*(p.sy-cy));
            int max_fov = g_cfg.magnet_enabled ? g_cfg.magnet_fov : g_cfg.aimbot_fov;
            if (d <= max_fov && d < best_dist) { best_dist = d; best = &p; }
        }
    }
    if (!best && g_cfg.aimbot_enabled) {
        // Try off-screen targeting if no on-screen target
        // (simplified - just use distance)
        for (auto& p : g_players) {
            if (p.is_local || !p.is_enemy) continue;
            if (p.dist < best_dist) { best_dist = p.dist; best = &p; }
        }
    }
    if (!best) return;

    double dx = best->pos[0] - g_cam.loc[0];
    double dy = best->pos[1] - g_cam.loc[1];
    double dz = (best->pos[2]+g_cfg.aimbot_target_offset) - g_cam.loc[2];
    double len = sqrt(dx*dx+dy*dy+dz*dz);
    if (len < 1) return;
    double aim_pitch = -asin(dz/len) * 180.0 / PI;
    double aim_yaw   = atan2(dy, dx) * 180.0 / PI;

    // Write ControlRotation - find address via known offset chain
    uint64_t world = mc_read_ptr(0) ? mc_read_ptr(0xE56860) : 0;
    if (!world) return;
    uint64_t gi = mc_read_ptr(world + 0x188);
    if (!gi) return;
    uint64_t lp_arr = mc_read_ptr(gi + 0x38);
    if (!lp_arr) return;
    uint64_t lp = mc_read_ptr(lp_arr);
    if (!lp) return;
    uint64_t pc2 = mc_read_ptr(lp + 0x30);
    if (!pc2) return;
    uint64_t cr_addr = pc2 + 0x320; // AController::ControlRotation

    float cur_pitch = mc_read_float(cr_addr);
    float cur_yaw   = mc_read_float(cr_addr+4);

    float smooth = g_cfg.aimbot_smooth;
    float new_pitch = (float)(cur_pitch + (aim_pitch - cur_pitch) * smooth);
    float new_yaw   = (float)(cur_yaw + (aim_yaw - cur_yaw) * ((g_cfg.magnet_enabled&&best_dist<200) ? g_cfg.magnet_strength : smooth));

    mc_write_float(cr_addr, new_pitch);
    mc_write_float(cr_addr+4, new_yaw);
}

// =========================== Hotkeys ============================
static void check_hotkeys() {
    if (GetAsyncKeyState(VK_END) & 0x8000) { g_running = false; DestroyWindow(g_overlay); }
    if ((GetAsyncKeyState(VK_F1) & 0x8000) || (GetAsyncKeyState(VK_INSERT) & 0x8000)) {
        // Toggle Python menu via named event
        HANDLE ev = OpenEventW(EVENT_MODIFY_STATE, FALSE, L"MecchaMenuToggle");
        if (ev) { SetEvent(ev); CloseHandle(ev); }
        // Debounce
        static DWORD last = 0;
        if (GetTickCount() - last > 200) last = GetTickCount();
        else Sleep(250);
    }
}

// =========================== Window Proc ========================
static LRESULT CALLBACK wnd_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_DESTROY: g_running = false; PostQuitMessage(0); return 0;
    case WM_KEYDOWN: if (wp == VK_END) { g_running = false; DestroyWindow(hwnd); } break;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

// =========================== Main ===============================
int WINAPI WinMain(HINSTANCE hInst, HINSTANCE, LPSTR, int) {
    for (int i = 0; i < 30; i++) { if (mc_init()) break; Sleep(2000); }
    load_config();

    WNDCLASSEXW wc = {sizeof(wc), CS_HREDRAW|CS_VREDRAW, wnd_proc};
    wc.hInstance = hInst; wc.hCursor = LoadCursor(0,IDC_ARROW);
    wc.lpszClassName = OVERLAY_CLASS;
    RegisterClassExW(&wc);

    for (int i = 0; i < 30; i++) { g_game = find_game(); if (g_game) break; Sleep(1000); }
    if (!g_game) return 1;
    GetWindowRect(g_game, &g_rect);

    int w_px = g_rect.right-g_rect.left, h_px = g_rect.bottom-g_rect.top;
    g_overlay = CreateWindowExW(
        WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_TOPMOST|WS_EX_NOACTIVATE,
        OVERLAY_CLASS, L"Meccha Overlay", WS_POPUP,
        g_rect.left, g_rect.top, w_px, h_px, 0, 0, hInst, 0);
    if (!g_overlay) return 1;
    SetLayeredWindowAttributes(g_overlay, 0, 255, LWA_ALPHA);
    SetWindowPos(g_overlay, HWND_TOPMOST, 0,0,0,0, SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW);

    if (!init_d2d(g_overlay)) return 1;
    ShowWindow(g_overlay, SW_SHOW);

    if (g_cfg.show_cursor) ShowCursor(TRUE);

    while (g_running) {
        MSG msg;
        while (PeekMessageW(&msg, 0,0,0, PM_REMOVE)) { TranslateMessage(&msg); DispatchMessageW(&msg); }

        if (GetWindowRect(g_game, &g_rect)) {
            SetWindowPos(g_overlay, HWND_TOPMOST,
                g_rect.left, g_rect.top, g_rect.right-g_rect.left, g_rect.bottom-g_rect.top, SWP_SHOWWINDOW);
        }

        read_game_data();
        render_frame();

        // Aimbot (every 3 frames to reduce writes)
        if ((g_cfg.aimbot_enabled || g_cfg.magnet_enabled) && g_data_tick % 3 == 0)
            do_aimbot();

        check_hotkeys();
        Sleep(TICK_MS);
    }

    if (g_font) g_font->Release();
    if (g_font_small) g_font_small->Release();
    if (g_brush) g_brush->Release();
    if (g_rt) g_rt->Release();
    if (g_dwrite) g_dwrite->Release();
    if (g_d2d) g_d2d->Release();
    mc_cleanup();
    return 0;
}
