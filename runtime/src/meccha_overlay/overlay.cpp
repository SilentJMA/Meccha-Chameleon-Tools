#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
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
#include <algorithm>
#pragma comment(lib, "shlwapi")
#pragma comment(lib, "gdi32")
#pragma comment(lib, "user32")

#pragma comment(lib, "runtime\\.build\\bin\\meccha-core.lib")
#include "../meccha_core/meccha_core.h"

// ======================== Constants ==========================
constexpr int TARGET_FPS = 60;
constexpr int TICK_MS = 1000 / TARGET_FPS;
constexpr float PI = 3.14159265f;
const wchar_t* GAME_TITLE = L"Chameleon  ";
const wchar_t* WND_CLASS = L"MecchaOverlay";

// ======================== Globals ============================
static HWND g_wnd = nullptr, g_game = nullptr;
static RECT g_rect = {};
static std::atomic<bool> g_running{true};
static int g_data_tick = 0;

// ======================== Config =============================
struct Color3 { int r, g, b; };
struct EspConfig {
    bool enabled=true, dot_esp=true, box_esp=false, corner_box=false, skeleton_esp=false;
    bool snap_lines=true, show_local=true, show_names=true, show_roles=true, show_distance=true;
    bool health_bar=true, shield_bar=true, enemy_only=false, distance_scaling=true;
    bool invincible_detect=true, disable_buried=true, draw_all=false, draw_all_names=true;
    bool background_geo=false, show_cursor=false, radar_enabled=false, aimbot_enabled=false;
    bool aimbot_show_fov=true, magnet_enabled=false, hunter_esp=true, survivor_esp=true;
    bool hypervision_enabled=false, hv_show_paths=true, hv_show_exposure=true, hv_test_sphere=false;
    bool filter_hide_enemy=false, filter_hide_self=false, filter_hide_teammate=false, filter_hide_unknown=false;
    int dot_radius=8, line_thickness=1, radar_size=180, radar_opacity=160, aimbot_fov=150, magnet_fov=90;
    float box_height_world=100, scale_ref_dist=1500, draw_all_max_dist=3000, radar_range=5000;
    float aimbot_smooth=0.3f, aimbot_target_offset=90, magnet_strength=1;
    int box_y_offset=0, point_size=2;
    float hv_test_x=500, hv_test_y=0, hv_test_z=0;
    Color3 enemy_color={255,0,0}, teammate_color={255,255,0}, local_color={0,255,0}, unknown_color={0,80,180};
    Color3 hunter_color={255,60,60}, survivor_color={60,180,255}, visible_color={0,255,0};
    Color3 not_visible_color={128,0,128}, invincible_color={255,215,0}, radar_color={255,255,255};
    Color3 skeleton_color={0,255,255}, box_color={255,255,255};
    std::string color_mode="hybrid", hv_quality="high";
};
static EspConfig g_cfg;

