#!/usr/bin/env python3
"""Patch bridge.cpp with game-manipulation commands."""

path = r"C:\Users\Ayoub\Downloads\meccha-camouflage-1.0.0\runtime\src\bridge.cpp"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

if "GAME_COMMAND_PATCH_APPLIED" in content:
    print("Patch already applied, skipping.")
    exit(0)

from datetime import datetime, timezone
timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
edits = 0

def apply(name, old, new):
    global content, edits
    if old not in content:
        print(f"FAIL: {name}: anchor not found")
        return False
    content = content.replace(old, new, 1)
    edits += 1
    print(f"OK: {name}")
    return True

# ── Edit 1: Forward declarations ──
apply("Edit 1",
    "    auto start_template_uv_brush_async_job(const std::string& request, const std::shared_ptr<QueuedPaintJob>& queued_job) -> bool;",
    """    auto start_template_uv_brush_async_job(const std::string& request, const std::shared_ptr<QueuedPaintJob>& queued_job) -> bool;
    auto drain_game_commands_on_game_thread() -> void;
    auto execute_game_command_on_game_thread(const std::string& request) -> std::string;
    auto handle_game_command_direct(const std::string& request) -> std::string;
    auto handle_game_teleport(const std::string& payload, Reflection& ref, const SdkContext& ctx) -> std::string;
    auto handle_game_set_fov(const std::string& payload, Reflection& ref, const SdkContext& ctx) -> std::string;
    auto handle_game_kill(const std::string& payload, Reflection& ref, const SdkContext& ctx) -> std::string;
    auto json_extract_string(const std::string& json, const std::string& key) -> std::string;
    auto json_extract_double(const std::string& json, const std::string& key) -> double;
    auto json_extract_bool(const std::string& json, const std::string& key) -> bool;
    auto json_extract_payload(const std::string& full_json) -> std::string;""")

# ── Edit 2: QueuedGameCommand struct ──
apply("Edit 2",
    "    std::atomic<bool> g_dump_cancel_requested{false};",
    """    std::atomic<bool> g_dump_cancel_requested{false};

    struct QueuedGameCommand
    {
        std::string request{};
        std::string response{};
        bool done{false};
    };

    std::mutex g_game_cmd_mutex;
    std::condition_variable g_game_cmd_cv;
    std::vector<std::shared_ptr<QueuedGameCommand>> g_game_cmds;""")

# ── Edit 3: JSON extractor helpers ──
apply("Edit 3",
    "    auto clear_bridge_progress() -> void",
    """    auto json_extract_string(const std::string& json, const std::string& key) -> std::string
    {
        const auto key_start = json.find("\\\"" + key + "\\\"");
        if (key_start == std::string::npos) return {};
        const auto colon = json.find(':', key_start);
        if (colon == std::string::npos) return {};
        const auto value_start = json.find_first_of("\\\"0123456789-tfn", colon + 1);
        if (value_start == std::string::npos) return {};
        if (json[value_start] == '\\\"')
        {
            const auto value_end = json.find('\\\"', value_start + 1);
            if (value_end == std::string::npos) return {};
            return json.substr(value_start + 1, value_end - value_start - 1);
        }
        const auto value_end = json.find_first_of(",}]", value_start);
        if (value_end == std::string::npos) return {};
        return json.substr(value_start, value_end - value_start);
    }

    auto json_extract_double(const std::string& json, const std::string& key) -> double
    {
        const auto str = json_extract_string(json, key);
        if (str.empty()) return 0.0;
        char* end = nullptr;
        return std::strtod(str.c_str(), &end);
    }

    auto json_extract_bool(const std::string& json, const std::string& key) -> bool
    {
        const auto str = json_extract_string(json, key);
        return str == "true";
    }

    auto json_extract_payload(const std::string& full_json) -> std::string
    {
        const auto pay_key = full_json.find("\\\"payload\\\"");
        if (pay_key == std::string::npos) return {};
        const auto colon = full_json.find(':', pay_key);
        if (colon == std::string::npos) return {};
        const auto brace = full_json.find('{', colon);
        if (brace == std::string::npos) return {};
        int depth = 1;
        for (std::size_t i = brace + 1; i < full_json.size(); ++i)
        {
            if (full_json[i] == '{') ++depth;
            else if (full_json[i] == '}') { --depth; if (depth == 0) return full_json.substr(brace, i - brace + 1); }
        }
        return {};
    }

    auto clear_bridge_progress() -> void""")

