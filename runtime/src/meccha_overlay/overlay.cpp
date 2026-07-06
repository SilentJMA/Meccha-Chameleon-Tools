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
#include <atomic>

#pragma comment(lib, "d2d1")
#pragma comment(lib, "dwrite")
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

// D2D
static ID2D1Factory* g_d2d = nullptr;
static IDWriteFactory* g_dwrite = nullptr;
static ID2D1DCRenderTarget* g_rt = nullptr;
static IDWriteTextFormat* g_font = nullptr;
static IDWriteTextFormat* g_font_sm = nullptr;
static ID2D1SolidColorBrush* g_brush = nullptr;

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

// ======================== D2D Init ===========================
static bool init_d2d() {
    if(FAILED(D2D1CreateFactory(D2D1_FACTORY_TYPE_SINGLE_THREADED,&g_d2d))) return false;
    if(FAILED(DWriteCreateFactory(DWRITE_FACTORY_TYPE_SHARED,__uuidof(IDWriteFactory),(IUnknown**)&g_dwrite))) return false;
    // Create D2D DC render target (renders to GDI DC -> UpdateLayeredWindow)
    D2D1_RENDER_TARGET_PROPERTIES drtp = D2D1::RenderTargetProperties(
        D2D1_RENDER_TARGET_TYPE_HARDWARE,
        D2D1::PixelFormat(DXGI_FORMAT_B8G8R8A8_UNORM,D2D1_ALPHA_MODE_PREMULTIPLIED));
    if(FAILED(g_d2d->CreateDCRenderTarget(&drtp,&g_rt))) return false;
    g_rt->CreateSolidColorBrush(D2D1::ColorF(1,1,1,1),&g_brush);
    g_dwrite->CreateTextFormat(L"Consolas",nullptr,DWRITE_FONT_WEIGHT_NORMAL,
        DWRITE_FONT_STYLE_NORMAL,DWRITE_FONT_STRETCH_NORMAL,12.0f,L"en-us",&g_font);
    g_dwrite->CreateTextFormat(L"Segoe UI",nullptr,DWRITE_FONT_WEIGHT_NORMAL,
        DWRITE_FONT_STYLE_NORMAL,DWRITE_FONT_STRETCH_NORMAL,8.0f,L"en-us",&g_font_sm);
    return true;
}

// ======================== Game Data ==========================
struct PlayerData {
    uint64_t actor;
    double pos[3];
    float yaw, health, shield, dist;
    bool invincible, is_local, is_enemy, is_hunter, is_survivor;
    int role;
    float sx, sy; bool on_screen;
};
struct CameraData { double loc[3], rot[3]; float fov; bool valid; };
static std::vector<PlayerData> g_players;
static CameraData g_cam = {};

static HWND find_game() { return FindWindowW(nullptr, GAME_TITLE); }

static float sclf(float d) {
    if(!g_cfg.distance_scaling) return 1;
    return std::max(0.3f,std::min(3.0f,g_cfg.scale_ref_dist/std::max(100.0f,d)));
}

static bool w2s(const double pos[3],const CameraData& cam,int sw,int sh,float& sx,float& sy) {
    if(!cam.valid||cam.fov<=0)return false;
    float p=(float)(cam.rot[0]*PI/180),y=(float)(cam.rot[1]*PI/180),r=(float)(cam.rot[2]*PI/180);
    float sp=sinf(p),cp=cosf(p),sy_=sinf(y),cy_=cosf(y),sr=sinf(r),cr=cosf(r);
    double fwd[3]={cp*cy_,cp*sy_,sp},rgt[3]={sr*sp*cy_-cr*sy_,sr*sp*sy_+cr*cy_,-sr*cp};
    double up[3]={-(cr*sp*cy_+sr*sy_),cy_*sr-cr*sp*sy_,cr*cp};
    double dx=pos[0]-cam.loc[0],dy=pos[1]-cam.loc[1],dz=pos[2]-cam.loc[2];
    double vx=dx*fwd[0]+dy*fwd[1]+dz*fwd[2],vy=dx*rgt[0]+dy*rgt[1]+dz*rgt[2],vz=dx*up[0]+dy*up[1]+dz*up[2];
    if(vx<=0.1)return false;
    float thf=tanf(cam.fov*PI/360);if(thf<=0.001f)return false;
    float nx=float(vy/(vx*thf)),ny=float(vz/(vx*thf/(float(sw)/float(sh))));
    if(fabsf(nx)>1.5f||fabsf(ny)>1.5f)return false;
    sx=(1+nx)*sw/2;sy=(1-ny)*sh/2;return true;
}