static void load_config() {
    wchar_t path[512]; GetEnvironmentVariableW(L"APPDATA",path,512);
    PathAppendW(path,L"MecchaCamouflage\\esp_config.json");
    std::ifstream f(path); if(!f.is_open()) return;
    std::stringstream ss; ss<<f.rdbuf(); auto t=ss.str();
    auto js=[&](const std::string& k)->std::string{
        auto p=t.find("\""+k+"\""); if(p==std::string::npos)return"";
        p=t.find(':',p); if(p==std::string::npos)return"";
        p=t.find_first_of("\"tf0-9[",p+1); if(p==std::string::npos)return"";
        if(t[p]=='\"'){auto e=t.find('\"',p+1);return e==std::string::npos?"":t.substr(p+1,e-p-1);}
        if(t[p]=='['){auto e=t.find(']',p);return e==std::string::npos?"":t.substr(p,e-p+1);}
        auto e=t.find_first_of(",}\n\r",p+1);return t.substr(p,e-p);
    };
    auto jb=[&](const std::string& k)->bool{return js(k)=="true";};
    auto ji=[&](const std::string& k)->int{auto v=js(k);return v.empty()?0:atoi(v.c_str());};
    auto jf=[&](const std::string& k)->float{auto v=js(k);return v.empty()?0:(float)atof(v.c_str());};
    auto jc=[&](const std::string& k)->Color3{
        auto v=js(k); if(v.empty()||v[0]!='[') return {255,255,255};
        auto n=v.substr(1,v.size()-2); auto c1=n.find(','),c2=n.find(',',c1+1);
        if(c1==std::string::npos||c2==std::string::npos)return{255,255,255};
        auto cl=[&](const std::string& s)->int{int v=atoi(s.c_str());return v<0?0:v>255?255:v;};
        return{cl(n.substr(0,c1)),cl(n.substr(c1+1,c2-c1-1)),cl(n.substr(c2+1))};
    };
    #define CFGb(f) g_cfg.f=jb(#f)
    #define CFGi(f) g_cfg.f=ji(#f)
    #define CFGf(f) g_cfg.f=jf(#f)
    #define CFGc(f) g_cfg.f=jc(#f)
    CFGb(enabled);CFGb(dot_esp);CFGb(box_esp);CFGb(corner_box);CFGb(skeleton_esp);
    CFGb(snap_lines);CFGb(show_local);CFGb(show_names);CFGb(show_roles);CFGb(show_distance);
    CFGb(health_bar);CFGb(shield_bar);CFGb(enemy_only);CFGb(distance_scaling);
    CFGb(invincible_detect);CFGb(disable_buried);CFGb(draw_all);CFGb(draw_all_names);
    CFGb(background_geo);CFGb(show_cursor);CFGb(radar_enabled);CFGb(aimbot_enabled);
    CFGb(aimbot_show_fov);CFGb(magnet_enabled);CFGb(hunter_esp);CFGb(survivor_esp);
    CFGb(hypervision_enabled);CFGb(hv_show_paths);CFGb(hv_show_exposure);CFGb(hv_test_sphere);
    CFGb(filter_hide_enemy);CFGb(filter_hide_self);CFGb(filter_hide_teammate);CFGb(filter_hide_unknown);
    CFGi(dot_radius);CFGi(line_thickness);CFGi(radar_size);CFGi(radar_opacity);CFGi(aimbot_fov);CFGi(magnet_fov);
    CFGf(box_height_world);CFGf(scale_ref_dist);CFGf(draw_all_max_dist);CFGf(radar_range);
    CFGf(aimbot_smooth);CFGf(aimbot_target_offset);CFGf(magnet_strength);
    CFGi(box_y_offset);CFGi(point_size);
    CFGf(hv_test_x);CFGf(hv_test_y);CFGf(hv_test_z);
    CFGc(enemy_color);CFGc(teammate_color);CFGc(local_color);CFGc(unknown_color);
    CFGc(hunter_color);CFGc(survivor_color);CFGc(visible_color);CFGc(not_visible_color);
    CFGc(invincible_color);CFGc(radar_color);CFGc(skeleton_color);CFGc(box_color);
    auto cm=js("color_mode"); if(!cm.empty())g_cfg.color_mode=cm;
    auto hq=js("hv_quality"); if(!hq.empty())g_cfg.hv_quality=hq;
    g_cfg.radar_size=std::max(80,std::min(400,g_cfg.radar_size));
    g_cfg.radar_opacity=std::max(0,std::min(255,g_cfg.radar_opacity));
    #undef CFGb CFGi CFGf CFGc
}

// ======================== Game Data ==========================
struct PlayerData {
    uint64_t actor, ps;
    double pos[3];
    float yaw, health, shield, dist;
    bool invincible, is_local, is_enemy, is_hunter, is_survivor;
    int role;
    float sx, sy;
    bool on_screen;
};
struct CameraData { double loc[3], rot[3]; float fov; bool valid; };
static std::vector<PlayerData> g_players;
static std::vector<std::vector<double>> g_hv_cloud;
static CameraData g_cam = {};

static HWND find_game() { return FindWindowW(nullptr, GAME_TITLE); }

