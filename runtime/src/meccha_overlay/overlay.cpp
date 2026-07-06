#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <d2d1.h>
#include <dwrite.h>
#include <string>
#include <cstdio>
#include <cmath>
#include <vector>
#include <thread>
#include <atomic>
#pragma comment(lib, "d2d1")
#pragma comment(lib, "dwrite")
#pragma comment(lib, "ole32")

// ---------------------------------------------------------------------------
// Memory engine import (meccha-core.dll)
// ---------------------------------------------------------------------------
#pragma comment(lib, "runtime\\.build\\bin\\meccha-core.lib")
#include "../meccha_core/meccha_core.h"

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
constexpr UINT TARGET_FPS = 60;
constexpr UINT TICK_MS = 1000 / TARGET_FPS;
const wchar_t* GAME_WINDOW = L"Chameleon  ";
const wchar_t* OVERLAY_CLASS = L"MecchaOverlay";

// ---------------------------------------------------------------------------
// Direct2D globals
// ---------------------------------------------------------------------------
static ID2D1Factory*           g_d2d = nullptr;
static IDWriteFactory*         g_dwrite = nullptr;
static ID2D1HwndRenderTarget*  g_rt = nullptr;
static IDWriteTextFormat*      g_font = nullptr;
static ID2D1SolidColorBrush*   g_brush = nullptr;

static HWND  g_overlay_hwnd = nullptr;
static HWND  g_game_hwnd = nullptr;
static RECT  g_game_rect = {};

static std::atomic<bool> g_running{true};

// Colors
static D2D1_COLOR_F COLOR_DOT       = {1.0f, 0.3f, 0.3f, 1.0f};
static D2D1_COLOR_F COLOR_HEALTH    = {0.2f, 0.8f, 0.2f, 1.0f};
static D2D1_COLOR_F COLOR_SHIELD    = {0.2f, 0.4f, 0.9f, 1.0f};
static D2D1_COLOR_F COLOR_SNAP      = {0.8f, 0.2f, 0.2f, 1.0f};
static D2D1_COLOR_F COLOR_RADAR_BG  = {0.05f,0.05f,0.08f,0.7f};
static D2D1_COLOR_F COLOR_TEXT      = {0.9f, 0.9f, 0.9f, 1.0f};
static D2D1_COLOR_F COLOR_INVINCIBLE = {1.0f, 0.84f, 0.0f, 1.0f};

// ---------------------------------------------------------------------------
// Game data
// ---------------------------------------------------------------------------
struct PlayerData {
    uint64_t actor;
    double   pos[3];
    float    health;
    float    shield;
    bool     invincible;
    bool     is_local;
    bool     is_enemy;
    uint32_t role; // 0=unknown, 1=hunter, 2=survivor
    char     name[64];
};

struct CameraData {
    double loc[3];
    double rot[3];
    float  fov;
    bool   valid;
};

static std::vector<PlayerData> g_players;
static CameraData g_cam = {};

// ---------------------------------------------------------------------------
// Win32 helpers
// ---------------------------------------------------------------------------
static HWND find_game_window() {
    return FindWindowW(GAME_WINDOW, nullptr);
}

static bool get_window_rect(HWND hwnd, RECT* r) {
    return hwnd && GetWindowRect(hwnd, r);
}

// ---------------------------------------------------------------------------
// Direct2D init
// ---------------------------------------------------------------------------
static bool init_d2d(HWND hwnd) {
    if (FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED, &g_d2d)))
        return false;
    if (FAILED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED,
        __uuidof(IDWriteFactory), reinterpret_cast<IUnknown**>(&g_dwrite))))
        return false;

    RECT rc;
    GetClientRect(hwnd, &rc);
    D2D1_SIZE_U size = D2D1::SizeU(rc.right - rc.left, rc.bottom - rc.top);
    if (FAILED(g_d2d->CreateHwndRenderTarget(
        D2D1::RenderTargetProperties(D2D1_RENDER_TARGET_TYPE_HARDWARE,
            D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM, D2D1_ALPHA_MODE_PREMULTIPLIED)),
        D2D1::HwndRenderTargetProperties(hwnd, size),
        &g_rt)))
        return false;

    g_rt->CreateSolidColorBrush(D2D1::ColorF(1, 1, 1, 1), &g_brush);
    g_dwrite->CreateTextFormat(L"Consolas", nullptr,
        DWRITE_FONT_WEIGHT_NORMAL, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, 12.0f, L"en-us", &g_font);
    return true;
}

