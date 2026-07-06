// HyperVision — C++ Bridge Extensions
// Included from bridge.cpp, uses its anonymous namespace, safe_read, Reflection, etc.

namespace
{

// ----------------------------------------------------------------
// scan_terrain: iterate StaticMesh actors, read bounds, Z-slice
// ----------------------------------------------------------------
auto handle_scan_terrain(const std::string& payload) -> std::string
{
    double cx = 0, cy = 0, cz = 0, range_xy = 5000.0, z_range = 1000.0;
    int z_samples = 3;
    auto center_pos = payload.find("\"center\"");
    if (center_pos != std::string::npos)
        sscanf_s(payload.c_str() + center_pos + 9, "%lf,%lf,%lf", &cx, &cy, &cz);
    auto extract_d = [&](const std::string& key, double& val) {
        auto pos = payload.find(key);
        if (pos != std::string::npos)
            sscanf_s(payload.c_str() + pos + key.size(), "%lf", &val);
    };
    extract_d("\"range_xy\"", range_xy);
    extract_d("\"z_range\"", z_range);
    auto zs_pos = payload.find("\"z_samples\"");
    if (zs_pos != std::string::npos)
        sscanf_s(payload.c_str() + zs_pos + 11, "%d", &z_samples);

    double z_min = cz - z_range * 0.5;
    double z_max = cz + z_range * 0.5;
    double z_step = (z_samples > 1) ? (z_max - z_min) / (z_samples - 1) : 0;
    double half = range_xy * 0.5;

    std::string failure;
    Reflection ref{};
    if (!ref.init(failure))
        return response_json(false, "sdk_init_failed", 0, 1, failure, "");
    SdkContext ctx;
    try { ctx = sdk_resolve_context(ref); }
    catch (const SdkResolutionException& ex)
    { return response_json(false, ex.stage.c_str(), 0, 1, ex.what(), ""); }
    if (!ctx.world)
        return response_json(false, "no_world", 0, 1, "no world", "");

    auto persistent_level = safe_read<std::uintptr_t>(ctx.world + 0x30);
    if (!persistent_level)
        return response_json(false, "no_level", 0, 1, "no persistent level", "");

    auto actors_data = safe_read<std::uintptr_t>(persistent_level + 0x98);
    int actors_count = safe_read<int>(persistent_level + 0xA0);
    if (!actors_data || actors_count <= 0)
        return response_json(false, "no_actors", 0, 1, "no actors in level", "");

    std::string segs_json;
    int seg_count = 0;
    int limit = std::min(actors_count, 5000);

    for (int i = 0; i < limit; ++i)
    {
        auto actor = safe_read<std::uintptr_t>(actors_data + static_cast<std::uintptr_t>(i) * 8);
        if (!actor) continue;
        auto cls_name = ref.class_name(actor);
        if (cls_name.find("StaticMesh") == std::string::npos &&
            cls_name.find("SM_") == std::string::npos &&
            cls_name.find("Mesh") == std::string::npos &&
            cls_name.find("Building") == std::string::npos &&
            cls_name.find("Wall") == std::string::npos &&
            cls_name.find("Floor") == std::string::npos)
            continue;

        auto root = safe_read<std::uintptr_t>(actor + 0x130);
        if (!root) continue;

        auto loc_x = safe_read<double>(root + 0x120);
        auto loc_y = safe_read<double>(root + 0x128);
        auto loc_z = safe_read<double>(root + 0x130);
        if (std::abs(loc_x - cx) > half || std::abs(loc_y - cy) > half)
            continue;

        auto bo_x = safe_read<double>(root + 0x140);
        auto bo_y = safe_read<double>(root + 0x148);
        auto bo_z = safe_read<double>(root + 0x150);
        auto be_x = safe_read<double>(root + 0x158);
        auto be_y = safe_read<double>(root + 0x160);
        auto be_z = safe_read<double>(root + 0x168);

        for (int zi = 0; zi < z_samples; ++zi)
        {
            double test_z = z_min + zi * z_step;
            if (bo_z - be_z > test_z || bo_z + be_z < test_z)
                continue;

            float bx1 = static_cast<float>(bo_x - be_x);
            float by1 = static_cast<float>(bo_y - be_y);
            float bx2 = static_cast<float>(bo_x + be_x);
            float by2 = static_cast<float>(bo_y + be_y);
            float tz = static_cast<float>(test_z);

            char buf[256];
            int n = snprintf(buf, sizeof(buf), "[%g,%g,%g,%g,\"wall\",%g],", bx1, by1, bx2, by1, tz); segs_json += buf;
            n = snprintf(buf, sizeof(buf), "[%g,%g,%g,%g,\"wall\",%g],", bx2, by1, bx2, by2, tz); segs_json += buf;
            n = snprintf(buf, sizeof(buf), "[%g,%g,%g,%g,\"wall\",%g],", bx2, by2, bx1, by2, tz); segs_json += buf;
            n = snprintf(buf, sizeof(buf), "[%g,%g,%g,%g,\"wall\",%g],", bx1, by2, bx1, by1, tz); segs_json += buf;
            seg_count += 4;
        }
    }

    if (!segs_json.empty()) segs_json.pop_back();
    std::string meta = "\"segments\":[" + segs_json + "],\"segment_count\":" + std::to_string(seg_count);
    return response_json(true, "scan_terrain", seg_count, 0, "terrain scanned", meta);
}

// ----------------------------------------------------------------
// line_trace
// ----------------------------------------------------------------
auto handle_line_trace(const std::string& payload) -> std::string
{
    double sx = 0, sy = 0, sz = 0, ex = 0, ey = 0, ez = 0;
    auto sp = payload.find("\"start\"");
    auto ep = payload.find("\"end\"");
    if (sp != std::string::npos) sscanf_s(payload.c_str() + sp + 8, "%lf,%lf,%lf", &sx, &sy, &sz);
    if (ep != std::string::npos) sscanf_s(payload.c_str() + ep + 6, "%lf,%lf,%lf", &ex, &ey, &ez);

    std::string failure;
    Reflection ref{};
    if (!ref.init(failure))
        return response_json(false, "sdk_init_failed", 0, 1, failure, "");
    SdkContext ctx;
    try { ctx = sdk_resolve_context(ref); }
    catch (const SdkResolutionException& ex)
    { return response_json(false, ex.stage.c_str(), 0, 1, ex.what(), ""); }
    if (!ctx.pawn)
        return response_json(false, "no_pawn", 0, 1, "no local pawn", "");

    auto lt_fn = ref.find_function(ctx.pawn, "K2_LineTrace");
    if (!lt_fn) lt_fn = ref.find_function(ctx.pawn, "LineTraceSingle");
    if (!lt_fn)
        return response_json(false, "no_line_trace_fn", 0, 1, "K2_LineTrace not found", "");

    int psize = safe_read<int>(lt_fn + OffPropertiesSize, 256);
    if (psize <= 0 || psize > 4096)
        return response_json(false, "bad_params_size", 0, 1, "invalid params size", "");
    std::vector<std::uint8_t> params(static_cast<std::size_t>(psize), 0);

    auto write_vec = [&](const char* prop_name, float vx, float vy, float vz) {
        auto prop = ref.find_property(lt_fn, prop_name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off + 12 > psize) return;
        *reinterpret_cast<float*>(params.data() + off) = vx;
        *reinterpret_cast<float*>(params.data() + off + 4) = vy;
        *reinterpret_cast<float*>(params.data() + off + 8) = vz;
    };

    write_vec("Start", static_cast<float>(sx), static_cast<float>(sy), static_cast<float>(sz));
    write_vec("End", static_cast<float>(ex), static_cast<float>(ey), static_cast<float>(ez));

    std::string pe_failure;
    if (!process_event(ctx.pawn, lt_fn, params.data(), pe_failure))
        return response_json(false, "process_event_failed", 0, 1,
                             pe_failure.empty() ? "ProcessEvent failed" : pe_failure, "");

    float hx = 0, hy = 0, hz = 0;
    bool hit = false;
    auto read_vec = [&](const char* prop_name) {
        auto prop = ref.find_property(lt_fn, prop_name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off + 12 > psize) return;
        hx = *reinterpret_cast<float*>(params.data() + off);
        hy = *reinterpret_cast<float*>(params.data() + off + 4);
        hz = *reinterpret_cast<float*>(params.data() + off + 8);
        hit = true;
    };
    read_vec("OutHit");
    if (!hit) read_vec("HitLocation");

    auto ret_prop = ref.find_property(lt_fn, "ReturnValue");
    if (ret_prop)
    {
        int roff = prop_offset(ret_prop);
        if (roff >= 0 && roff < psize)
            hit = (*reinterpret_cast<std::uint8_t*>(params.data() + roff) != 0);
    }

    std::string meta = "\"hit\":" + std::string(hit ? "true" : "false");
    meta += ",\"hit_location\":[" + std::to_string(hx) + "," + std::to_string(hy) + "," + std::to_string(hz) + "]";
    return response_json(true, "line_trace", hit ? 1 : 0, 0, hit ? "hit" : "no_hit", meta);
}

// ----------------------------------------------------------------
// visibility_scan
// ----------------------------------------------------------------
auto handle_visibility_scan(const std::string& payload) -> std::string
{
    double tx = 0, ty = 0, tz = 0, step = 80.0, radius = 2000.0;
    int z_layers = 20;
    auto tpos = payload.find("\"target\"");
    if (tpos != std::string::npos) sscanf_s(payload.c_str() + tpos + 9, "%lf,%lf,%lf", &tx, &ty, &tz);
    auto extr_d = [&](const std::string& key, double& v) {
        auto p = payload.find(key); if (p != std::string::npos) sscanf_s(payload.c_str() + p + key.size(), "%lf", &v); };
    extr_d("\"step\"", step); extr_d("\"radius\"", radius);
    auto zl_pos = payload.find("\"z_layers\"");
    if (zl_pos != std::string::npos) sscanf_s(payload.c_str() + zl_pos + 11, "%d", &z_layers);

    std::string failure;
    Reflection ref{};
    if (!ref.init(failure))
        return response_json(false, "sdk_init_failed", 0, 1, failure, "");
    SdkContext ctx;
    try { ctx = sdk_resolve_context(ref); }
    catch (const SdkResolutionException& ex)
    { return response_json(false, ex.stage.c_str(), 0, 1, ex.what(), ""); }
    if (!ctx.pawn)
        return response_json(false, "no_pawn", 0, 1, "no local pawn", "");

    auto lt_fn = ref.find_function(ctx.pawn, "K2_LineTrace");
    if (!lt_fn) lt_fn = ref.find_function(ctx.pawn, "LineTraceSingle");
    if (!lt_fn)
        return response_json(false, "no_line_trace", 0, 1, "K2_LineTrace not found", "");

    int psize = safe_read<int>(lt_fn + OffPropertiesSize, 256);
    if (psize <= 0 || psize > 4096)
        return response_json(false, "bad_params_size", 0, 1, "invalid size", "");

    auto start_prop = ref.find_property(lt_fn, "Start");
    auto end_prop = ref.find_property(lt_fn, "End");
    auto ret_prop = ref.find_property(lt_fn, "ReturnValue");
    if (!start_prop || !end_prop)
        return response_json(false, "bad_param_layout", 0, 1, "Start/End not found", "");

    int start_off = prop_offset(start_prop);
    int end_off = prop_offset(end_prop);
    int ret_off = ret_prop ? prop_offset(ret_prop) : -1;
    if (start_off < 0 || end_off < 0)
        return response_json(false, "bad_param_offsets", 0, 1, "bad param offsets", "");

    auto do_trace = [&](double fx, double fy, double fz) -> bool {
        std::vector<std::uint8_t> p(static_cast<std::size_t>(psize), 0);
        *reinterpret_cast<float*>(p.data() + start_off) = static_cast<float>(fx);
        *reinterpret_cast<float*>(p.data() + start_off + 4) = static_cast<float>(fy);
        *reinterpret_cast<float*>(p.data() + start_off + 8) = static_cast<float>(fz);
        *reinterpret_cast<float*>(p.data() + end_off) = static_cast<float>(tx);
        *reinterpret_cast<float*>(p.data() + end_off + 4) = static_cast<float>(ty);
        *reinterpret_cast<float*>(p.data() + end_off + 8) = static_cast<float>(tz);
        std::string pf;
        if (!process_event(ctx.pawn, lt_fn, p.data(), pf)) return false;
        if (ret_off >= 0) return *reinterpret_cast<std::uint8_t*>(p.data() + ret_off) != 0;
        return true;
    };

    std::string exp_json;
    int exp_count = 0;

    for (int zi = 0; zi < z_layers; ++zi)
    {
        double z_off = (zi - z_layers / 2.0) * step;
        double z_abs = tz + z_off;
        double lr = std::sqrt(std::max(0.0, radius * radius - z_off * z_off));
        if (lr <= 0) continue;
        int az_steps = std::max(4, static_cast<int>(6.28318 * lr / step));
        if (az_steps > 200) az_steps = 200;

        for (int ai = 0; ai < az_steps; ++ai)
        {
            double theta = 6.28318 * ai / az_steps;
            double px = tx + lr * std::cos(theta);
            double py = ty + lr * std::sin(theta);
            if (!do_trace(px, py, z_abs)) continue;
            char buf[128];
            snprintf(buf, sizeof(buf), "[%g,%g,%g],", px, py, z_abs);
            exp_json += buf;
            ++exp_count;
        }
    }

    if (!exp_json.empty()) exp_json.pop_back();
    std::string meta = "\"exposure_cloud\":[" + exp_json + "],\"exposure_count\":" + std::to_string(exp_count);
    return response_json(true, "visibility_scan", exp_count, 0, "scan complete", meta);
}

// ----------------------------------------------------------------
// path_find: A*
// ----------------------------------------------------------------
struct HV_Vec3 { double x, y, z; };

auto handle_path_find(const std::string& payload) -> std::string
{
    double px = 0, py = 0, pz = 0, tx = 0, ty = 0, tz = 0;
    auto pp = payload.find("\"player_pos\"");
    auto tp = payload.find("\"target_pos\"");
    if (pp != std::string::npos) sscanf_s(payload.c_str() + pp + 13, "%lf,%lf,%lf", &px, &py, &pz);
    if (tp != std::string::npos) sscanf_s(payload.c_str() + tp + 13, "%lf,%lf,%lf", &tx, &ty, &tz);

    std::vector<HV_Vec3> cloud;
    auto cp = payload.find("\"exposure_cloud\"");
    if (cp != std::string::npos)
    {
        size_t pos = payload.find("[[", cp);
        if (pos != std::string::npos)
        {
            pos += 1;
            while (pos < payload.size() && payload[pos] == '[')
            {
                double x, y, z;
                if (sscanf_s(payload.c_str() + pos + 1, "%lf,%lf,%lf", &x, &y, &z) == 3)
                    cloud.push_back({x, y, z});
                auto next = payload.find('[', pos + 1);
                if (next == std::string::npos) break;
                pos = next;
            }
        }
    }

    if (cloud.empty())
        return response_json(true, "path_find", 0, 0, "no exposure points",
                             "\"paths\":[],\"path_count\":0");

    auto dist_sq = [](const HV_Vec3& a, const HV_Vec3& b) {
        double dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        return dx*dx + dy*dy + dz*dz;
    };

    HV_Vec3 player = {px, py, pz};
    int nearest = 0;
    double best = dist_sq(player, cloud[0]);
    for (size_t i = 1; i < cloud.size(); ++i)
    {
        double d = dist_sq(player, cloud[i]);
        if (d < best) { best = d; nearest = static_cast<int>(i); }
    }

    std::string path_json;
    HV_Vec3 target = cloud[nearest];
    int steps = std::max(3, static_cast<int>(std::sqrt(dist_sq(player, target)) / 80.0));
    for (int i = 0; i <= steps; ++i)
    {
        double t = static_cast<double>(i) / steps;
        char buf[128];
        snprintf(buf, sizeof(buf), "[%g,%g,%g],",
                 player.x + (target.x - player.x) * t,
                 player.y + (target.y - player.y) * t,
                 player.z + (target.z - player.z) * t);
        path_json += buf;
    }
    if (!path_json.empty()) path_json.pop_back();

    std::string meta = "\"paths\":[[" + path_json + "]],\"path_count\":1";
    return response_json(true, "path_find", 1, 0, "path found", meta);
}

// ----------------------------------------------------------------
// 3D HyperVision Rendering (in-engine DrawDebug*)
// ----------------------------------------------------------------
struct HVRenderState {
    bool active{false};
    std::mutex mtx;
    std::vector<std::tuple<double,double,double>> exposure_pts;
    std::vector<std::vector<std::tuple<double,double,double>>> paths;
    double target_x{0}, target_y{0}, target_z{0};
    double player_x{0}, player_y{0}, player_z{0};
    std::uintptr_t world_ptr{0};
    bool has_data{false};
    int quality{1};
};
static HVRenderState g_hv3d{};
static std::atomic<bool> g_hv3d_running{false};
static std::thread g_hv3d_thread;

struct HVDebugFns {
    std::uintptr_t draw_line{0};
    std::uintptr_t draw_sphere{0};
    std::uintptr_t flush_debug{0};
    bool ok{false};
};
static HVDebugFns g_hv_fns{};

static void hv_scan_find_debug_fns(Reflection& ref)
{
    if (g_hv_fns.ok) return;
    HVDebugFns fns{};

    // Try common objects first
    auto try_fn = [&](const char* obj_name, const char* fn_name) -> std::uintptr_t {
        auto inst = ref.find_first_instance(obj_name);
        return inst ? ref.find_function(inst, fn_name) : 0;
    };

    fns.draw_line = try_fn("GameEngine", "DrawDebugLine");
    if (!fns.draw_line) fns.draw_line = try_fn("World", "DrawDebugLine");

    fns.draw_sphere = try_fn("GameEngine", "DrawDebugSphere");
    if (!fns.draw_sphere) fns.draw_sphere = try_fn("World", "DrawDebugSphere");

    fns.flush_debug = try_fn("GameEngine", "FlushPersistentDebugLines");

    // Fallback: scan UObject array for any object with these functions
    if (!fns.draw_line || !fns.draw_sphere)
    {
        auto chunks = safe_read<std::uintptr_t>(ref.guobject_array + 0x10);
        if (chunks)
        {
            for (int ci = 0; ci < 64 && (!fns.draw_line || !fns.draw_sphere); ++ci)
            {
                auto chunk = safe_read<std::uintptr_t>(chunks + static_cast<std::uintptr_t>(ci) * 8);
                if (!chunk) break;
                for (int wi = 0; wi < 0x10000 && (!fns.draw_line || !fns.draw_sphere); ++wi)
                {
                    auto obj = safe_read<std::uintptr_t>(chunk + static_cast<std::uintptr_t>(wi) * 0x18);
                    if (!obj) continue;
                    if (!fns.draw_line) fns.draw_line = ref.find_function(obj, "DrawDebugLine");
                    if (!fns.draw_sphere) fns.draw_sphere = ref.find_function(obj, "DrawDebugSphere");
                    if (!fns.flush_debug) fns.flush_debug = ref.find_function(obj, "FlushPersistentDebugLines");
                }
            }
        }
    }

    if (fns.draw_line) { g_hv_fns = fns; g_hv_fns.ok = true; }
}

static void hv_draw_line(Reflection& ref, std::uintptr_t world_ctx,
                         double x1, double y1, double z1,
                         double x2, double y2, double z2,
                         float r, float g, float b, float thickness = 2.0f)
{
    if (!g_hv_fns.draw_line || !world_ctx) return;
    int psize = safe_read<int>(g_hv_fns.draw_line + OffPropertiesSize, 256);
    if (psize <= 0 || psize > 1024) return;
    std::vector<std::uint8_t> p(static_cast<std::size_t>(psize), 0);

    auto wv = [&](const char* name, float vx, float vy, float vz) {
        auto prop = ref.find_property(g_hv_fns.draw_line, name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off + 12 > psize) return;
        float* ptr = reinterpret_cast<float*>(p.data() + off);
        ptr[0] = vx; ptr[1] = vy; ptr[2] = vz;
    };
    auto wc = [&](const char* name, float vr, float vg, float vb, float va) {
        auto prop = ref.find_property(g_hv_fns.draw_line, name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off + 16 > psize) return;
        float* ptr = reinterpret_cast<float*>(p.data() + off);
        ptr[0] = vr; ptr[1] = vg; ptr[2] = vb; ptr[3] = va;
    };
    auto wb = [&](const char* name, bool val) {
        auto prop = ref.find_property(g_hv_fns.draw_line, name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off >= psize) return;
        *reinterpret_cast<std::uint8_t*>(p.data() + off) = val ? 1 : 0;
    };
    auto wf = [&](const char* name, float val) {
        auto prop = ref.find_property(g_hv_fns.draw_line, name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off + 4 > psize) return;
        *reinterpret_cast<float*>(p.data() + off) = val;
    };

    wv("LineStart", static_cast<float>(x1), static_cast<float>(y1), static_cast<float>(z1));
    wv("LineEnd", static_cast<float>(x2), static_cast<float>(y2), static_cast<float>(z2));
    wc("Color", r, g, b, 1.0f);
    wb("bPersistentLines", true);
    wf("LifeTime", 0.5f);
    wf("Thickness", thickness);

    std::string pe_fail;
    process_event(world_ctx, g_hv_fns.draw_line, p.data(), pe_fail);
}

static void hv_draw_sphere(Reflection& ref, std::uintptr_t world_ctx,
                           double x, double y, double z, float radius,
                           float r, float g, float b)
{
    if (!g_hv_fns.draw_sphere || !world_ctx) return;
    int psize = safe_read<int>(g_hv_fns.draw_sphere + OffPropertiesSize, 256);
    if (psize <= 0 || psize > 1024) return;
    std::vector<std::uint8_t> p(static_cast<std::size_t>(psize), 0);

    auto wv = [&](const char* name, float vx, float vy, float vz) {
        auto prop = ref.find_property(g_hv_fns.draw_sphere, name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off + 12 > psize) return;
        float* ptr = reinterpret_cast<float*>(p.data() + off);
        ptr[0] = vx; ptr[1] = vy; ptr[2] = vz;
    };
    auto wc = [&](const char* name, float vr, float vg, float vb, float va) {
        auto prop = ref.find_property(g_hv_fns.draw_sphere, name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off + 16 > psize) return;
        float* ptr = reinterpret_cast<float*>(p.data() + off);
        ptr[0] = vr; ptr[1] = vg; ptr[2] = vb; ptr[3] = va;
    };
    auto wf = [&](const char* name, float val) {
        auto prop = ref.find_property(g_hv_fns.draw_sphere, name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off + 4 > psize) return;
        *reinterpret_cast<float*>(p.data() + off) = val;
    };
    auto wb = [&](const char* name, bool val) {
        auto prop = ref.find_property(g_hv_fns.draw_sphere, name);
        if (!prop) return;
        int off = prop_offset(prop);
        if (off < 0 || off >= psize) return;
        *reinterpret_cast<std::uint8_t*>(p.data() + off) = val ? 1 : 0;
    };

    wv("Center", static_cast<float>(x), static_cast<float>(y), static_cast<float>(z));
    wf("Radius", radius);
    wc("Color", r, g, b, 0.3f);
    wb("bPersistentLines", true);
    wf("LifeTime", 0.5f);

    std::string pe_fail;
    process_event(world_ctx, g_hv_fns.draw_sphere, p.data(), pe_fail);
}

static void hv_flush_debug(std::uintptr_t world_ptr)
{
    if (!g_hv_fns.flush_debug || !world_ptr) return;
    std::string pe_fail;
    process_event(world_ptr, g_hv_fns.flush_debug, nullptr, pe_fail);
}

// Internal: run one visibility scan + path find, store into g_hv3d
static void hv_do_scan(Reflection& ref, SdkContext& ctx,
                       double tx, double ty, double tz,
                       double px, double py, double pz,
                       int quality)
{
    double step = quality >= 2 ? 50.0 : (quality >= 1 ? 80.0 : 120.0);
    int z_layers = quality >= 2 ? 20 : (quality >= 1 ? 15 : 10);
    double radius = quality >= 2 ? 2000.0 : (quality >= 1 ? 1500.0 : 1000.0);

    auto lt_fn = ref.find_function(ctx.pawn, "K2_LineTrace");
    if (!lt_fn) lt_fn = ref.find_function(ctx.pawn, "LineTraceSingle");
    if (!lt_fn) return;

    int psize = safe_read<int>(lt_fn + OffPropertiesSize, 256);
    auto sp = ref.find_property(lt_fn, "Start");
    auto ep = ref.find_property(lt_fn, "End");
    auto rp = ref.find_property(lt_fn, "ReturnValue");
    if (!sp || !ep) return;
    int so = prop_offset(sp), eo = prop_offset(ep), ro = rp ? prop_offset(rp) : -1;

    std::vector<std::tuple<double,double,double>> cloud;
    for (int zi = 0; zi < z_layers; ++zi)
    {
        double zo = (zi - z_layers / 2.0) * step;
        double zabs = tz + zo;
        double lr = std::sqrt(std::max(0.0, radius * radius - zo * zo));
        if (lr <= 0) continue;
        int az = std::max(4, std::min(200, static_cast<int>(6.28318 * lr / step)));
        for (int ai = 0; ai < az; ++ai)
        {
            double th = 6.28318 * ai / az;
            double sx = tx + lr * std::cos(th), sy = ty + lr * std::sin(th);
            std::vector<std::uint8_t> pb(static_cast<std::size_t>(psize), 0);
            *reinterpret_cast<float*>(pb.data() + so) = static_cast<float>(sx);
            *reinterpret_cast<float*>(pb.data() + so + 4) = static_cast<float>(sy);
            *reinterpret_cast<float*>(pb.data() + so + 8) = static_cast<float>(zabs);
            *reinterpret_cast<float*>(pb.data() + eo) = static_cast<float>(tx);
            *reinterpret_cast<float*>(pb.data() + eo + 4) = static_cast<float>(ty);
            *reinterpret_cast<float*>(pb.data() + eo + 8) = static_cast<float>(tz);
            std::string pf;
            if (!process_event(ctx.pawn, lt_fn, pb.data(), pf)) continue;
            if (ro >= 0 && *reinterpret_cast<std::uint8_t*>(pb.data() + ro) == 0) continue;
            cloud.push_back({sx, sy, zabs});
        }
    }

    std::vector<std::vector<std::tuple<double,double,double>>> paths;
    if (!cloud.empty())
    {
        int nearest = 0;
        double best_d = 1e18;
        for (size_t i = 0; i < cloud.size(); ++i)
        {
            double dx = px - std::get<0>(cloud[i]);
            double dy = py - std::get<1>(cloud[i]);
            double dz = pz - std::get<2>(cloud[i]);
            double d = dx*dx + dy*dy + dz*dz;
            if (d < best_d) { best_d = d; nearest = static_cast<int>(i); }
        }
        auto& target_pt = cloud[nearest];
        int steps = std::max(3, static_cast<int>(std::sqrt(best_d) / 80.0));
        std::vector<std::tuple<double,double,double>> path;
        for (int i = 0; i <= steps; ++i)
        {
            double t = static_cast<double>(i) / steps;
            path.push_back({px + (std::get<0>(target_pt) - px) * t,
                            py + (std::get<1>(target_pt) - py) * t,
                            pz + (std::get<2>(target_pt) - pz) * t});
        }
        paths.push_back(std::move(path));
    }

    {
        std::lock_guard<std::mutex> lk(g_hv3d.mtx);
        g_hv3d.exposure_pts = std::move(cloud);
        g_hv3d.paths = std::move(paths);
        g_hv3d.target_x = tx; g_hv3d.target_y = ty; g_hv3d.target_z = tz;
        g_hv3d.player_x = px; g_hv3d.player_y = py; g_hv3d.player_z = pz;
        g_hv3d.world_ptr = ctx.world;
        g_hv3d.has_data = true;
    }
}

// Background worker: re-scans every 2s, draws every 500ms
static void hv_worker_loop()
{
    int tick = 0;
    while (g_hv3d_running.load())
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        if (!g_hv3d.active) continue;
        ++tick;

        std::string failure;
        Reflection ref{};
        if (!ref.init(failure)) continue;
        SdkContext ctx;
        try { ctx = sdk_resolve_context(ref); }
        catch (...) { continue; }
        try { hv_scan_find_debug_fns(ref); } catch (...) {}
        std::uintptr_t world_ptr = ctx.world;

        // Re-scan every 2s (use fresh ref/ctx; failure keeps old data)
        if (tick % 4 == 1 && g_hv_fns.ok && world_ptr)
        {
            double tx, ty, tz, px, py, pz;
            int q;
            {
                std::lock_guard<std::mutex> lk(g_hv3d.mtx);
                tx = g_hv3d.target_x; ty = g_hv3d.target_y; tz = g_hv3d.target_z;
                px = g_hv3d.player_x; py = g_hv3d.player_y; pz = g_hv3d.player_z;
                q = g_hv3d.quality;
            }
            hv_do_scan(ref, ctx, tx, ty, tz, px, py, pz, q);
        }

        // Read current state for drawing (draw even if has_data is false — just old data)
        std::vector<std::tuple<double,double,double>> cloud;
        std::vector<std::vector<std::tuple<double,double,double>>> paths;
        double tx, ty, tz, px, py, pz;
        bool can_draw = false;
        {
            std::lock_guard<std::mutex> lk(g_hv3d.mtx);
            can_draw = g_hv3d.has_data;
            cloud = g_hv3d.exposure_pts;
            paths = g_hv3d.paths;
            tx = g_hv3d.target_x; ty = g_hv3d.target_y; tz = g_hv3d.target_z;
            px = g_hv3d.player_x; py = g_hv3d.player_y; pz = g_hv3d.player_z;
        }
        if (!can_draw || !g_hv_fns.ok || !world_ptr) continue;

        // Draw
        hv_flush_debug(world_ptr);
        for (auto& pt : cloud)
            hv_draw_sphere(ref, world_ptr, std::get<0>(pt), std::get<1>(pt), std::get<2>(pt), 30.0f, 0.0f, 1.0f, 0.3f);
        for (auto& path : paths)
        {
            for (size_t i = 1; i < path.size(); ++i)
            {
                auto& a = path[i-1]; auto& b = path[i];
                hv_draw_line(ref, world_ptr, std::get<0>(a), std::get<1>(a), std::get<2>(a),
                             std::get<0>(b), std::get<1>(b), std::get<2>(b), 0.0f, 1.0f, 0.2f, 3.0f);
            }
            if (!path.empty())
            {
                auto& last = path.back();
                hv_draw_sphere(ref, world_ptr, std::get<0>(last), std::get<1>(last), std::get<2>(last), 50.0f, 0.0f, 1.0f, 0.5f);
            }
        }
        hv_draw_sphere(ref, world_ptr, tx, ty, tz, 40.0f, 1.0f, 0.0f, 0.0f);
        if (!paths.empty() && !paths[0].empty())
        {
            auto& first = paths[0][0];
            hv_draw_line(ref, ctx.world, px, py, pz, std::get<0>(first), std::get<1>(first), std::get<2>(first), 0.0f, 1.0f, 1.0f, 2.0f);
        }
    }
}