// ======================== Read Game ==========================
static void read_game_data() {
    g_data_tick++;
    if(g_data_tick%(TARGET_FPS/20)==0) load_config();
    CameraData cam={}; cam.valid=mc_read_camera(cam.loc,cam.rot,&cam.fov);
    if(cam.valid) g_cam=cam; if(!cam.valid&&!g_cam.valid) return;

    static int off_rc=-1,off_rl=-1,off_aps=-1,off_pp=-1;
    static int off_gi=-1,off_lp=-1,off_pc=-1,off_ap=-1;
    static bool ok=false; if(!ok){
        off_rc=mc_get_offset("RootComponent");off_rl=mc_get_offset("RelativeLocation");
        off_aps=mc_resolve_offset("Actor","PlayerState");
        off_pp=mc_resolve_offset("PlayerState","PawnPrivate");
        off_gi=mc_get_offset("OwningGameInstance");off_lp=mc_get_offset("LocalPlayers");
        off_pc=mc_get_offset("PlayerController");off_ap=mc_resolve_offset("PlayerController","AcknowledgedPawn");
        ok=true;
    }
    uint64_t local_pawn=0;
    uint64_t world=mc_get_world();
    if(world&&off_gi>=0&&off_lp>=0&&off_pc>=0&&off_ap>=0){
        uint64_t gi=mc_read_ptr(world+off_gi);
        if(gi){uint64_t la=mc_read_ptr(gi+off_lp);
            if(la){uint64_t lp=mc_read_ptr(la);
                if(lp){uint64_t lpc=mc_read_ptr(lp+off_pc);
                    if(lpc)local_pawn=mc_read_ptr(lpc+off_ap);
                }
            }
        }
    }

    uint64_t buf[64]; int n=mc_read_players(buf,64);
    g_players.clear(); if(n<=0) return;
    for(int i=0;i<n;i++){
        uint64_t root=(off_rc>=0)?mc_read_ptr(buf[i]+off_rc):0;
        if(!root)continue; float pf[3]; int lo=(off_rl>=0)?off_rl:0x11C;
        if(!mc_read_vec3_f(root+lo,pf))continue;
        PlayerData p={}; p.actor=buf[i];
        p.pos[0]=pf[0];p.pos[1]=pf[1];p.pos[2]=pf[2];
        float rf[3]={};mc_read_vec3_f(root+lo+12,rf);p.yaw=rf[1];
        p.health=mc_player_get_health(buf[i],0);
        p.shield=mc_read_float(buf[i]+0x140);
        p.invincible=mc_player_get_invincible(buf[i])&&g_cfg.invincible_detect;
        uint64_t ps=(off_aps>=0)?mc_read_ptr(buf[i]+off_aps):0;
        if(!ps&&off_pp>=0){
            for(uint32_t j=0;j<(uint32_t)mc_uobject_count()&&!ps;j++){
                uint64_t o=mc_uobject_get(j); if(!o)continue;
                char cn[64]; if(!mc_uobject_class_name(o,cn,64))continue;
                if(strstr(cn,"PlayerController")){
                    uint64_t os=mc_read_ptr(o+off_aps/*wrong: use off_pstate*/);
                    // Try via AcknowledgedPawn -> PlayerState
                    if(off_ap>=0){uint64_t pawn=mc_read_ptr(o+off_ap); if(pawn==buf[i]){ps=pawn;break;}}
                }
            }
        }
        p.role=mc_player_get_role(ps?ps:buf[i]); p.is_hunter=(p.role==1);p.is_survivor=(p.role==2);
        p.is_local=(buf[i]==local_pawn); p.is_enemy=!p.is_local;
        if(p.health<0.01f)continue;
        p.dist=(float)sqrt(pow(p.pos[0]-g_cam.loc[0],2)+pow(p.pos[1]-g_cam.loc[1],2)+pow(p.pos[2]-g_cam.loc[2],2));
        g_players.push_back(p);
    }
    std::sort(g_players.begin(),g_players.end(),[](auto&a,auto&b){return a.dist<b.dist;});
}