// ---------------------------------------------------------------------------
// Game data reader
// ---------------------------------------------------------------------------
static void read_game_data() {
    CameraData cam = {};
    cam.valid = mc_read_camera(cam.loc, cam.rot, &cam.fov);
    g_cam = cam;

    // Read players
    std::vector<PlayerData> players;
    uint64_t buf[64];
    int32_t n = mc_read_players(buf, 64);
    for (int32_t i = 0; i < n; i++) {
        PlayerData p = {};
        p.actor = buf[i];
        if (!mc_read_vec3_f(buf[i] + 0x128, (float*)p.pos)) // RootComponent::RelativeLocation
            continue;
        p.health = mc_player_get_health(buf[i], 0);
        p.invincible = mc_player_get_invincible(buf[i]);
        p.role = mc_player_get_role(buf[i]);
        mc_uobject_get_name(buf[i], p.name, sizeof(p.name));
        // Simple enemy detection (actor != local player via CameraManager)
        p.is_enemy = (i > 0);
        p.is_local = (i == 0);
        players.push_back(p);
    }
    g_players = players;
}

// ---------------------------------------------------------------------------
// 3D to screen projection
// ---------------------------------------------------------------------------
static bool world_to_screen(const double pos[3], const CameraData& cam,
                             UINT sw, UINT sh, float& sx, float& sy) {
    if (!cam.valid || cam.fov <= 0) return false;
    double pitch = cam.rot[0] * 3.14159265 / 180.0;
    double yaw   = cam.rot[1] * 3.14159265 / 180.0;
    double sp = sin(pitch), cp = cos(pitch);
    double sy_ = sin(yaw), cy_ = cos(yaw);
    double fwd[3] = { cp * cy_, cp * sy_, sp };
    double right[3] = { -sy_, cy_, 0 };
    double up[3] = { -sp * cy_, -sp * sy_, cp };

    double dx = pos[0] - cam.loc[0];
    double dy = pos[1] - cam.loc[1];
    double dz = pos[2] - cam.loc[2];

    double vx = dx * fwd[0] + dy * fwd[1] + dz * fwd[2];
    double vy = dx * right[0] + dy * right[1] + dz * right[2];
    double vz = dx * up[0] + dy * up[1] + dz * up[2];
    if (vx <= 0.1) return false;

    double tan_hfov = tan(cam.fov * 3.14159265 / 360.0);
    if (tan_hfov <= 0.001) return false;
    double ndc_x = vy / (vx * tan_hfov);
    double ndc_y = vz / (vx * tan_hfov / (double(sw) / double(sh)));
    if (fabs(ndc_x) > 1.5 || fabs(ndc_y) > 1.5) return false;

    sx = float((1.0 + ndc_x) * sw / 2.0);
    sy = float((1.0 - ndc_y) * sh / 2.0);
    return true;
}

// ---------------------------------------------------------------------------
// Rendering
// ---------------------------------------------------------------------------
static void draw_dot(float x, float y, float r, D2D1_COLOR_F color) {
    g_brush->SetColor(color);
    g_rt->FillEllipse(D2D1::Ellipse(D2D1::Point2F(x, y), r, r), g_brush);
}

static void draw_box(float x, float y, float w, float h, D2D1_COLOR_F color) {
    g_brush->SetColor(color);
    g_rt->DrawRectangle(D2D1::RectF(x - w/2, y - h, x + w/2, y), g_brush, 1.0f);
}

static void draw_snap_line(float sx, float sy, UINT sh, D2D1_COLOR_F color) {
    g_brush->SetColor(color);
    g_rt->DrawLine(D2D1::Point2F(sx, sy), D2D1::Point2F(sx, float(sh)), g_brush, 1.0f);
}

static void draw_text(const wchar_t* text, float x, float y, D2D1_COLOR_F color) {
    g_brush->SetColor(color);
    g_rt->DrawText(text, (UINT32)wcslen(text), g_font,
        D2D1::RectF(x, y, x + 300, y + 20), g_brush);
}

static void draw_bar(float x, float y, float w, float h, float pct, D2D1_COLOR_F color) {
    if (pct < 0) pct = 0;
    if (pct > 1) pct = 1;
    // Background
    g_brush->SetColor(D2D1::ColorF(0.1f, 0.1f, 0.1f, 0.6f));
    g_rt->FillRectangle(D2D1::RectF(x, y, x + w, y + h), g_brush);
    // Fill
    g_brush->SetColor(color);
    g_rt->FillRectangle(D2D1::RectF(x, y, x + w * pct, y + h), g_brush);
}