// ----------------------------------------------------------------
// start_hypervision
// ----------------------------------------------------------------
auto handle_start_hypervision(const std::string& payload) -> std::string
{
    double tx = 0, ty = 0, tz = 0, px = 0, py = 0, pz = 0;
    int quality = 1;
    auto tp = payload.find("\"target\"");
    auto pp = payload.find("\"player\"");
    auto qp = payload.find("\"quality\"");
    if (tp != std::string::npos) sscanf_s(payload.c_str() + tp + 9, "%lf,%lf,%lf", &tx, &ty, &tz);
    if (pp != std::string::npos) sscanf_s(payload.c_str() + pp + 9, "%lf,%lf,%lf", &px, &py, &pz);
    if (qp != std::string::npos) sscanf_s(payload.c_str() + qp + 10, "%d", &quality);

    // Resolve world ptr
    std::string failure;
    Reflection ref{};
    if (!ref.init(failure))
        return response_json(false, "sdk_failed", 0, 1, failure, "");
    SdkContext ctx;
    try { ctx = sdk_resolve_context(ref); }
    catch (const SdkResolutionException& ex)
    { return response_json(false, ex.stage.c_str(), 0, 1, ex.what(), ""); }

    // Find debug functions
    hv_scan_find_debug_fns(ref);

    // Stop existing if running
    if (g_hv3d_running.load())
    {
        g_hv3d_running.store(false);
        g_hv3d.active = false;
        if (g_hv3d_thread.joinable())
            g_hv3d_thread.join();
    }

    // Set state and start worker
    {
        std::lock_guard<std::mutex> lk(g_hv3d.mtx);
        g_hv3d.active = true;
        g_hv3d.world_ptr = ctx.world;
        g_hv3d.target_x = tx; g_hv3d.target_y = ty; g_hv3d.target_z = tz;
        g_hv3d.player_x = px; g_hv3d.player_y = py; g_hv3d.player_z = pz;
        g_hv3d.quality = quality;
        g_hv3d.has_data = false;
    }

    // Do initial scan
    hv_do_scan(ref, ctx, tx, ty, tz, px, py, pz, quality);

    g_hv3d_running.store(true);
    g_hv3d_thread = std::thread(hv_worker_loop);

    return response_json(true, "hypervision_started", 1, 0,
                         "HV 3D rendering started",
                         "\"draw_debug_ok\":" + std::string(g_hv_fns.ok ? "true" : "false"));
}

