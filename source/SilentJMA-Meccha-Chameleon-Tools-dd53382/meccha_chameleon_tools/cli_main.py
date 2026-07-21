#!/usr/bin/env python3
"""CLI entry point for Meccha Chameleon Tools – no Qt5 dependency."""
import os
import sys
import time
import json
import ctypes
import threading
from pathlib import Path

from meccha_chameleon_tools.core import MecchaESP
from meccha_chameleon_tools.config import Config, load_config, save_config
from meccha_chameleon_tools.camouflage import (
    ensure_bridge_ready, paint_now, stop_paint,
    is_bridge_alive, send_preview, send_unpreview,
)
from meccha_chameleon_tools.translations import _tr

KEY_MAP = {
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74,
    "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
    "F11": 0x7A, "F12": 0x7B,
}


def _get_key_state(name):
    vk = KEY_MAP.get(name)
    if vk is None:
        return False
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def _key_down(name, state):
    held = _get_key_state(name)
    if held and not state.get(name):
        state[name] = True
        return True
    if not held:
        state[name] = False
    return False


def cli_main():
    config = load_config()
    _tr.set_language(config.language)

    print("Meccha Chameleon Tools (CLI)")
    print(f"  Process: {config.game_process_name}")
    print(f"  Language: {config.language}")
    print()

    esp = None
    try:
        esp = MecchaESP()
        print("Connected to game.")
    except (RuntimeError, Exception) as e:
        print(f"Could not connect to game: {e}")
        print("Make sure the game is running.")

    print()
    print("Configurable hotkeys:")
    print(f"  Paint:    {config.paint_hotkey}   – paint camouflage")
    print(f"  Stop:     {config.stop_hotkey}    – cancel paint")
    print()
    print("Hold Ctrl+C to exit (or close this window).")

    key_state = {}
    running = True

    def _on_paint():
        print("Painting...")
        err = ensure_bridge_ready(config.game_process_name)
        if err:
            print(f"Bridge error: {err}")
            return
        resp = paint_now(config)
        if resp.get("success"):
            print("Paint complete!")
        else:
            print(f"Paint failed: {resp.get('message', 'unknown')}")

    def _on_preview():
        print("Previewing...")
        err = ensure_bridge_ready(config.game_process_name)
        if err:
            print(f"Bridge error: {err}")
            return
        resp = send_preview(config)
        if resp.get("success"):
            print("Preview applied.")
        else:
            print(f"Preview failed: {resp.get('message', 'unknown')}")

    def _on_unpreview():
        print("Removing preview...")
        resp = send_unpreview(config)
        if resp.get("success"):
            print("Preview restored.")
        else:
            print(f"UnPreview failed: {resp.get('message', 'unknown')}")

    def _on_stop():
        print("Stopping paint...")
        stop_paint()

    def _player_mod_loop():
        last_speed = config.player_speed_mult
        last_jump = config.player_jump_mult
        last_enabled = config.player_mod_enabled
        while running:
            if config.player_mod_enabled and esp:
                if (config.player_speed_mult != last_speed or
                    config.player_jump_mult != last_jump or
                    not last_enabled):
                    esp.player_mod(config.player_speed_mult, config.player_jump_mult)
                    last_speed = config.player_speed_mult
                    last_jump = config.player_jump_mult
                    last_enabled = True
            elif not config.player_mod_enabled and last_enabled and esp:
                esp.player_mod(1.0, 1.0)
                last_enabled = False
            time.sleep(1.0)

    threading.Thread(target=_player_mod_loop, daemon=True).start()

    try:
        while running:
            if _key_down(config.paint_hotkey, key_state):
                threading.Thread(target=_on_paint, daemon=True).start()
            if _key_down(config.stop_hotkey, key_state):
                threading.Thread(target=_on_stop, daemon=True).start()

            if esp and config.enabled and config.teleport_collectible_key:
                tp_vk = ord(config.teleport_collectible_key.upper())
                tp_held = bool(ctypes.windll.user32.GetAsyncKeyState(tp_vk) & 0x8000)
                if tp_held and not key_state.get("_tp"):
                    esp.teleport_collectible(config.teleport_collectible_key)
                    print("Teleported nearest collectible.")
                key_state["_tp"] = tp_held

            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        if esp:
            esp.cleanup()
        save_config(config)


if __name__ == "__main__":
    cli_main()