// ======================== World to Screen ===================
static bool w2s(const double pos[3], const CameraData& cam, int sw, int sh, float& sx, float& sy) {
    if(!cam.valid||cam.fov<=0) return false;
    float p=(float)(cam.rot[0]*PI/180),y=(float)(cam.rot[1]*PI/180),r=(float)(cam.rot[2]*PI/180);
    float sp=sinf(p),cp=cosf(p),sy_=sinf(y),cy_=cosf(y),sr=sinf(r),cr=cosf(r);
    double fwd[3]={cp*cy_,cp*sy_,sp};
    double rgt[3]={sr*sp*cy_-cr*sy_,sr*sp*sy_+cr*cy_,-sr*cp};
    double up[3]={-(cr*sp*cy_+sr*sy_),cy_*sr-cr*sp*sy_,cr*cp};
    double dx=pos[0]-cam.loc[0],dy=pos[1]-cam.loc[1],dz=pos[2]-cam.loc[2];
    double vx=dx*fwd[0]+dy*fwd[1]+dz*fwd[2];
    double vy=dx*rgt[0]+dy*rgt[1]+dz*rgt[2];
    double vz=dx*up[0]+dy*up[1]+dz*up[2];
    if(vx<=0.1) return false;
    float thf=tanf(cam.fov*PI/360); if(thf<=0.001f) return false;
    float ndc_x=float(vy/(vx*thf)),ndc_y=float(vz/(vx*thf/(float(sw)/float(sh))));
    if(fabsf(ndc_x)>1.5f||fabsf(ndc_y)>1.5f) return false;
    sx=(1+ndc_x)*sw/2; sy=(1-ndc_y)*sh/2;
    return true;
}

static float scl(float d) {
    if(!g_cfg.distance_scaling) return 1;
    return std::max(0.3f,std::min(3.0f,g_cfg.scale_ref_dist/std::max(100.0f,d)));
}

// ======================== GDI Drawing =======================
static void gdi_txt(HDC hdc, int x, int y, COLORREF c, const wchar_t* fmt, ...) {
    SetTextColor(hdc, c); SetBkMode(hdc, TRANSPARENT);
    wchar_t buf[256]; va_list ap; va_start(ap,fmt); vswprintf_s(buf,fmt,ap); va_end(ap);
    TextOutW(hdc, x, y, buf, (int)wcslen(buf));
}
static void gdi_fill(HDC hdc, int x, int y, int w, int h, COLORREF c) {
    SetDCBrushColor(hdc, c); SetDCPenColor(hdc, c);
    SelectObject(hdc, GetStockObject(DC_BRUSH)); SelectObject(hdc, GetStockObject(DC_PEN));
    Rectangle(hdc, x, y, x+w, y+h);
}
static void gdi_line(HDC hdc, int x1,int y1,int x2,int y2, COLORREF c, int w=1) {
    HPEN pen=CreatePen(PS_SOLID,w,c); SelectObject(hdc,pen);
    MoveToEx(hdc,x1,y1,0); LineTo(hdc,x2,y2); DeleteObject(pen);
}
static void gdi_circle(HDC hdc, int cx,int cy,int r, COLORREF c) {
    SetDCBrushColor(hdc,c); SetDCPenColor(hdc,c);
    SelectObject(hdc, GetStockObject(DC_BRUSH)); SelectObject(hdc, GetStockObject(DC_PEN));
    Ellipse(hdc,cx-r,cy-r,cx+r,cy+r);
}

static COLORREF cr(const Color3& c) { return RGB(c.r,c.g,c.b); }
static Color3 team_col(const PlayerData& p) {
    if(p.is_local) return g_cfg.local_color;
    if(p.is_enemy) return g_cfg.enemy_color;
    return g_cfg.teammate_color;
}
static Color3 role_col(const PlayerData& p) {
    if(p.is_hunter) return g_cfg.hunter_color;
    if(p.is_survivor) return g_cfg.survivor_color;
    return g_cfg.unknown_color;
}
static Color3 final_col(const PlayerData& p) {
    if(g_cfg.color_mode=="role") { auto c=role_col(p); if(c.r||c.g||c.b) return c; }
    return team_col(p);
}