// ======================== Colors ==============================
static D2D1_COLOR_F c2f(const Color3& c,float a=1){return{c.r/255.0f,c.g/255.0f,c.b/255.0f,a};}
static Color3 team_c(const PlayerData& p){
    if(p.is_local) return g_cfg.local_color;
    if(p.is_enemy) return g_cfg.enemy_color;
    return g_cfg.teammate_color;
}
static Color3 role_c(const PlayerData& p){
    if(p.is_hunter) return g_cfg.hunter_color;
    if(p.is_survivor) return g_cfg.survivor_color;
    return g_cfg.unknown_color;
}
static D2D1_COLOR_F final_c(const PlayerData& p){
    if(g_cfg.color_mode=="role"){auto c=role_c(p);if(c.r||c.g||c.b)return c2f(c);}
    return c2f(team_c(p));
}

// ======================== D2D Rendering =======================
static void d2d_txt(float x,float y,D2D1_COLOR_F c,const wchar_t* t){
    g_brush->SetColor(c);
    g_rt->DrawText(t,(UINT32)wcslen(t),g_font,D2D1::RectF(x,y,x+300,y+20),g_brush);
}
static void d2d_fc(float cx,float cy,float r,D2D1_COLOR_F c){
    g_brush->SetColor(c);g_rt->FillEllipse({cx,cy,r,r},g_brush);
}
static void d2d_dc(float cx,float cy,float r,D2D1_COLOR_F c,float w=1){
    g_brush->SetColor(c);g_rt->DrawEllipse({cx,cy,r,r},g_brush,w);
}
static void d2d_ln(float x1,float y1,float x2,float y2,D2D1_COLOR_F c,float w=1){
    g_brush->SetColor(c);g_rt->DrawLine({x1,y1},{x2,y2},g_brush,w);
}
static void d2d_fr(float x,float y,float w,float h,D2D1_COLOR_F c){
    g_brush->SetColor(c);g_rt->FillRectangle(D2D1::RectF(x,y,x+w,y+h),g_brush);
}

