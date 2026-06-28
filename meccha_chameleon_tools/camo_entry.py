#!/usr/bin/env python3
"""Standalone camouflage-only entry point for MecchaCamouflage.exe."""
import sys
import os
import ctypes

from PyQt5.QtWidgets import QApplication, QMessageBox
from PyQt5.QtCore import QTimer

from meccha_chameleon_tools.core import MecchaESP
from meccha_chameleon_tools.config import Config, load_config, save_config
from meccha_chameleon_tools.ui import Menu


def camo_main():
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        pass
    app = QApplication(sys.argv)

    config = load_config()
    try:
        esp = MecchaESP()
    except (RuntimeError, Exception) as e:
        QMessageBox.critical(
            None, "Game Not Found",
            f"Could not connect to the game.\n\n"
            f"Make sure the game is running before launching.\n\n"
            f"Error: {e}"
        )
        sys.exit(1)

    menu = Menu(config, esp, tabs=["Camouflage"])
    menu.setWindowTitle("Meccha Camouflage")
    menu.show()
    app.aboutToQuit.connect(lambda: (save_config(config), esp.cleanup()))
    sys.exit(app.exec_())


if __name__ == "__main__":
    camo_main()