// ======================== Rendering ==========================
static void render_frame(HDC hdc, int sw, int sh) {
    // Black = transparent (LWA_COLORKEY)
    gdi_fill(hdc, 0, 0, sw, sh, RGB(0,0,0));

    if(!g_cam.valid) {
        gdi_txt(hdc, sw/2-80, sh/2, RGB(128,128,128), L"Waiting for game...");
        return;
    }

    // Compute screen positions
    for(auto& p : g_players) {
        double aim[3]={p.pos[0],p.pos[1],p.pos[2]+g_cfg.aimbot_target_offset};
        p.on_screen = w2s(aim, g_cam, sw, sh, p.sx, p.sy);
    }

    for(auto& p : g_players) {
        if(!p.on_screen) continue;
        if(p.is_local&&!g_cfg.show_local) continue;
        if(g_cfg.enemy_only&&!p.is_enemy) continue;
        if(g_cfg.disable_buried&&p.dist<50) continue;
        if(p.is_hunter&&!g_cfg.hunter_esp) continue;
        if(p.is_survivor&&!g_cfg.survivor_esp) continue;
        if(p.is_local&&g_cfg.filter_hide_self) continue;
        if(!p.is_local&&p.is_enemy&&g_cfg.filter_hide_enemy) continue;
        if(!p.is_local&&!p.is_enemy&&g_cfg.filter_hide_teammate) continue;
        if(g_cfg.filter_hide_unknown&&!p.is_hunter&&!p.is_survivor&&!p.is_local&&!p.is_enemy) continue;

        float s=scl(p.dist);
        int sx=(int)p.sx, sy=(int)p.sy;

        // Snap line
        if(!p.is_local&&g_cfg.snap_lines) {
            COLORREF team=cr(team_col(p)), role=cr(role_col(p));
            bool hybrid=g_cfg.color_mode=="hybrid"&&(p.is_hunter||p.is_survivor);
            int x0=sw/2,y0=sh,x1=sx,y1=sy;
            int dx=x1-x0,dy=y1-y0;
            int dist_=(int)sqrtf((float)(dx*dx+dy*dy));
            if(dist_>0) {
                if(hybrid) {
                    for(int t=0;t<dist_;t+=8) {
                        int t2=(t+8<dist_)?t+8:dist_;
                        int px1=(int)(x0+dx*(float)t/dist_);
                        int py1=(int)(y0+dy*(float)t/dist_);
                        int px2=(int)(x0+dx*(float)t2/dist_);
                        int py2=(int)(y0+dy*(float)t2/dist_);
                        gdi_line(hdc,px1,py1,px2,py2,(t/8)%2?role:team,1);
                    }
                } else {
                    gdi_line(hdc,x0,y0,x1,y1,team,1);
                }
            }
        }

        // Dot
        if(g_cfg.dot_esp) {
            int r=std::max(2,(int)(g_cfg.dot_radius*s));
            gdi_circle(hdc,sx,sy,r,cr(final_col(p)));
            if(p.invincible) {
                // Gold X
                HPEN pen=CreatePen(PS_SOLID,std::max(1,r/2),cr(g_cfg.invincible_color));
                SelectObject(hdc,pen);
                int o=(int)(r*0.4f);
                MoveToEx(hdc,sx-o,sy-o,0); LineTo(hdc,sx+o,sy+o);
                MoveToEx(hdc,sx+o,sy-o,0); LineTo(hdc,sx-o,sy+o);
                DeleteObject(pen);
            }
        }

        // Box (3D projected)
        if(g_cfg.box_esp||g_cfg.corner_box) {
            float hh=g_cfg.box_height_world*s;
            float hw=(g_cfg.box_height_world/3.0f)*s;
            float yaw_rad=p.yaw*PI/180,cy=cosf(yaw_rad),siny=sinf(yaw_rad);
            float corners[8][3]={{-hw,0,-hw},{-hw,0,hw},{hw,0,hw},{hw,0,-hw},
                                 {-hw,hh,-hw},{-hw,hh,hw},{hw,hh,hw},{hw,hh,-hw}};
            float mnx=1e9f,mny=1e9f,mxx=-1e9f,mxy=-1e9f;
            int valid=0;
            for(auto& c:corners) {
                float rx=c[0]*cy-c[2]*siny,rz=c[0]*siny+c[2]*cy;
                double wp[3]={p.pos[0]+rx,p.pos[1]+c[1],p.pos[2]+rz};
                float sx_,sy_;
                if(w2s(wp,g_cam,sw,sh,sx_,sy_)) {
                    mnx=std::min(mnx,sx_); mny=std::min(mny,sy_);
                    mxx=std::max(mxx,sx_); mxy=std::max(mxy,sy_); valid++;
                }
            }
            if(valid>=4) {
                auto bcol=cr(g_cfg.box_color);
                int bw=(int)(mxx-mnx),bh=(int)(mxy-mny);
                if(g_cfg.box_esp&&!g_cfg.corner_box) {
                    HPEN pen=CreatePen(PS_SOLID,g_cfg.line_thickness,bcol);
                    SelectObject(hdc,pen); SelectObject(hdc,GetStockObject(NULL_BRUSH));
                    Rectangle(hdc,(int)mnx,(int)mny,(int)mxx,(int)mxy);
                    DeleteObject(pen);
                }
                if(g_cfg.corner_box) {
                    if(bw>=2&&bh>=2) {
                        int clen=std::max(4,(int)(std::min(bw,bh)*0.25f));
                        HPEN pen=CreatePen(PS_SOLID,g_cfg.line_thickness,bcol);
                        SelectObject(hdc,pen);
                        int mx=(int)mnx,Mx=(int)mxx,my=(int)mny,My=(int)mxy;
                        MoveToEx(hdc,mx,my,0);LineTo(hdc,mx+clen,my);
                        MoveToEx(hdc,mx,my,0);LineTo(hdc,mx,my+clen);
                        MoveToEx(hdc,Mx-clen,my,0);LineTo(hdc,Mx,my);
                        MoveToEx(hdc,Mx,my,0);LineTo(hdc,Mx,my+clen);
                        MoveToEx(hdc,mx,My-clen,0);LineTo(hdc,mx,My);
                        MoveToEx(hdc,mx,My,0);LineTo(hdc,mx+clen,My);
                        MoveToEx(hdc,Mx-clen,My,0);LineTo(hdc,Mx,My);
                        MoveToEx(hdc,Mx,My-clen,0);LineTo(hdc,Mx,My);
                        DeleteObject(pen);
                    }
                }
            }
        }

        // Health bar (above player)
        if(g_cfg.health_bar) {
            int bw=std::max(4,(int)(24*s));
            int bx=sx-bw/2, by=sy-(int)(20*s);
            int bh_=4;
            // Background
            gdi_fill(hdc,bx,by,bw,bh_,RGB(30,30,30));
            // Health fill with gradient
            float hpct=std::max(0.0f,std::min(1.0f,p.health/100.0f));
            int hfill=(int)(bw*hpct);
            if(hfill>0) {
                int hcr=(int)(255*(1-hpct)), hcg=(int)(255*hpct);
                gdi_fill(hdc,bx,by,hfill,bh_,RGB(hcr,hcg,0));
            }
            // Shield
            if(g_cfg.shield_bar&&p.shield>0) {
                float spct=std::min(1.0f,p.shield/100.0f);
                int sy_=by+bh_+2;
                gdi_fill(hdc,bx,sy_,bw,bh_,RGB(30,30,30));
                int sfill=(int)(bw*spct);
                if(sfill>0) gdi_fill(hdc,bx,sy_,sfill,bh_,RGB(0,120,255));
            }
        }

        // Labels (right of dot)
        std::wstring parts;
        if(g_cfg.show_names) {
            if(p.is_local) parts+=L"YOU";
            else if(p.is_enemy) { wchar_t b[32]; swprintf_s(b,L"Enemy %d",rand()%4+1); parts+=b; }
            else parts+=L"Teammate";
        }
        if(g_cfg.show_roles&&p.is_hunter) parts+=parts.empty()?L"Hunter":L" | Hunter";
        if(g_cfg.show_roles&&p.is_survivor) parts+=parts.empty()?L"Survivor":L" | Survivor";
        if(p.invincible) parts+=parts.empty()?L"[INV]":L" | [INV]";
        if(g_cfg.show_distance&&!p.is_local) {
            wchar_t b[32]; swprintf_s(b,L"%dm",(int)(p.dist/100));
            parts+=parts.empty()?b: (L" | "+std::wstring(b));
        }
        if(!parts.empty()) {
            int lx=sx+(int)(g_cfg.dot_radius*s)+4, ly=sy;
            SetTextColor(hdc,cr(final_col(p))); SetBkMode(hdc,TRANSPARENT);
            TextOutW(hdc,lx,ly,parts.c_str(),(int)parts.size());
        }
    }

    // Aimbot FOV
    if(g_cfg.aimbot_enabled&&g_cfg.aimbot_show_fov) {
        HPEN pen=CreatePen(PS_SOLID,1,RGB(255,255,255));
        SelectObject(hdc,pen); SelectObject(hdc,GetStockObject(NULL_BRUSH));
        int r=g_cfg.aimbot_fov;
        Ellipse(hdc,sw/2-r,sh/2-r,sw/2+r,sh/2+r);
        DeleteObject(pen);
    }

    // Radar (top-right)
    if(g_cfg.radar_enabled) {
        int rs=g_cfg.radar_size, rx=sw-rs-20, ry=20;
        int cx=rx+rs/2, cy=ry+rs/2;
        float range=std::max(g_cfg.radar_range,1000.0f), half=rs/2.0f;
        float scale_=(half-8)/range;
        // Background
        gdi_fill(hdc,rx,ry,rs,rs,RGB((int)(0*0.05f),(int)(0*0.05f),(int)(0*0.08f)));
        // Border
        HPEN pen=CreatePen(PS_SOLID,1,RGB(255,255,255));
        SelectObject(hdc,pen); SelectObject(hdc,GetStockObject(NULL_BRUSH));
        Ellipse(hdc,cx-half,cy-half,cx+half,cy+half);
        DeleteObject(pen);
        // Crosshair
        HPEN cpen=CreatePen(PS_SOLID,1,RGB(80,80,100));
        SelectObject(hdc,cpen);
        MoveToEx(hdc,cx-half,cy,0); LineTo(hdc,cx+half,cy);
        MoveToEx(hdc,cx,cy-half,0); LineTo(hdc,cx,cy+half);
        DeleteObject(cpen);
        // Center dot
        gdi_circle(hdc,cx,cy,2,cr(g_cfg.local_color));
        // Players
        for(auto& p:g_players) {
            if(p.is_local) continue;
            float dx=(float)(p.pos[0]-g_cam.loc[0]),dz=(float)(p.pos[2]-g_cam.loc[2]);
            float d2d=sqrtf(dx*dx+dz*dz); if(d2d<1) continue;
            float angle=atan2f(dx,dz)-g_cam.rot[1]*PI/180;
            float rsize=d2d/range*half;
            float px=sinf(angle)*rsize, py=cosf(angle)*rsize;
            if(fabsf(px)>half-4||fabsf(py)>half-4) continue;
            gdi_circle(hdc,(int)(cx+px),(int)(cy+py),2,cr(team_col(p)));
        }
    }

    // Status
    int non_local=0; for(auto&p:g_players) if(!p.is_local) non_local++;
    gdi_txt(hdc,10,20,RGB(255,255,255),L"Players: %d | Attached",non_local);

    // Watermark
    SetTextColor(hdc,RGB(255,255,255)); SetBkMode(hdc,TRANSPARENT);
    TextOutW(hdc,sw-165,sh-15,L"Meccha Chameleon Tools",22);
}