// ======================== Render Frame ========================
static void render_d2d(HDC hdc, int sw, int sh) {
    // Bind D2D to the DC
    RECT rc={0,0,sw,sh};
    if(FAILED(g_rt->BindDC(hdc,&rc))) return;
    g_rt->BeginDraw();
    g_rt->Clear(D2D1::ColorF(0,0,0,0)); // transparent

    if(!g_cam.valid) {
        d2d_txt((float)sw/2-80,(float)sh/2,c2f({128,128,128}),L"Waiting for game...");
        goto end;
    }

    // Compute screen positions
    for(auto& p:g_players){
        double ap[3]={p.pos[0],p.pos[1],p.pos[2]+g_cfg.aimbot_target_offset};
        p.on_screen=w2s(ap,g_cam,sw,sh,p.sx,p.sy);
    }

    for(auto& p:g_players){
        if(!p.on_screen)continue;
        if(p.is_local&&!g_cfg.show_local)continue;
        if(g_cfg.enemy_only&&!p.is_enemy)continue;
        if(g_cfg.disable_buried&&p.dist<50)continue;
        if(p.is_hunter&&!g_cfg.hunter_esp)continue;
        if(p.is_survivor&&!g_cfg.survivor_esp)continue;
        if(p.is_local&&g_cfg.filter_hide_self)continue;
        if(!p.is_local&&p.is_enemy&&g_cfg.filter_hide_enemy)continue;
        if(!p.is_local&&!p.is_enemy&&g_cfg.filter_hide_teammate)continue;

        float s=sclf(p.dist);
        float sx=p.sx,sy=p.sy;
        auto team=team_c(p),role=role_c(p);
        bool hybrid=g_cfg.color_mode=="hybrid"&&(p.is_hunter||p.is_survivor);
        auto col=c2f(team);

        // Snap line
        if(!p.is_local&&g_cfg.snap_lines){
            float x0=sw/2.0f,y0=(float)sh,x1=sx,y1=sy;
            float dx=x1-x0,dy=y1-y0; float len=sqrtf(dx*dx+dy*dy);
            if(len>0){
                if(hybrid){
                    float seg=8;
                    for(int i=0;i<(int)(len/seg);i++){
                        float t0=i*seg/len,t1=std::min((i+1)*seg,len)/len;
                        d2d_ln(x0+dx*t0,y0+dy*t0,x0+dx*t1,y0+dy*t1,(i%2)?c2f(role):c2f(team),1);
                    }
                }else d2d_ln(x0,y0,x1,y1,col,1);
            }
        }

        // Dot
        if(g_cfg.dot_esp){
            float r=std::max(2.0f,(float)g_cfg.dot_radius*s);
            d2d_fc(sx,sy,r,final_c(p));
            if(p.invincible){
                float o=r*0.4f; float lw=std::max(1.0f,r/2);
                d2d_ln(sx-o,sy-o,sx+o,sy+o,c2f(g_cfg.invincible_color),lw);
                d2d_ln(sx+o,sy-o,sx-o,sy+o,c2f(g_cfg.invincible_color),lw);
            }
        }

        // Box (3D projected)
        if(g_cfg.box_esp||g_cfg.corner_box){
            float hh=g_cfg.box_height_world*s,hw=(g_cfg.box_height_world/3)*s;
            float yaw=p.yaw*PI/180,cy=cosf(yaw),si=sinf(yaw);
            float cn[8][3]={{-hw,0,-hw},{-hw,0,hw},{hw,0,hw},{hw,0,-hw},
                            {-hw,hh,-hw},{-hw,hh,hw},{hw,hh,hw},{hw,hh,-hw}};
            float mnx=1e9f,mny=1e9f,mxx=-1e9f,mxy=-1e9f; int v=0;
            for(auto&c:cn){
                float rx=c[0]*cy-c[2]*si,rz=c[0]*si+c[2]*cy;
                double wp[3]={p.pos[0]+rx,p.pos[1]+c[1],p.pos[2]+rz};
                float sx_,sy_; if(w2s(wp,g_cam,sw,sh,sx_,sy_)){mnx=std::min(mnx,sx_);mny=std::min(mny,sy_);mxx=std::max(mxx,sx_);mxy=std::max(mxy,sy_);v++;}
            }
            if(v>=4){
                auto bc=c2f(g_cfg.box_color); float lt=(float)g_cfg.line_thickness;
                if(g_cfg.box_esp&&!g_cfg.corner_box){d2d_dc(mnx,mny,0,bc,lt);d2d_dc(mxx,mxy,0,bc,lt);
                    d2d_ln(mnx,mny,mxx,mny,bc,lt);d2d_ln(mxx,mny,mxx,mxy,bc,lt);
                    d2d_ln(mxx,mxy,mnx,mxy,bc,lt);d2d_ln(mnx,mxy,mnx,mny,bc,lt);}
                if(g_cfg.corner_box){
                    int bw=(int)(mxx-mnx),bh=(int)(mxy-mny);
                    if(bw>=2&&bh>=2){
                        int cl=std::max(4,(int)(std::min(bw,bh)*0.25f));
                        d2d_ln((float)mnx,(float)mny,(float)(mnx+cl),(float)mny,bc,lt);
                        d2d_ln((float)mnx,(float)mny,(float)mnx,(float)(mny+cl),bc,lt);
                        d2d_ln((float)(mxx-cl),(float)mny,(float)mxx,(float)mny,bc,lt);
                        d2d_ln((float)mxx,(float)mny,(float)mxx,(float)(mny+cl),bc,lt);
                        d2d_ln((float)mnx,(float)(mxy-cl),(float)mnx,(float)mxy,bc,lt);
                        d2d_ln((float)mnx,(float)mxy,(float)(mnx+cl),(float)mxy,bc,lt);
                        d2d_ln((float)(mxx-cl),(float)mxy,(float)mxx,(float)mxy,bc,lt);
                        d2d_ln((float)mxx,(float)(mxy-cl),(float)mxx,(float)mxy,bc,lt);
                    }
                }
            }
        }

        // Health bar (above)
        if(g_cfg.health_bar){
            float bw=std::max(4.0f,24*s),bh=4;
            float bx=sx-bw/2,by=sy-20*s;
            d2d_fr(bx,by,bw,bh,c2f({30,30,30},180/255.0f));
            float hpct=std::max(0.0f,std::min(1.0f,p.health/100.0f));
            float hfill=bw*hpct; if(hfill>0)d2d_fr(bx,by,hfill,bh,c2f({(int)(255*(1-hpct)),(int)(255*hpct),0},220/255.0f));
            if(g_cfg.shield_bar&&p.shield>0){
                float sy_=by+bh+2;d2d_fr(bx,sy_,bw,bh,c2f({30,30,30},180/255.0f));
                float sfill=bw*std::min(1.0f,p.shield/100.0f);if(sfill>0)d2d_fr(bx,sy_,sfill,bh,c2f({0,120,255},220/255.0f));
            }
        }

        // Labels
        std::wstring parts;
        if(g_cfg.show_names){
            if(p.is_local) parts+=L"YOU";
            else if(p.is_enemy) {wchar_t b[32];int idx=0;for(auto&op:g_players){if(!op.is_local&&op.is_enemy)idx++;if(&op==&p)break;}swprintf_s(b,L"Enemy %d",idx);parts+=b;}
            else parts+=L"Teammate";
        }
        if(g_cfg.show_roles&&p.is_hunter) parts+=parts.empty()?L"Hunter":L" | Hunter";
        if(g_cfg.show_roles&&p.is_survivor) parts+=parts.empty()?L"Survivor":L" | Survivor";
        if(p.invincible) parts+=parts.empty()?L"[INV]":L" | [INV]";
        if(g_cfg.show_distance&&!p.is_local){wchar_t b[32];swprintf_s(b,L"%dm",(int)(p.dist/100));parts+=parts.empty()?b:(L" | "+std::wstring(b));}
        if(!parts.empty()){int lx=(int)(sx+g_cfg.dot_radius*s+4);d2d_txt((float)lx,sy,final_c(p),parts.c_str());}
    }

    // Aimbot FOV
    if(g_cfg.aimbot_enabled&&g_cfg.aimbot_show_fov)
        d2d_dc((float)sw/2,(float)sh/2,(float)g_cfg.aimbot_fov,c2f({255,255,255}),1);

    // Radar (top-right)
    if(g_cfg.radar_enabled){
        int rs=g_cfg.radar_size,rx=sw-rs-20,ry=20;
        float cx=(float)(rx+rs/2),cy=(float)(ry+rs/2),range=std::max(g_cfg.radar_range,1000.0f);
        float half=rs/2.0f,sc=(half-8)/range;
        d2d_fr((float)rx,(float)ry,(float)rs,(float)rs,c2f({0,0,0},g_cfg.radar_opacity/255.0f));
        d2d_dc(cx,cy,half,c2f({80,80,100}),1);
        d2d_ln(cx-half,cy,cx+half,cy,c2f({80,80,100}),1); d2d_ln(cx,cy-half,cx,cy+half,c2f({80,80,100}),1);
        d2d_fc(cx,cy,2.5f,c2f(g_cfg.local_color));
        for(auto&p:g_players){if(p.is_local)continue;
            float dx=(float)(p.pos[0]-g_cam.loc[0]),dz=(float)(p.pos[2]-g_cam.loc[2]);
            float d2d=sqrtf(dx*dx+dz*dz);if(d2d<1)continue;
            float ang=atan2f(dx,dz)-g_cam.rot[1]*PI/180;
            float px=sinf(ang)*d2d/range*half,py=cosf(ang)*d2d/range*half;
            if(fabsf(px)>half-4||fabsf(py)>half-4)continue;
            d2d_fc(cx+px,cy+py,2.5f,c2f(team_c(p)));
        }
    }

    // Status
    int nl=0; for(auto&p:g_players)if(!p.is_local)nl++;
    {wchar_t st[128];swprintf_s(st,L"Players: %d | Attached",nl);d2d_txt(10,20,c2f({255,255,255}),st);}

    // Watermark
    g_brush->SetColor(c2f({255,255,255},40/255.0f));
    g_rt->DrawText(L"Meccha Chameleon Tools",22,g_font_sm,D2D1::RectF((float)sw-165,(float)sh-13,(float)sw,(float)sh),g_brush);

end:
    g_rt->EndDraw();
}

