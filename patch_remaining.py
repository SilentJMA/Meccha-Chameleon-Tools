#!/usr/bin/env python3
"""Apply remaining edits to bridge.cpp."""
path = r"C:\Users\Ayoub\Downloads\meccha-camouflage-1.0.0\runtime\src\bridge.cpp"

with open(path, 'r', encoding='utf-8') as f:
    c = f.read()

edits = 0

# Edit 5: Add drain_game_commands to drain_paint_jobs_on_game_thread
old5 = '            g_paint_jobs_cv.notify_all();\n        }\n    }'
new5 = '            g_paint_jobs_cv.notify_all();\n        }\n        drain_game_commands_on_game_thread();\n    }'
if old5 in c:
    c = c.replace(old5, new5, 1)
    edits += 1
    print("Edit 5 OK")
else:
    # Try more flexible approach - find the function
    print("Edit 5: searching for notify_all context...")
    idx = c.find('g_paint_jobs_cv.notify_all()')
    if idx >= 0:
        # Find the next 3 lines
        eol = c.find('\n', idx)
        line2_start = eol + 1
        line2_end = c.find('\n', line2_start)
        line3_start = line2_end + 1
        line3_end = c.find('\n', line3_start)
        fragment = c[idx:line3_end]
        print(f"Found: |{fragment}|")
        # The fragment should be the notify_all line + 2 closing braces
        # Add drain_game_commands before the function closing
        insert_pos = c.find('    }', line3_start)
        if insert_pos >= 0 and insert_pos - line3_start < 20:
            c = c[:insert_pos] + '        drain_game_commands_on_game_thread();\n    ' + c[insert_pos:]
            edits += 1
            print("Edit 5 OK (alternative)")
        else:
            print(f"Edit 5 FAIL: insert_pos={insert_pos}")
    else:
        print("Edit 5 FAIL: notify_all not found")

# Edit 7: Update capabilities
old7 = 'sdk_probe\\",\\"sdk_deep_probe\\",\\"paint_full_route\\",\\"shutdown\\"]'
new7 = 'sdk_probe\\",\\"sdk_deep_probe\\",\\"paint_full_route\\",\\"shutdown\\",\\"teleport\\",\\"set_fov\\",\\"kill\\"]'
if old7 in c:
    c = c.replace(old7, new7, 1)
    edits += 1
    print("Edit 7 OK")
else:
    print("Edit 7 FAIL: anchor not found")

with open(path, 'w', encoding='utf-8') as f:
    f.write(c)
print(f"Done: {edits} remaining edits applied")