# ── Edit 4: Game command handler functions ──
# Insert before handle_request
apply("Edit 4",
    "    auto handle_request(const std::string& line) -> std::string\n    {",
    """    auto execute_game_command_on_game_thread(const std::string& request) -> std::string
    {
        std::string failure{};
        if (!install_process_event_hook(failure))
        {
            return response_json(false, failure.c_str(), 0, 1, failure);
        }
        auto job = std::make_shared<QueuedGameCommand>();
        job->request = request;
        {
            std::lock_guard<std::mutex> lock(g_game_cmd_mutex);
            g_game_cmds.push_back(job);
        }
        if (const auto thread_id = g_game_thread_id.load())
        {
            PostThreadMessageW(thread_id, PaintDispatchMessage, 0, 0);
        }
        std::unique_lock<std::mutex> lock(g_game_cmd_mutex);
        const bool completed = g_game_cmd_cv.wait_for(lock, std::chrono::seconds(30), [&]() {
            return job->done;
        });
        if (!completed)
        {
            return response_json(false, "game_thread_dispatch_timeout", 0, 1, "game thread did not process command");
        }
        return job->response;
    }

    auto drain_game_commands_on_game_thread() -> void
    {
        std::vector<std::shared_ptr<QueuedGameCommand>> jobs{};
        {
            std::lock_guard<std::mutex> lock(g_game_cmd_mutex);
            jobs.swap(g_game_cmds);
        }
        for (const auto& job : jobs)
        {
            if (!job) continue;
            const auto response = handle_game_command_direct(job->request);
            {
                std::lock_guard<std::mutex> lock(g_game_cmd_mutex);
                job->response = response;
                job->done = true;
            }
            g_game_cmd_cv.notify_all();
        }
    }

    auto handle_game_teleport(const std::string& payload, Reflection& ref, const SdkContext& ctx) -> std::string
    {
        const double x = json_extract_double(payload, "x");
        const double y = json_extract_double(payload, "y");
        const double z = json_extract_double(payload, "z");

        if (!live_uobject(ctx.pawn))
        {
            return response_json(false, "pawn_unavailable", 0, 1, "local pawn not available");
        }

        const auto set_location_fn = ref.find_function(ctx.pawn, "K2_SetActorLocation");
        if (!set_location_fn)
        {
            return response_json(false, "function_unavailable", 0, 1, "K2_SetActorLocation not found");
        }

        sdk::Actor_K2_SetActorLocation params{};
        params.NewLocation = {x, y, z};
        params.bTeleport = true;

        std::string pe_failure{};
        if (!process_event(ctx.pawn, set_location_fn, reinterpret_cast<std::uint8_t*>(&params), pe_failure))
        {
            return response_json(false, "process_event_failed", 0, 1, pe_failure);
        }

        std::string meta = "\\\"target_x\\\":" + std::to_string(x) +
                           ",\\\"target_y\\\":" + std::to_string(y) +
                           ",\\\"target_z\\\":" + std::to_string(z) +
                           ",\\\"return_value\\\":" + (params.ReturnValue ? "true" : "false");
        return response_json(true, "teleport", 0, 0, "teleported", meta);
    }

    auto handle_game_set_fov(const std::string& payload, Reflection& ref, const SdkContext& ctx) -> std::string
    {
        const double fov = json_extract_double(payload, "fov");
        if (fov < 1.0 || fov > 179.0)
        {
            return response_json(false, "invalid_fov", 0, 1, "FOV must be between 1 and 179");
        }

        if (!live_uobject(ctx.controller))
        {
            return response_json(false, "controller_unavailable", 0, 1, "player controller not available");
        }

        const auto camera_manager = safe_read<std::uintptr_t>(ctx.controller + sdk::FieldOffsets::PlayerController_PlayerCameraManager);
        if (!live_uobject(camera_manager))
        {
            return response_json(false, "camera_manager_unavailable", 0, 1, "PlayerCameraManager not available");
        }

        const auto set_fov_fn = ref.find_function(camera_manager, "SetFOV");
        if (set_fov_fn)
        {
            sdk_call_single_number(ref, camera_manager, "SetFOV", fov);
            return response_json(true, "set_fov", 0, 0, "FOV set via SetFOV function",
                                "\\\"fov\\\":" + std::to_string(fov) + ",\\\"method\\\":\\\"SetFOV\\\"");
        }

        const auto fov_offset = ref.resolve_property_offset("PlayerCameraManager", "FOVAngle");
        if (fov_offset >= 0)
        {
            *reinterpret_cast<float*>(camera_manager + static_cast<std::uintptr_t>(fov_offset)) = static_cast<float>(fov);
            return response_json(true, "set_fov", 0, 0, "FOV set via FOVAngle property",
                                "\\\"fov\\\":" + std::to_string(fov) + ",\\\"method\\\":\\\"FOVAngle\\\"");
        }

        const auto default_fov_offset = ref.resolve_property_offset("PlayerCameraManager", "DefaultFOV");
        if (default_fov_offset >= 0)
        {
            *reinterpret_cast<float*>(camera_manager + static_cast<std::uintptr_t>(default_fov_offset)) = static_cast<float>(fov);
            return response_json(true, "set_fov", 0, 0, "FOV set via DefaultFOV property",
                                "\\\"fov\\\":" + std::to_string(fov) + ",\\\"method\\\":\\\"DefaultFOV\\\"");
        }

        return response_json(false, "fov_method_unavailable", 0, 1,
                            "could not find SetFOV function or FOVAngle/DefaultFOV property");
    }

    auto handle_game_kill(const std::string& payload, Reflection& ref, const SdkContext& ctx) -> std::string
    {
        if (!live_uobject(ctx.pawn))
        {
            return response_json(false, "pawn_unavailable", 0, 1, "local pawn not available");
        }

        const bool kill_enemies = json_extract_bool(payload, "enemies");

        if (kill_enemies)
        {
            return response_json(false, "not_implemented", 0, 1, "enemy kill not yet implemented via bridge");
        }

        {
            const auto destroy_fn = ref.find_function(ctx.pawn, "K2_DestroyActor");
            if (destroy_fn)
            {
                const auto params_size = safe_read<int>(destroy_fn + OffPropertiesSize, 0);
                if (params_size >= 0 && params_size <= 1024)
                {
                    std::vector<std::uint8_t> p(std::max(1, params_size), 0);
                    std::string pe_failure{};
                    if (process_event(ctx.pawn, destroy_fn, p.data(), pe_failure))
                    {
                        return response_json(true, "kill", 0, 0, "K2_DestroyActor called", "\\\"method\\\":\\\"K2_DestroyActor\\\"");
                    }
                }
            }
        }

        {
            const auto pawn_class_name = ref.class_name(ctx.pawn);
            for (const auto* prop_name : {"Health", "HP", "CurrentHealth"})
            {
                const auto offset = ref.resolve_property_offset(pawn_class_name.c_str(), prop_name);
                if (offset >= 0)
                {
                    *reinterpret_cast<float*>(ctx.pawn + static_cast<std::uintptr_t>(offset)) = 0.0f;
                    return response_json(true, "kill", 0, 0,
                                        std::string("set ") + prop_name + " to 0",
                                        "\\\"method\\\":\\\"property_" + std::string(prop_name) + "\\\"");
                }
            }
        }

        {
            const auto suicide_fn = ref.find_function(ctx.pawn, "Suicide");
            if (suicide_fn)
            {
                const auto params_size = safe_read<int>(suicide_fn + OffPropertiesSize, 0);
                if (params_size >= 0 && params_size <= 1024)
                {
                    std::vector<std::uint8_t> p(std::max(1, params_size), 0);
                    std::string pe_failure{};
                    if (process_event(ctx.pawn, suicide_fn, p.data(), pe_failure))
                    {
                        return response_json(true, "kill", 0, 0, "Suicide called", "\\\"method\\\":\\\"Suicide\\\"");
                    }
                }
            }
        }

        {
            const auto damage_fn = ref.find_function(ctx.pawn, "ReceiveDamage");
            if (damage_fn)
            {
                const auto params_size = safe_read<int>(damage_fn + OffPropertiesSize, 0);
                if (params_size > 0 && params_size <= 1024)
                {
                    std::vector<std::uint8_t> p(static_cast<std::size_t>(params_size), 0);
                    for (auto prop = safe_read<std::uintptr_t>(damage_fn + OffChildProperties); prop; prop = safe_read<std::uintptr_t>(prop + OffFFieldNext))
                    {
                        const auto name = ref.names.resolve(safe_read<std::uint32_t>(prop + OffFFieldName));
                        if (name != "ReturnValue")
                        {
                            write_number(ref, prop, p.data(), 99999.0);
                            break;
                        }
                    }
                    std::string pe_failure{};
                    if (process_event(ctx.pawn, damage_fn, p.data(), pe_failure))
                    {
                        return response_json(true, "kill", 0, 0, "ReceiveDamage called", "\\\"method\\\":\\\"ReceiveDamage\\\"");
                    }
                }
            }
        }

        {
            const auto console_fn = ref.find_function(ctx.controller, "ConsoleCommand");
            if (console_fn)
            {
                const auto params_size = safe_read<int>(console_fn + OffPropertiesSize, 0);
                if (params_size > 0 && params_size <= 4096)
                {
                    std::vector<std::uint8_t> p(static_cast<std::size_t>(params_size), 0);
                    std::vector<std::wstring> backing{};
                    for (auto prop = safe_read<std::uintptr_t>(console_fn + OffChildProperties); prop; prop = safe_read<std::uintptr_t>(prop + OffFFieldNext))
                    {
                        const auto name = ref.names.resolve(safe_read<std::uint32_t>(prop + OffFFieldName));
                        if (name == "Command" || name == "command")
                        {
                            sdk_write_fstring_param(prop, p.data(), "kill", backing);
                        }
                    }
                    std::string pe_failure{};
                    if (process_event(ctx.controller, console_fn, p.data(), pe_failure))
                    {
                        return response_json(true, "kill", 0, 0, "ConsoleCommand 'kill'", "\\\"method\\\":\\\"ConsoleCommand\\\"");
                    }
                }
            }
        }

        return response_json(false, "kill_failed", 0, 1, "all kill strategies failed");
    }

    auto handle_game_command_direct(const std::string& request) -> std::string
    {
        std::string failure{};
        Reflection ref{};
        if (!ref.init(failure))
        {
            return response_json(false, failure.c_str(), 0, 1, failure.empty() ? "SDK reflection init failed" : failure);
        }
        SdkContext ctx{};
        try
        {
            ctx = sdk_resolve_context(ref);
        }
        catch (const SdkResolutionException& ex)
        {
            return response_json(false, ex.stage.c_str(), 0, 1, ex.what());
        }

        const std::string payload = json_extract_payload(request);

        if (request.find("\\\"type\\\":\\\"teleport\\\"") != std::string::npos)
        {
            return handle_game_teleport(payload, ref, ctx);
        }
        if (request.find("\\\"type\\\":\\\"set_fov\\\"") != std::string::npos)
        {
            return handle_game_set_fov(payload, ref, ctx);
        }
        if (request.find("\\\"type\\\":\\\"kill\\\"") != std::string::npos)
        {
            return handle_game_kill(payload, ref, ctx);
        }
        return response_json(false, "unknown_game_command", 0, 1, "unknown game command type");
    }

    auto handle_request(const std::string& line) -> std::string
    {""")