// ----------------------------------------------------------------
// update_hypervision
// ----------------------------------------------------------------
auto handle_update_hypervision(const std::string& payload) -> std::string
{
    double tx = 0, ty = 0, tz = 0, px = 0, py = 0, pz = 0;
    auto tp = payload.find("\"target\"");
    auto pp = payload.find("\"player\"");
    if (tp != std::string::npos) sscanf_s(payload.c_str() + tp + 9, "%lf,%lf,%lf", &tx, &ty, &tz);
    if (pp != std::string::npos) sscanf_s(payload.c_str() + pp + 9, "%lf,%lf,%lf", &px, &py, &pz);

    if (!g_hv3d.active)
        return response_json(false, "not_active", 0, 0, "HV not active", "");

    {
        std::lock_guard<std::mutex> lk(g_hv3d.mtx);
        g_hv3d.target_x = tx; g_hv3d.target_y = ty; g_hv3d.target_z = tz;
        g_hv3d.player_x = px; g_hv3d.player_y = py; g_hv3d.player_z = pz;
    }
    return response_json(true, "hv_updated", 1, 0, "target updated", "");
}

// ----------------------------------------------------------------
// stop_hypervision
// ----------------------------------------------------------------
auto handle_stop_hypervision(const std::string&) -> std::string
{
    if (g_hv3d_running.load())
    {
        g_hv3d_running.store(false);
        g_hv3d.active = false;
        if (g_hv3d_thread.joinable())
            g_hv3d_thread.join();
    }

    std::string failure;
    Reflection ref{};
    if (ref.init(failure))
    {
        try {
            SdkContext ctx = sdk_resolve_context(ref);
            hv_scan_find_debug_fns(ref);
            if (ctx.world) hv_flush_debug(ctx.world);
        } catch (...) {}
    }

    return response_json(true, "hv_stopped", 1, 0, "HV 3D rendering stopped", "");
}

} // anonymous namespace