// ======================== Game Data Reading ==================
static void read_game_data() {
    g_data_tick++;
    if(g_data_tick%(TARGET_FPS/20)==0) load_config();

    CameraData cam={};
    cam.valid=mc_read_camera(cam.loc,cam.rot,&cam.fov);
    if(cam.valid) g_cam=cam;

    if(!cam.valid&&!g_cam.valid) return;
    if(!cam.valid) return;

    g_players.clear();
    uint64_t buf[64];
    int n=mc_read_players(buf,64);
    if(n<=0) return;

    int32_t off_rc=mc_get_offset("RootComponent");
    int32_t off_rl=mc_get_offset("RelativeLocation");
    int32_t off_ps=0, off_pawn=0;

    for(int i=0;i<n;i++) {
        PlayerData p={}; p.actor=buf[i];
        uint64_t root=(off_rc>=0)?mc_read_ptr(buf[i]+off_rc):0;
        if(!root) continue;
        float pf[3]; int lo=(off_rl>=0)?off_rl:0x11C;
        if(!mc_read_vec3_f(root+lo,pf)) continue;
        p.pos[0]=pf[0]; p.pos[1]=pf[1]; p.pos[2]=pf[2];
        float rf[3]={}; mc_read_vec3_f(root+lo+12,rf);
        p.yaw=rf[1];
        p.health=mc_player_get_health(buf[i],0);
        p.shield=mc_read_float(buf[i]+0x140);
        p.invincible=mc_player_get_invincible(buf[i])&&g_cfg.invincible_detect;
        p.role=mc_player_get_role(buf[i]);
        p.is_hunter=(p.role==1); p.is_survivor=(p.role==2);
        // Determine is_local via PlayerController comparison
        p.is_local=(i==0); // simplified
        p.is_enemy=(i>0);
        if(p.health<0.01f) continue;
        p.dist=(float)sqrt(pow(p.pos[0]-g_cam.loc[0],2)+pow(p.pos[1]-g_cam.loc[1],2)+pow(p.pos[2]-g_cam.loc[2],2));
        g_players.push_back(p);
    }
    std::sort(g_players.begin(),g_players.end(),[](auto&a,auto&b){return a.dist<b.dist;});
}