# ── Edit 5: Update drain_paint_jobs_on_game_thread ──
# Find the end of drain_paint_jobs_on_game_thread function
marker = "g_paint_jobs_cv.notify_all();"
idx = content.find("    drain_paint_jobs_on_game_thread")
if idx >= 0:
    end_idx = content.find(marker, idx)
    if end_idx >= 0:
        # Find the next 3 closing braces after notify_all
        brace_count = 0
        insert_pos = end_idx + len(marker)
        for _ in range(3):
            pos = content.find("    }", insert_pos)
            if pos == -1:
                break
            insert_pos = pos + 5
            brace_count += 1
        if brace_count >= 2:
            # Insert before the last closing brace (function end)
            # Actually, we need the function closing brace, which is the third one
            # pattern: }
            #          }
            # which ends the for loop and the function
            # Actually the pattern after notify_all is:
            #             }
            #         }
            #     }
            
            # Let me just look for the third closing brace
            pos1 = content.find("}", end_idx + len(marker))
            pos2 = content.find("}", pos1 + 4) if pos1 >= 0 else -1
            pos3 = content.find("}", pos2 + 4) if pos2 >= 0 else -1
            
            if pos3 >= 0 and pos3 - pos2 < 20:
                # Insert before pos3 (which is function closing brace)
                # Check what's between notify_all and here
                between = content[end_idx + len(marker):pos3+1]
                if "drain_game_commands" not in between:
                    content = content[:pos3] + "        drain_game_commands_on_game_thread();\n    " + content[pos3:]
                    edits += 1
                    print("OK: Edit 5")
                else:
                    print("OK: Edit 5 already applied")
            else:
                print(f"FAIL: Edit 5: could not locate function closing brace (pos1={pos1} pos2={pos2} pos3={pos3})")
        else:
            print(f"FAIL: Edit 5: only found {brace_count} closing braces")
    else:
        print("FAIL: Edit 5: notify_all marker not found")
