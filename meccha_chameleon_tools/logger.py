#!/usr/bin/env python3
"""Logging — silent by default, --verbose enables console output."""
import sys
import os
import time

VERBOSE = False
_log_file = None


def init():
    global _log_file
    if "--verbose" in sys.argv or "-v" in sys.argv:
        enable()
    log_path = os.path.join(os.environ.get("APPDATA", "."), "MecchaCamouflage", "debug.log")
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        _log_file = open(log_path, "a", encoding="utf-8")
    except Exception:
        _log_file = None


def enable():
    global VERBOSE
    VERBOSE = True


def _fmt(msg):
    return f"[{time.strftime('%H:%M:%S')}] {msg}"


def info(msg):
    line = _fmt(f"INFO  {msg}")
    if VERBOSE:
        print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def warn(msg):
    line = _fmt(f"WARN  {msg}")
    if VERBOSE:
        print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def error(msg):
    line = _fmt(f"ERROR {msg}")
    if VERBOSE or True:
        print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()


def debug(msg):
    if not VERBOSE:
        return
    line = _fmt(f"DEBUG {msg}")
    print(line)
    if _log_file:
        _log_file.write(line + "\n")
        _log_file.flush()