static void render_frame() {
    if (!g_rt || g_overlay_hwnd != GetForegroundWindow())
        return;

    RECT rc;
    GetClientRect(g_overlay_hwnd, &rc);
    UINT sw = rc.right - rc.left;
    UINT sh = rc.bottom - rc.top;
    if (sw == 0 || sh == 0) return;

    g_rt->BeginDraw();
    g_rt->Clear(D2D1::ColorF(0, 0, 0, 0));

    if (!g_players.empty() || g_cam.valid) {
        // Snap lines + dots
        for (auto& p : g_players) {
            float sx, sy;
            if (world_to_screen(p.pos, g_cam, sw, sh, sx, sy)) {
                if (!p.is_local) {
                    draw_snap_line(sx, sy, sh, p.is_enemy ? COLOR_SNAP : D2D1::ColorF(0.6f,0.6f,0.2f,1));
                    draw_dot(sx, sy, 6, p.invincible ? COLOR_INVINCIBLE : COLOR_DOT);
                }

                // Health bar
                float hx = sx - 15, hy = sy + 5;
                draw_bar(hx, hy, 30, 3, p.health / 100.0f, COLOR_HEALTH);

                // Name
                wchar_t wname[128];
                MultiByteToWideChar(CP_UTF8, 0, p.name, -1, wname, 128);
                draw_text(wname, sx - 30, hy + 5, COLOR_TEXT);
            }
        }

        // Status text
        wchar_t status[128];
        swprintf_s(status, L"Players: %zu | FOV: %.0f",
            g_players.size(), g_cam.fov);
        draw_text(status, 10, 10, COLOR_TEXT);
    } else {
        draw_text(L"Waiting for game...", float(sw)/2 - 80, float(sh)/2, COLOR_TEXT);
    }

    g_rt->EndDraw();
}

// ---------------------------------------------------------------------------
// Window procedure
// ---------------------------------------------------------------------------
static LRESULT CALLBACK wnd_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_DESTROY:
        g_running = false;
        PostQuitMessage(0);
        return 0;
    case WM_KEYDOWN:
        if (wp == VK_END) { g_running = false; DestroyWindow(hwnd); }
        break;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
int WINAPI WinMain(HINSTANCE hInst, HINSTANCE, LPSTR, int) {
    // Init memory engine
    if (!mc_init()) {
        MessageBoxA(nullptr, "Game process not found. Start MECCA CHAMELEON first.",
                    "Meccha Overlay", MB_ICONERROR);
        // Retry loop
        for (int i = 0; i < 30 && !mc_init(); i++)
            Sleep(2000);
        if (!mc_init()) return 1;
    }

    // Init memory engine subsystems
    WNDCLASSEXW wc = { sizeof(wc) };
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = wnd_proc;
    wc.hInstance = hInst;
    wc.hCursor = LoadCursor(nullptr, IDC_ARROW);
    wc.lpszClassName = OVERLAY_CLASS;
    RegisterClassExW(&wc);

    // Find game window
    for (int i = 0; i < 30; i++) {
        g_game_hwnd = find_game_window();
        if (g_game_hwnd) break;
        Sleep(1000);
    }
    if (!g_game_hwnd) return 1;
    get_window_rect(g_game_hwnd, &g_game_rect);

    // Create overlay window (layered, transparent)
    int w = g_game_rect.right - g_game_rect.left;
    int h = g_game_rect.bottom - g_game_rect.top;
    g_overlay_hwnd = CreateWindowExW(
        WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOPMOST | WS_EX_NOACTIVATE,
        OVERLAY_CLASS, L"Meccha Overlay", WS_POPUP,
        g_game_rect.left, g_game_rect.top, w, h,
        nullptr, nullptr, hInst, nullptr);
    if (!g_overlay_hwnd) return 1;

    SetLayeredWindowAttributes(g_overlay_hwnd, 0, 255, LWA_ALPHA);
    SetWindowPos(g_overlay_hwnd, HWND_TOPMOST, 0, 0, 0, 0,
                 SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);

    if (!init_d2d(g_overlay_hwnd)) return 1;

    ShowWindow(g_overlay_hwnd, SW_SHOW);

    // Main loop
    while (g_running) {
        // Poll messages
        MSG msg;
        while (PeekMessageW(&msg, nullptr, 0, 0, PM_REMOVE)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }

        // Reposition overlay to match game window
        if (get_window_rect(g_game_hwnd, &g_game_rect)) {
            SetWindowPos(g_overlay_hwnd, HWND_TOPMOST,
                g_game_rect.left, g_game_rect.top,
                g_game_rect.right - g_game_rect.left,
                g_game_rect.bottom - g_game_rect.top,
                SWP_SHOWWINDOW);
        }

        // Read game data (every frame for now)
        read_game_data();

        // Render
        render_frame();

        Sleep(TICK_MS);
    }

    // Cleanup
    if (g_font) g_font->Release();
    if (g_brush) g_brush->Release();
    if (g_rt) g_rt->Release();
    if (g_dwrite) g_dwrite->Release();
    if (g_d2d) g_d2d->Release();
    mc_cleanup();
    return 0;
}