else:
    print("FAIL: Edit 5: drain_paint_jobs not found")

# ── Edit 6: Add new command dispatch ──
idx_pfr = content.find('if (line.find("\\"type\\":\\"paint_full_route\\"")')
if idx_pfr == -1:
    idx_pfr = content.find('"type":"paint_full_route"')

if idx_pfr >= 0:
    # Find the closing brace of this if block
    close_brace = content.find("}", idx_pfr)
    if close_brace >= 0:
        # Check if teleport is already there
        next_part = content[close_brace:close_brace+300]
        if '"type":"teleport"' not in next_part:
            new_cmds = """        if (line.find("\\"type\\":\\"teleport\\"") != std::string::npos)
        {
            return execute_game_command_on_game_thread(line);
        }
        if (line.find("\\"type\\":\\"set_fov\\"") != std::string::npos)
        {
            return execute_game_command_on_game_thread(line);
        }
        if (line.find("\\"type\\":\\"kill\\"") != std::string::npos)
        {
            return execute_game_command_on_game_thread(line);
        }

"""
            content = content[:close_brace+1] + "\n" + new_cmds + content[close_brace+1:]
            edits += 1
            print("OK: Edit 6")
        else:
            print("OK: Edit 6 already applied")
    else:
        print("FAIL: Edit 6: closing brace not found")
else:
    print("FAIL: Edit 6: paint_full_route anchor not found")

# ── Edit 7: Update capabilities list ──
if '"metadata":{"commands":["ping","capabilities","sdk_probe","sdk_deep_probe","paint_full_route","shutdown"],' in content:
    content = content.replace(
        '"metadata":{"commands":["ping","capabilities","sdk_probe","sdk_deep_probe","paint_full_route","shutdown"],',
        '"metadata":{"commands":["ping","capabilities","sdk_probe","sdk_deep_probe","paint_full_route","shutdown","teleport","set_fov","kill"],',
        1
    )
    edits += 1
    print("OK: Edit 7")
else:
    print("FAIL: Edit 7: anchor not found")

# ── Add marker ──
content = content.replace(
    "BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID)",
    f"// GAME_COMMAND_PATCH_APPLIED {timestamp}\nBOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID)"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print(f"\nDone: {edits} edits applied")