// ======================== Aimbot ==============================
static void do_aimbot(){
    if(!g_cfg.aimbot_enabled||!g_cam.valid||g_players.empty())return;
    uint64_t w=mc_get_world();if(!w)return;
    int gi=mc_get_offset("OwningGameInstance"),lp=mc_get_offset("LocalPlayers"),pc=mc_get_offset("PlayerController");
    if(gi<0||lp<0||pc<0)return;
    uint64_t g=mc_read_ptr(w+gi),la=mc_read_ptr(g+lp),l=mc_read_ptr(la),p=mc_read_ptr(l+pc);
    if(!p)return; int cr=mc_resolve_offset("Controller","ControlRotation");if(cr<0)return;
    uint64_t ca=p+cr; float cx=g_rect.right/2.0f,cy=g_rect.bottom/2.0f,best=1e9f; const PlayerData*bt=nullptr;
    for(auto&pl:g_players){if(pl.is_local||!pl.is_enemy||!pl.on_screen)continue;
        float d=sqrtf((pl.sx-cx)*(pl.sx-cx)+(pl.sy-cy)*(pl.sy-cy));
        if(d<=g_cfg.aimbot_fov&&d<best){best=d;bt=&pl;}
    }
    if(!bt)return;
    double dx=bt->pos[0]-g_cam.loc[0],dy=bt->pos[1]-g_cam.loc[1],dz=(bt->pos[2]+g_cfg.aimbot_target_offset)-g_cam.loc[2];
    double len=sqrt(dx*dx+dy*dy+dz*dz);if(len<1)return;
    double ap=-asin(dz/len)*180/PI,ay=atan2(dy,dx)*180/PI;
    float cp_=mc_read_float(ca),cy_=mc_read_float(ca+4),sm=g_cfg.aimbot_smooth;
    mc_write_float(ca,(float)(cp_+(ap-cp_)*sm));mc_write_float(ca+4,(float)(cy_+(ay-cy_)*sm));
}

