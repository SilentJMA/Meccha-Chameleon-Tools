#!/usr/bin/env python3
"""
MECCA CHAMELEON TOOLS — External ESP & Camouflage
Fully external overlay for MECCA CHAMELEON (Steam / UE5.6).
"""
import sys
import os
import ctypes

from PyQt5.QtWidgets import QApplication, QMessageBox

from meccha_chameleon_tools.core import MecchaESP
from meccha_chameleon_tools.config import Config, load_config, save_config, CONFIG_FILE
from meccha_chameleon_tools.translations import _tr
from meccha_chameleon_tools.ui import Menu, Overlay
from meccha_chameleon_tools.updater import APP_VERSION as __version__


_DEFAULT_GAME_DIR = r"C:\Program Files (x86)\Steam\steamapps\common\MECCA CHAMELEON\Chameleon\Binaries\Win64"


def get_game_dir(config=None):
    if config and hasattr(config, "game_directory") and config.game_directory:
        return config.game_directory
    return _DEFAULT_GAME_DIR


def _set_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main():
    _set_dpi_aware()
    app = QApplication(sys.argv)

    config = load_config()
    _tr.set_language(config.language)

    try:
        esp = MecchaESP()
    except (RuntimeError, Exception) as e:
        QMessageBox.critical(
            None, "Game Not Found",
            f"Could not connect to MECCA CHAMELEON.\n\n"
            f"Make sure the game is running before launching this tool.\n\n"
            f"Error: {e}"
        )
        sys.exit(1)

    menu = Menu(config, esp)
    overlay = Overlay(esp, config)
    overlay.show()
    menu.show()

    app.aboutToQuit.connect(lambda: (save_config(config), esp.cleanup()))
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