// ======================== Aimbot =============================
static void do_aimbot() {
    if(!(g_cfg.aimbot_enabled||g_cfg.magnet_enabled)||!g_cam.valid||g_players.empty()) return;
    uint64_t world=mc_get_world(); if(!world) return;
    int32_t off_gi=mc_get_offset("OwningGameInstance"),
            off_lp=mc_get_offset("LocalPlayers"),
            off_pc=mc_get_offset("PlayerController");
    if(off_gi<0||off_lp<0||off_pc<0) return;
    uint64_t gi=mc_read_ptr(world+off_gi); if(!gi) return;
    uint64_t la=mc_read_ptr(gi+off_lp); if(!la) return;
    uint64_t lp=mc_read_ptr(la); if(!lp) return;
    uint64_t pc=mc_read_ptr(lp+off_pc); if(!pc) return;
    int32_t off_cr=mc_resolve_offset("Controller","ControlRotation");
    if(off_cr<0) return;
    uint64_t ca=pc+off_cr;

    float cx=g_rect.right-g_rect.left,cy=g_rect.bottom-g_rect.top;
    cx/=2; cy/=2;
    float best=1e9f; const PlayerData* bt=nullptr;
    for(auto&p:g_players) {
        if(p.is_local||!p.is_enemy) continue;
        if(p.on_screen) {
            float d=sqrtf((p.sx-cx)*(p.sx-cx)+(p.sy-cy)*(p.sy-cy));
            int fov=g_cfg.magnet_enabled?g_cfg.magnet_fov:g_cfg.aimbot_fov;
            if(d<=fov&&d<best) {best=d;bt=&p;}
        }
    }
    if(!bt) return;

    double dx=bt->pos[0]-g_cam.loc[0],dy=bt->pos[1]-g_cam.loc[1],
           dz=(bt->pos[2]+g_cfg.aimbot_target_offset)-g_cam.loc[2];
    double len=sqrt(dx*dx+dy*dy+dz*dz); if(len<1) return;
    double ap=-asin(dz/len)*180/PI, ay=atan2(dy,dx)*180/PI;
    float cp=mc_read_float(ca), cy_=mc_read_float(ca+4);
    float sm=g_cfg.aimbot_smooth;
    mc_write_float(ca,(float)(cp+(ap-cp)*sm));
    mc_write_float(ca+4,(float)(cy_+(ay-cy_)*(g_cfg.magnet_enabled?g_cfg.magnet_strength:sm)));
}