// ======================== Window ==============================
static LRESULT CALLBACK wnd_proc(HWND h,UINT m,WPARAM w,LPARAM l){
    if(m==WM_DESTROY){g_running=false;PostQuitMessage(0);return 0;}
    if(m==WM_KEYDOWN&&w==VK_END){g_running=false;DestroyWindow(h);}
    return DefWindowProcW(h,m,w,l);
}

int WINAPI WinMain(HINSTANCE hi,HINSTANCE,LPSTR,int){
    for(int i=0;i<30;i++){if(mc_init())break;Sleep(2000);}
    if(mc_is_attached())mc_init_engine(); load_config();
    if(!init_d2d()) return 1;

    WNDCLASSEXW wc={sizeof(wc)}; wc.style=CS_HREDRAW|CS_VREDRAW; wc.lpfnWndProc=wnd_proc;
    wc.hInstance=hi;wc.hCursor=LoadCursor(0,IDC_ARROW);wc.lpszClassName=WND_CLASS;
    if(!RegisterClassExW(&wc))return 1;
    for(int i=0;i<30;i++){g_game=find_game();if(g_game)break;Sleep(1000);} if(!g_game)return 1;
    GetWindowRect(g_game,&g_rect);

    int w=g_rect.right-g_rect.left,h=g_rect.bottom-g_rect.top;
    g_wnd=CreateWindowExW(WS_EX_LAYERED|WS_EX_TRANSPARENT|WS_EX_TOPMOST|WS_EX_NOACTIVATE,
        WND_CLASS,L"Meccha Overlay",WS_POPUP,g_rect.left,g_rect.top,w,h,0,0,hi,0);
    if(!g_wnd)return 1;
    SetWindowPos(g_wnd,HWND_TOPMOST,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW);

    // Create DIBSection for UpdateLayeredWindow
    HDC ref_dc=GetDC(g_wnd);
    HDC mem_dc=CreateCompatibleDC(ref_dc);
    BITMAPINFO bi={}; bi.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth=w; bi.bmiHeader.biHeight=-h; // top-down
    bi.bmiHeader.biPlanes=1; bi.bmiHeader.biBitCount=32;
    bi.bmiHeader.biCompression=BI_RGB;
    void* bits=nullptr;
    HBITMAP bmp=CreateDIBSection(mem_dc,&bi,DIB_RGB_COLORS,&bits,0,0);
    HGDIOBJ old_bmp=SelectObject(mem_dc,bmp);
    ReleaseDC(g_wnd,ref_dc);

    if(g_cfg.show_cursor)ShowCursor(TRUE);

    // Pre-blend function for alpha
    BLENDFUNCTION blend={AC_SRC_OVER,0,255,AC_SRC_ALPHA};
    POINT zero={0,0}; SIZE size={w,h};

    while(g_running){
        MSG msg; while(PeekMessageW(&msg,0,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}
        if(GetWindowRect(g_game,&g_rect)){
            SetWindowPos(g_wnd,HWND_TOPMOST,g_rect.left,g_rect.top,
                g_rect.right-g_rect.left,g_rect.bottom-g_rect.top,SWP_SHOWWINDOW);
        }
        read_game_data();
        render_d2d(mem_dc,w,h);
        UpdateLayeredWindow(g_wnd,0,0,&size,mem_dc,&zero,0,&blend,ULW_ALPHA);

        if(g_data_tick%3==0) do_aimbot();
        if(GetAsyncKeyState(VK_END)&0x8000){g_running=false;DestroyWindow(g_wnd);}
        Sleep(TICK_MS);
    }

    SelectObject(mem_dc,old_bmp); DeleteObject(bmp); DeleteDC(mem_dc);
    if(g_font)g_font->Release(); if(g_font_sm)g_font_sm->Release();
    if(g_brush)g_brush->Release(); if(g_rt)g_rt->Release();
    if(g_dwrite)g_dwrite->Release(); if(g_d2d)g_d2d->Release();
    mc_cleanup(); return 0;
}