// ======================== Window =============================
static LRESULT CALLBACK wnd_proc(HWND hwnd,UINT msg,WPARAM wp,LPARAM lp) {
    switch(msg) {
    case WM_DESTROY: g_running=false; PostQuitMessage(0); return 0;
    case WM_PAINT: {
        PAINTSTRUCT ps; HDC hdc=BeginPaint(hwnd,&ps);
        RECT rc; GetClientRect(hwnd,&rc);
        render_frame(hdc,rc.right-rc.left,rc.bottom-rc.top);
        EndPaint(hwnd,&ps);
        return 0;
    }
    case WM_KEYDOWN: if(wp==VK_END) {g_running=false;DestroyWindow(hwnd);} break;
    case WM_ERASEBKGND: return 1; // prevent flicker
    }
    return DefWindowProcW(hwnd,msg,wp,lp);
}

int WINAPI WinMain(HINSTANCE hInst,HINSTANCE,LPSTR,int) {
    // Init memory engine
    for(int i=0;i<30;i++){if(mc_init())break;Sleep(2000);}
    if(mc_is_attached()) mc_init_engine();
    load_config();

    WNDCLASSEXW wc={sizeof(wc),CS_HREDRAW|CS_VREDRAW,wnd_proc};
    wc.hInstance=hInst; wc.hCursor=LoadCursor(0,IDC_ARROW);
    wc.lpszClassName=WND_CLASS;
    if(!RegisterClassExW(&wc)) return 1;

    // Find game window
    for(int i=0;i<30;i++){g_game=find_game();if(g_game)break;Sleep(1000);}
    if(!g_game) return 1;
    GetWindowRect(g_game,&g_rect);

    int wp=g_rect.right-g_rect.left,hp=g_rect.bottom-g_rect.top;
    g_wnd=CreateWindowExW(
        WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_TOPMOST|WS_EX_NOACTIVATE,
        WND_CLASS,L"Meccha Overlay",WS_POPUP|WS_VISIBLE,
        g_rect.left,g_rect.top,wp,hp,0,0,hInst,0);
    if(!g_wnd) return 1;
    SetLayeredWindowAttributes(g_wnd,RGB(0,0,0),0,LWA_COLORKEY);
    SetWindowPos(g_wnd,HWND_TOPMOST,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW);

    if(g_cfg.show_cursor) ShowCursor(TRUE);

    // Main loop
    while(g_running) {
        MSG msg;
        while(PeekMessageW(&msg,0,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}

        if(GetWindowRect(g_game,&g_rect)) {
            SetWindowPos(g_wnd,HWND_TOPMOST,g_rect.left,g_rect.top,
                         g_rect.right-g_rect.left,g_rect.bottom-g_rect.top,SWP_SHOWWINDOW);
        }

        read_game_data();

        // Trigger WM_PAINT
        InvalidateRect(g_wnd,0,FALSE);

        // Aimbot every 3 frames
        if(g_data_tick%3==0) do_aimbot();

        // Hotkeys
        if(GetAsyncKeyState(VK_END)&0x8000){g_running=false;DestroyWindow(g_wnd);}
        if((GetAsyncKeyState(VK_F1)&0x8000)||(GetAsyncKeyState(VK_INSERT)&0x8000)){
            HANDLE ev=OpenEventW(EVENT_MODIFY_STATE,FALSE,L"MecchaMenuToggle");
            if(ev){SetEvent(ev);CloseHandle(ev);}
            Sleep(200);
        }

        Sleep(TICK_MS);
    }

    mc_cleanup();
    return 0;
}
