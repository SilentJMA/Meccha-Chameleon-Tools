#!/usr/bin/env python3
"""Qt5 overlay and menu widgets for MECCHA CHAMELEON ESP."""
import math
import os
import ctypes
import sys
import time
import threading
from typing import Tuple, Optional

from PyQt5.QtWidgets import (
    QApplication, QWidget, QCheckBox, QComboBox, QLabel,
    QVBoxLayout, QHBoxLayout, QPushButton, QFrame,
    QSpinBox, QDoubleSpinBox, QSlider, QListWidget,
    QStackedWidget, QScrollArea, QSizeGrip,
)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QBrush, QPolygonF
from PyQt5.QtCore import QPointF

from meccha_chameleon_tools.core import (
    MecchaESP, rp, ru32, rfloat, wfloat, rvec3, rvec3_f, dist,
    read_array, OFFSETS,
)
from meccha_chameleon_tools.config import Config, save_config, load_config
from meccha_chameleon_tools.translations import _tr, LANGUAGE_NAMES
from meccha_chameleon_tools.camouflage import ensure_bridge_ready, paint_now, paint_start, paint_single, stop_paint, is_bridge_alive, send_preview, send_unpreview
from meccha_chameleon_tools import updater


# ---------------------------------------------------------------------------
# Math helpers
# ---------------------------------------------------------------------------
def rotation_to_axes(rot):
    pitch, yaw, roll = [math.radians(x) for x in rot]
    sp, cp = math.sin(pitch), math.cos(pitch)
    sy, cy = math.sin(yaw), math.cos(yaw)
    sr, cr = math.sin(roll), math.cos(roll)
    forward = (cp * cy, cp * sy, sp)
    right = (sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp)
    up = (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * cy, cr * cp)
    return forward, right, up


def w2s(world_pos, camera, screen_w, screen_h):
    """Project world pos to screen. Returns None only if behind camera."""
    cam_loc = camera["loc"]
    cam_rot = camera["rot"]
    fov = camera["fov"]
    forward, right, up = rotation_to_axes(cam_rot)
    dx = world_pos[0] - cam_loc[0]
    dy = world_pos[1] - cam_loc[1]
    dz = world_pos[2] - cam_loc[2]
    view_x = dx * forward[0] + dy * forward[1] + dz * forward[2]
    view_y = dx * right[0] + dy * right[1] + dz * right[2]
    view_z = dx * up[0] + dy * up[1] + dz * up[2]
    if view_x <= 0.1:
        return None
    aspect = screen_w / screen_h
    tan_hfov = math.tan(math.radians(fov) / 2.0)
    ndc_x = view_y / (view_x * tan_hfov)
    ndc_y = view_z / (view_x * tan_hfov / aspect)
    screen_x = (1.0 + ndc_x) * screen_w / 2.0
    screen_y = (1.0 - ndc_y) * screen_h / 2.0
    return (screen_x, screen_y)


def clamp_screen(x, y, w, h, margin=10):
    """Clamp coordinates within visible area (with margin)."""
    return (max(margin, min(w - margin, x)), max(margin, min(h - margin, y)))


# ---------------------------------------------------------------------------
# Key name mapping (shared between Menu and Overlay)
# ---------------------------------------------------------------------------
KEY_NAMES = {
    0x01: "LMB", 0x02: "RMB", 0x04: "MMB", 0x05: "MB4", 0x06: "MB5",
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x10: "Shift",
    0x11: "Ctrl", 0x12: "Alt", 0x13: "Pause", 0x1B: "Esc", 0x20: "Space",
    0x21: "PageUp", 0x22: "PageDown", 0x23: "End", 0x24: "Home",
    0x25: "Left", 0x26: "Up", 0x27: "Right", 0x28: "Down",
    0x2D: "Insert", 0x2E: "Delete",
    0x30: "0", 0x31: "1", 0x32: "2", 0x33: "3", 0x34: "4",
    0x35: "5", 0x36: "6", 0x37: "7", 0x38: "8", 0x39: "9",
    0x41: "A", 0x42: "B", 0x43: "C", 0x44: "D", 0x45: "E", 0x46: "F",
    0x47: "G", 0x48: "H", 0x49: "I", 0x4A: "J", 0x4B: "K", 0x4C: "L",
    0x4D: "M", 0x4E: "N", 0x4F: "O", 0x50: "P", 0x51: "Q", 0x52: "R",
    0x53: "S", 0x54: "T", 0x55: "U", 0x56: "V", 0x57: "W", 0x58: "X",
    0x59: "Y", 0x5A: "Z",
    0x60: "Num0", 0x61: "Num1", 0x62: "Num2", 0x63: "Num3", 0x64: "Num4",
    0x65: "Num5", 0x66: "Num6", 0x67: "Num7", 0x68: "Num8", 0x69: "Num9",
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5",
    0x75: "F6", 0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10",
    0x7A: "F11", 0x7B: "F12",
    0xBA: ";", 0xBB: "=", 0xBC: ",", 0xBD: "-", 0xBE: ".", 0xBF: "/",
    0xC0: "`", 0xDB: "[", 0xDC: "\\", 0xDD: "]", 0xDE: "'",
}

KEY_VK = {v: k for k, v in KEY_NAMES.items()}


def vk_from_name(name):
    return KEY_VK.get(name, 0x2D)  # default Insert


def name_from_vk(vk):
    return KEY_NAMES.get(vk, f"VK_{vk:02X}")


# ---------------------------------------------------------------------------
# Key recording helper
# ---------------------------------------------------------------------------
class KeyRecorder:
    def __init__(self, on_record):
        self.on_record = on_record
        self.active = False
        self._timer = QTimer()
        self._timer.timeout.connect(self._poll)
        self._start_tick = 0

    def start(self):
        self.active = True
        self._start_tick = ctypes.windll.kernel32.GetTickCount()
        self._timer.start(50)

    def stop(self):
        self.active = False
        self._timer.stop()

    def _poll(self):
        elapsed = ctypes.windll.kernel32.GetTickCount() - self._start_tick
        if elapsed < 300:
            return
        for vk in range(1, 0x100):
            if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                name = name_from_vk(vk)
                self.stop()
                self.on_record(name)
                return
        if elapsed > 5000:
            self.stop()


# ---------------------------------------------------------------------------
# ESP drawing utilities
# ---------------------------------------------------------------------------
def draw_health_bar(painter, x, y, w, h, health_pct, shield_pct, spacing=2):
    """Draw stacked health (green top) and shield (blue bottom) bars."""
    bar_w = max(4, w)
    bar_h = 4
    if shield_pct is not None and shield_pct > 0:
        sy = y + bar_h + spacing
        sfill = int(bar_w * min(shield_pct / 100.0, 1.0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 180))
        painter.drawRect(int(x), int(sy), int(bar_w), bar_h)
        painter.setBrush(QColor(0, 120, 255, 220))
        painter.drawRect(int(x), int(sy), int(sfill), bar_h)
    if health_pct is not None and health_pct >= 0:
        hy = y
        hfill = int(bar_w * min(health_pct / 100.0, 1.0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 180))
        painter.drawRect(int(x), int(hy), int(bar_w), bar_h)
        pct_clamped = max(0.0, min(100.0, float(health_pct or 0)))
        r = int(255 * (1 - pct_clamped / 100.0))
        g = int(255 * (pct_clamped / 100.0))
        painter.setBrush(QColor(r, g, 0, 220))
        painter.drawRect(int(x), int(hy), int(hfill), bar_h)


def draw_2d_box(painter, pos, camera, screen_w, screen_h,
                height_world, half_width_world, rot, color, scale=1.0, thickness=1):
    """Draw a 2D bounding box around a world position with given rotation."""
    h = height_world * scale
    hw = half_width_world * scale
    corners_local = [
        (-hw, 0, -hw), (-hw, 0, hw), (hw, 0, hw), (hw, 0, -hw),
        (-hw, h, -hw), (-hw, h, hw), (hw, h, hw), (hw, h, -hw),
    ]
    pitch, yaw, _ = rot if rot else (0, 0, 0)
    yaw_rad = math.radians(yaw)
    cy, sy = math.cos(yaw_rad), math.sin(yaw_rad)
    screen_points = []
    for lx, ly, lz in corners_local:
        rx = lx * cy - lz * sy
        rz = lx * sy + lz * cy
        wx = pos[0] + rx
        wy = pos[1] + ly
        wz = pos[2] + rz
        s = w2s((wx, wy, wz), camera, screen_w, screen_h)
        if s:
            screen_points.append(s)
    if len(screen_points) < 4:
        return
    xs = [p[0] for p in screen_points]
    ys = [p[1] for p in screen_points]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    painter.setPen(QPen(QColor(*color), thickness))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(int(min_x), int(min_y), int(max_x - min_x), int(max_y - min_y))


def draw_corner_box(painter, pos, camera, screen_w, screen_h,
                    height_world, half_width_world, rot, color, scale=1.0, length_ratio=0.25, thickness=2):
    """Draw a corner-only 2D bounding box (like chameleonEsp DrawBox)."""
    h = height_world * scale
    hw = half_width_world * scale
    corners_local = [
        (-hw, 0, -hw), (-hw, 0, hw), (hw, 0, hw), (hw, 0, -hw),
        (-hw, h, -hw), (-hw, h, hw), (hw, h, hw), (hw, h, -hw),
    ]
    pitch, yaw, _ = rot if rot else (0, 0, 0)
    yaw_rad = math.radians(yaw)
    cy, sy = math.cos(yaw_rad), math.sin(yaw_rad)
    screen_points = []
    for lx, ly, lz in corners_local:
        rx = lx * cy - lz * sy
        rz = lx * sy + lz * cy
        wx = pos[0] + rx
        wy = pos[1] + ly
        wz = pos[2] + rz
        s = w2s((wx, wy, wz), camera, screen_w, screen_h)
        if s:
            screen_points.append(s)
    if len(screen_points) < 4:
        return
    xs = [p[0] for p in screen_points]
    ys = [p[1] for p in screen_points]
    min_x, max_x = int(min(xs)), int(max(xs))
    min_y, max_y = int(min(ys)), int(max(ys))
    bw = max_x - min_x
    bh = max_y - min_y
    if bw < 2 or bh < 2:
        return
    corner = max(4, int(min(bw, bh) * length_ratio))
    pen = QPen(QColor(*color), thickness)
    painter.setPen(pen)
    painter.drawLine(min_x, min_y, min_x + corner, min_y)
    painter.drawLine(min_x, min_y, min_x, min_y + corner)
    painter.drawLine(max_x - corner, min_y, max_x, min_y)
    painter.drawLine(max_x, min_y, max_x, min_y + corner)
    painter.drawLine(min_x, max_y - corner, min_x, max_y)
    painter.drawLine(min_x, max_y, min_x + corner, max_y)
    painter.drawLine(max_x - corner, max_y, max_x, max_y)
    painter.drawLine(max_x, max_y - corner, max_x, max_y)


def draw_skeleton(painter, bone_positions, camera, screen_w, screen_h, color):
    """Draw skeleton lines connecting bones."""
    bone_screen = {}
    for name, pos in bone_positions.items():
        s = w2s(pos, camera, screen_w, screen_h)
        if s:
            bone_screen[name] = s
    connections = [
        ("pelvis", "spine_01"), ("spine_01", "spine_02"),
        ("spine_02", "spine_03"), ("spine_03", "neck_01"),
        ("neck_01", "head"),
        ("clavicle_l", "upperarm_l"), ("upperarm_l", "lowerarm_l"),
        ("lowerarm_l", "hand_l"),
        ("clavicle_r", "upperarm_r"), ("upperarm_r", "lowerarm_r"),
        ("lowerarm_r", "hand_r"),
        ("pelvis", "thigh_l"), ("thigh_l", "calf_l"), ("calf_l", "foot_l"),
        ("pelvis", "thigh_r"), ("thigh_r", "calf_r"), ("calf_r", "foot_r"),
    ]
    painter.setPen(QPen(QColor(*color), 2))
    for a, b in connections:
        if a in bone_screen and b in bone_screen:
            x1, y1 = bone_screen[a]
            x2, y2 = bone_screen[b]
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))


def draw_radar(painter, cam, local_pos, players, radar_cx, radar_cy, radar_size, radar_range, color, opacity):
    """Draw a 2D radar overlay in the corner."""
    half = radar_size / 2
    painter.setPen(QPen(QColor(255, 255, 255, opacity), 1))
    painter.setBrush(QBrush(QColor(0, 0, 0, opacity)))
    painter.drawEllipse(int(radar_cx - half), int(radar_cy - half), radar_size, radar_size)
    painter.drawLine(int(radar_cx - half), int(radar_cy), int(radar_cx + half), int(radar_cy))
    painter.drawLine(int(radar_cx), int(radar_cy - half), int(radar_cx), int(radar_cy + half))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 255, 0, 220))
    painter.drawEllipse(int(radar_cx - 2), int(radar_cy - 2), 5, 5)
    cam_yaw = math.radians(cam["rot"][1])
    for p in players:
        pos = p["pos"]
        dx = pos[0] - local_pos[0]
        dz = pos[2] - local_pos[2]
        d2d = math.sqrt(dx * dx + dz * dz)
        if d2d > radar_range or d2d < 1.0:
            continue
        angle = math.atan2(dx, dz) - cam_yaw
        r = (d2d / radar_range) * (half - 8)
        rx = radar_cx + r * math.sin(angle)
        ry = radar_cy - r * math.cos(angle)
        color_rgba = QColor(*p.get("color", color), 220) if not p["is_local"] else QColor(0, 255, 0, 220)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color_rgba)
        painter.drawEllipse(int(rx - 2), int(ry - 2), 5, 5)


ES = "\u26a0 "


class PaintSignals(QObject):
    status = pyqtSignal(str)
    done = pyqtSignal()


class UpdateSignals(QObject):
    found = pyqtSignal(dict)
    up_to_date = pyqtSignal()
    error = pyqtSignal(str)
    progress = pyqtSignal(int)
    downloaded = pyqtSignal(str)
    download_error = pyqtSignal(str)


class Menu(QWidget):
    # Modern dark palette (single source of truth for the menu theme)
    C = {
        "bg":        "#0f1117",
        "surface":   "#171a23",
        "surface2":  "#1d212c",
        "surface3":  "#252a37",
        "border":    "#2b3140",
        "border2":   "#353c4f",
        "text":      "#d7dbe6",
        "text_dim":  "#8b93a7",
        "text_faint":"#5b6275",
        "accent":    "#5b8cff",
        "accent_d":  "#3f6fe0",
        "accent2":   "#9d7bff",
        "good":      "#41d18f",
        "warn":      "#ffb648",
        "bad":       "#ff6b6b",
        "cyan":      "#46d6e0",
    }

    STYLE = """
        QFrame#menuFrame {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #14171f, stop:1 #0d0f15);
            border: 1px solid #2b3140;
            border-radius: 14px;
        }
        QLabel { color: #d7dbe6; font-size: 11px; background: transparent; }
        QLabel#titleLbl {
            font-size: 16px; font-weight: bold; color: #aeb9ff;
            padding: 2px 0; letter-spacing: 2px;
            background: transparent;
        }
        QCheckBox {
            color: #c5cad8; font-size: 11px; spacing: 9px; padding: 3px 2px;
            background: transparent;
        }
        QCheckBox::indicator {
            width: 16px; height: 16px; border-radius: 4px;
            border: 1px solid #3a4253; background: #14171f;
        }
        QCheckBox::indicator:hover { border-color: #5b8cff; }
        QCheckBox::indicator:checked {
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 #5b8cff, stop:1 #9d7bff);
            border-color: #7d9bff;
        }
        QComboBox {
            background-color: #1d212c; color: #d7dbe6;
            border: 1px solid #2b3140; padding: 5px 10px; border-radius: 6px;
            font-size: 11px; min-height: 24px;
        }
        QComboBox:hover { border-color: #4a5470; }
        QComboBox::drop-down {
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 24px; border-left: 1px solid #2b3140;
            border-top-right-radius: 6px; border-bottom-right-radius: 6px;
        }
        QComboBox::down-arrow { width: 9px; height: 9px; }
        QComboBox QAbstractItemView {
            background-color: #1d212c; color: #d7dbe6;
            border: 1px solid #353c4f; border-radius: 6px;
            selection-background-color: #2f3a5a; selection-color: #fff;
            outline: none; font-size: 11px; padding: 4px;
        }
        QPushButton {
            background-color: #222737; color: #d7dbe6;
            border: 1px solid #2b3140; padding: 7px 12px; border-radius: 7px;
            font-size: 11px;
        }
        QPushButton:hover { background-color: #2c3349; border-color: #4a5470; }
        QPushButton:pressed { background-color: #353d57; }
        QPushButton:disabled { color: #5b6275; background-color: #1a1d27; border-color: #232838; }
        QPushButton#primaryBtn {
            background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                stop:0 #5b8cff, stop:1 #3f6fe0);
            color: #fff; border: 1px solid #6d9bff; font-weight: bold;
        }
        QPushButton#primaryBtn:hover { background: #6d9bff; }
        QPushButton#dangerBtn {
            background-color: #3a2026; color: #ff9b9b; border-color: #5a2f38;
        }
        QPushButton#dangerBtn:hover { background-color: #4d2a31; color: #ffb3b3; }
        QSpinBox, QDoubleSpinBox {
            background-color: #14171f; color: #d7dbe6;
            border: 1px solid #2b3140; padding: 3px 8px; border-radius: 6px;
            font-size: 11px; min-height: 24px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus { border-color: #5b8cff; }
        QSpinBox::up-button, QDoubleSpinBox::up-button,
        QSpinBox::down-button, QDoubleSpinBox::down-button {
            background-color: #222737; border: 1px solid #2b3140; width: 20px;
        }
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
            background-color: #2c3349;
        }
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { width: 7px; height: 7px; }
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { width: 7px; height: 7px; }
        QSlider::groove:horizontal {
            background: #14171f; border: 1px solid #2b3140;
            height: 6px; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 #5b8cff, stop:1 #9d7bff);
            border: 1px solid #7d9bff; width: 15px; height: 15px;
            margin: -5px 0; border-radius: 8px;
        }
        QSlider::handle:horizontal:hover { background: #6d9bff; }
        QSlider::sub-page:horizontal { background: #3f6fe0; border-radius: 3px; }
    """

    def __init__(self, config: Config, esp: MecchaESP, tabs=None):
        super().__init__()
        self.config = config
        self.esp = esp
        self._active_tabs = tabs or [
            "ESP", "HEALTH", "VISUALS", "RADAR", "AIM/ASSIST", "PLAYER", "CAMOUFLAGE"
        ]
        self.setWindowTitle("Meccha Chameleon Tools")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None
        self._key_recorder = KeyRecorder(self._on_key_recorded)
        self._container = None
        self._update_info = None
        self._update_state = "idle"
        self._update_signals = UpdateSignals()
        self._update_signals.found.connect(self._on_update_found)
        self._update_signals.up_to_date.connect(self._on_update_up_to_date)
        self._update_signals.error.connect(self._on_update_error)
        self._update_signals.progress.connect(self._on_update_progress)
        self._update_signals.downloaded.connect(self._on_update_downloaded)
        self._update_signals.download_error.connect(self._on_update_error)
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._build_ui()
        self.resize(660, 760)
        self.setMinimumSize(560, 620)
        QTimer.singleShot(1500, self._check_updates)

    def _close_app(self):
        QApplication.quit()

    # ----- Update checker -------------------------------------------------
    def _style_update_button(self, highlight=False):
        if highlight:
            self.update_btn.setStyleSheet(
                "QPushButton { background: #3f6fe0; color: #fff; border: 1px solid #6d9bff;"
                " border-radius: 6px; font-size: 10px; padding: 3px 10px; }"
                " QPushButton:hover { background: #5b8cff; }"
            )
        else:
            self.update_btn.setStyleSheet(
                "QPushButton { background: #1d212c; color: #8b93a7; border: 1px solid #2b3140;"
                " border-radius: 6px; font-size: 10px; padding: 3px 10px; }"
                " QPushButton:hover { border-color: #4a5470; color: #d7dbe6; }"
            )

    def _refresh_update_button(self):
        """Render the update button to match the current state (survives rebuilds)."""
        state = self._update_state
        if state == "checking":
            self.update_btn.setText(_tr("Checking..."))
            self.update_btn.setEnabled(False)
            self._style_update_button(False)
        elif state == "available" and self._update_info:
            self.update_btn.setText(_tr("\u2b07 Update {version}", version=self._update_info["version"]))
            self.update_btn.setEnabled(True)
            self._style_update_button(True)
        elif state == "downloading":
            self.update_btn.setEnabled(False)
            self._style_update_button(True)
        elif state == "up_to_date":
            self.update_btn.setText(_tr("Up to date"))
            self.update_btn.setEnabled(False)
            self._style_update_button(False)
        elif state == "done":
            self.update_btn.setText(_tr("Download Complete"))
            self.update_btn.setEnabled(True)
            self._style_update_button(True)
        elif state == "error":
            self.update_btn.setText(_tr("Update Failed"))
            self.update_btn.setEnabled(True)
            self._style_update_button(False)
        else:
            self.update_btn.setText(_tr("Check for Updates"))
            self.update_btn.setEnabled(True)
            self._style_update_button(False)

    def _check_updates(self):
        if self._update_state in ("checking", "downloading"):
            return
        self._update_state = "checking"
        self._refresh_update_button()

        def _work():
            try:
                info = updater.check_for_update(updater.APP_VERSION)
                if info:
                    self._update_signals.found.emit(info)
                else:
                    self._update_signals.up_to_date.emit()
            except Exception as e:
                self._update_signals.error.emit(str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _on_update_button_clicked(self):
        state = self._update_state
        if state == "available":
            self._download_update()
        elif state == "done":
            self._reveal_download()
        elif state in ("idle", "up_to_date", "error"):
            self._check_updates()

    def _download_update(self):
        info = self._update_info
        if not info:
            return
        if not info.get("asset_url"):
            import webbrowser
            webbrowser.open(info.get("page_url", updater.RELEASES_PAGE))
            return
        self._update_state = "downloading"
        self._refresh_update_button()
        asset_name = info.get("asset_name") or "Meccha-Chameleon-Tools.exe"
        dest = os.path.join(updater.default_download_dir(), asset_name)
        self._downloaded_path = dest

        def _work():
            try:
                def _cb(done, total):
                    pct = int(done * 100 / total) if total else 0
                    self._update_signals.progress.emit(pct)
                updater.download_update(info["asset_url"], dest, _cb)
                self._update_signals.downloaded.emit(dest)
            except Exception as e:
                self._update_signals.download_error.emit(str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _reveal_download(self):
        path = getattr(self, "_downloaded_path", None)
        if path and os.path.exists(path):
            try:
                import subprocess
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            except Exception:
                pass

    def _on_update_found(self, info):
        self._update_info = info
        self._update_state = "available"
        self._refresh_update_button()

    def _on_update_up_to_date(self):
        self._update_state = "up_to_date"
        self._refresh_update_button()

    def _on_update_error(self, msg):
        self._update_state = "error"
        self._refresh_update_button()

    def _on_update_progress(self, pct):
        self.update_btn.setText(_tr("Downloading... {pct}%", pct=pct))

    def _on_update_downloaded(self, path):
        self._update_state = "done"
        self._downloaded_path = path
        self._refresh_update_button()

    def _switch_language(self, lang_code):
        self.config.language = lang_code
        _tr.set_language(lang_code)
        self._rebuild_ui()

    def _rebuild_ui(self):
        old_pos = self.pos()
        if self._container:
            self._outer_layout.removeWidget(self._container)
            self._container.setParent(None)
            self._container.deleteLater()
            self._container = None
        self._pages = {}
        self._key_recorder = KeyRecorder(self._on_key_recorded)
        self._build_ui()
        self.move(old_pos)

    def _on_key_recorded(self, name):
        self.config.aimbot_key = name
        self.lbl_aim_key.setText(_tr("Aim Key: {key}", key=name))
        self.btn_record_key.setEnabled(True)
        self.btn_record_key.setText(_tr("Record Key"))

    def _on_magnet_key_recorded(self, name):
        self.config.magnet_hold_key = name
        self.lbl_magnet_key.setText(name)
        self.btn_record_magnet.setEnabled(True)
        self.btn_record_magnet.setText(_tr("Record"))

    def _on_tp_key_recorded(self, name):
        self.config.teleport_collectible_key = name
        self.lbl_tp_key.setText(name)
        self.btn_record_tp.setEnabled(True)
        self.btn_record_tp.setText(_tr("Record"))

    def _build_ui(self):
        container = QFrame(self)
        container.setObjectName("menuFrame")
        self._container = container
        container.setStyleSheet(self.STYLE)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        # ---- Header (title + language + resize grip) --------------------
        header = QHBoxLayout()
        header.setSpacing(10)
        logo = QLabel("\u25c8")  # ◈ diamond bullet
        logo.setStyleSheet("color: #5b8cff; font-size: 18px;")
        title = QLabel(_tr("MECCA CHAMELEON TOOLS"))
        title.setObjectName("titleLbl")
        header.addWidget(logo)
        header.addWidget(title)
        header.addStretch()

        self.lang_combo = QComboBox()
        lang_codes = list(LANGUAGE_NAMES.keys())
        self.lang_combo.addItems([LANGUAGE_NAMES[k] for k in lang_codes])
        self.lang_combo.setCurrentIndex(lang_codes.index(self.config.language) if self.config.language in lang_codes else 0)
        self.lang_combo.currentIndexChanged.connect(lambda idx: self._switch_language(lang_codes[idx]))
        self.lang_combo.setFixedWidth(120)
        header.addWidget(self.lang_combo)

        grip = QSizeGrip(container)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("background: transparent;")
        header.addWidget(grip)
        outer.addLayout(header)

        sub = QLabel(_tr("External ESP & camouflage overlay"))
        sub.setStyleSheet(f"color: {self.C['text_faint']}; font-size: 10px; padding: 0 2px;")
        outer.addWidget(sub)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {self.C['border']};")
        outer.addWidget(line)

        # ---- Body (sidebar + stacked pages) -----------------------------
        body = QHBoxLayout()
        body.setSpacing(10)

        self.tab_list = QListWidget()
        self.tab_list.setFixedWidth(124)
        self.tab_list.setFocusPolicy(Qt.NoFocus)
        self.tab_list.setStyleSheet(f"""
            QListWidget {{
                background: {self.C['surface']}; border: 1px solid {self.C['border']};
                border-radius: 10px; padding: 6px; outline: none;
            }}
            QListWidget::item {{
                color: {self.C['text_dim']}; padding: 9px 8px; border-radius: 7px;
                font-size: 11px; font-weight: bold;
            }}
            QListWidget::item:selected {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 #2f3a5a, stop:1 #283150);
                color: #aeb9ff;
                border-left: 3px solid #5b8cff;
            }}
            QListWidget::item:hover:!selected {{
                background: {self.C['surface2']}; color: {self.C['text']};
            }}
            QListWidget::vertical-scrollbar {{ background: #12141c; width: 8px; border-radius: 4px; }}
            QListWidget::vertical-scrollbar-handle {{
                background: {self.C['border2']}; min-height: 20px; border-radius: 4px;
            }}
            QListWidget::vertical-scrollbar-handle:hover {{ background: #444c63; }}
            QListWidget::vertical-scrollbar-add-line,
            QListWidget::vertical-scrollbar-sub-line {{ height: 0px; }}
        """)
        for t in self._active_tabs:
            self.tab_list.addItem(self._tab_item_text(t))
        self.tab_list.currentRowChanged.connect(self._switch_tab)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")

        self._pages = {}
        for tab_name in self._active_tabs:
            page = QWidget()
            page.setStyleSheet("background: transparent;")
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(page)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setStyleSheet("background: transparent;")
            self._pages[tab_name] = page
            self.stack.addWidget(scroll)

        body.addWidget(self.tab_list)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        # ---- Action bar (Save / Load / Close) ---------------------------
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_save = QPushButton(_tr("Save Config"))
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.clicked.connect(self._save_config)
        self.btn_load = QPushButton(_tr("Load Config"))
        self.btn_load.clicked.connect(self._load_config)
        self.btn_close = QPushButton(_tr("Close"))
        self.btn_close.setObjectName("dangerBtn")
        self.btn_close.clicked.connect(self._close_app)

        hint = QLabel(_tr("Ins/F1 toggle \u2022 Drag to move \u2022 END = Exit"))
        hint.setStyleSheet(f"color: {self.C['text_faint']}; font-size: 9px;")
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_load)
        bar.addWidget(self.btn_close)
        bar.addStretch()
        bar.addWidget(hint)
        outer.addLayout(bar)

        # ---- Footer (links + update) ------------------------------------
        footer = QHBoxLayout()
        footer.setSpacing(8)
        github_link = QLabel('<a href="https://github.com/SilentJMA/Meccha-Chameleon-Tools" style="color: #8ab4f8; text-decoration: none; font-size: 9px;">GitHub</a>')
        github_link.setOpenExternalLinks(True)
        release_label = QLabel("v" + updater.APP_VERSION)
        release_label.setStyleSheet(f"color: {self.C['text_faint']}; font-size: 9px;")
        self.update_btn = QPushButton(_tr("Check for Updates"))
        self.update_btn.setCursor(Qt.PointingHandCursor)
        self.update_btn.setFixedHeight(22)
        self.update_btn.clicked.connect(self._on_update_button_clicked)
        self._style_update_button()
        copyright_link = QLabel('<a href="https://github.com/SilentJMA" style="color: #8b93a7; text-decoration: none; font-size: 9px;">\u00a9 2026 SilentJMA</a>')
        copyright_link.setOpenExternalLinks(True)
        footer.addWidget(github_link)
        footer.addStretch()
        footer.addWidget(release_label)
        footer.addWidget(self.update_btn)
        footer.addStretch()
        footer.addWidget(copyright_link)
        outer.addLayout(footer)
        self._refresh_update_button()

        self._outer_layout.addWidget(container)

        if "ESP" in self._active_tabs:
            self._build_esp_tab()
        if "HEALTH" in self._active_tabs:
            self._build_health_tab()
        if "VISUALS" in self._active_tabs:
            self._build_visual_tab()
        if "RADAR" in self._active_tabs:
            self._build_radar_tab()
        if "AIM/ASSIST" in self._active_tabs:
            self._build_aimbot_tab()
        if "PLAYER" in self._active_tabs:
            self._build_player_tab()
        if "CAMOUFLAGE" in self._active_tabs:
            self._build_camouflage_tab()

    # ----- Layout helpers -------------------------------------------------
    def _tab_item_text(self, tab):
        icon = {
            "ESP": "◈",
            "HEALTH": "♥",
            "VISUALS": "✦",
            "RADAR": "◉",
            "AIM/ASSIST": "⊕",
            "PLAYER": "⬡",
            "CAMOUFLAGE": "▣",
        }.get(tab, "•")
        return f"{icon}  {_tr(tab)}"

    def _section_header(self, text, color=None):
        lbl = QLabel(text)
        lbl.setStyleSheet(
            f"font-size: 11px; font-weight: bold; letter-spacing: 1px; "
            f"color: {color or self.C['accent']}; padding: 2px 0;"
        )
        return lbl

    def _card(self, spacing=6, margins=(12, 10, 12, 10)):
        card = QFrame()
        card.setFrameShape(QFrame.StyledPanel)
        card.setStyleSheet(
            f"QFrame {{ background: {self.C['surface']}; border: 1px solid {self.C['border']}; "
            f"border-radius: 10px; }}"
        )
        lo = QVBoxLayout(card)
        lo.setContentsMargins(*margins)
        lo.setSpacing(spacing)
        return card, lo

    def _labeled_row(self, label, widget, label_color=None):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label)
        if label_color:
            lbl.setStyleSheet(f"color: {label_color}; font-size: 11px;")
        row.addWidget(lbl)
        row.addStretch(1)
        row.addWidget(widget)
        return row

    def _key_record_row(self, label, lbl_widget, btn_widget):
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(lbl_widget)
        row.addStretch(1)
        row.addWidget(btn_widget)
        return row

    def _spin(self, value, vmin, vmax, step, on_change, double=False):
        spn = QDoubleSpinBox() if double else QSpinBox()
        spn.setRange(vmin, vmax)
        spn.setSingleStep(step)
        spn.setValue(value)
        spn.valueChanged.connect(on_change)
        return spn

    def _switch_tab(self, idx):
        if 0 <= idx < len(self._active_tabs):
            self.stack.setCurrentIndex(idx)

    def _build_esp_tab(self):
        p = self._pages["ESP"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(10)

        # Master switch
        self.cb_enabled = self._chk(_tr("ESP Enabled"), "enabled")
        self.cb_enabled.setStyleSheet("font-size: 12px; font-weight: bold; color: #aeb9ff;")
        lo.addWidget(self.cb_enabled)

        # Display modes
        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("DISPLAY MODE")))
        row = QHBoxLayout()
        row.setSpacing(6)
        self.cb_dot = self._chk(_tr("Dot"), "dot_esp")
        self.cb_box = self._chk(_tr("2D Box"), "box_esp")
        self.cb_skeleton = self._chk(_tr("Skeleton"), "skeleton_esp")
        self.cb_corner = self._chk(_tr("Corner Box"), "corner_box")
        row.addWidget(self.cb_dot)
        row.addWidget(self.cb_box)
        row.addWidget(self.cb_skeleton)
        row.addWidget(self.cb_corner)
        clo.addLayout(row)

        dr = QHBoxLayout()
        dr.addWidget(QLabel(_tr("Dot Radius:")))
        self.spn_dot = QSpinBox()
        self.spn_dot.setRange(2, 32)
        self.spn_dot.setValue(self.config.dot_radius)
        self.spn_dot.valueChanged.connect(lambda v: setattr(self.config, "dot_radius", v))
        dr.addWidget(self.spn_dot)
        self.cb_dist_scale = self._chk(_tr("Dist. Scaling"), "distance_scaling")
        dr.addStretch(1)
        dr.addWidget(self.cb_dist_scale)
        clo.addLayout(dr)
        lo.addWidget(card)

        # Elements shown
        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("ELEMENTS")))
        for cfg, label in [("show_local", _tr("Show Local Player")), ("show_names", _tr("Show Names")),
                           ("show_distance", _tr("Show Distance")), ("snap_lines", _tr("Snap Lines")),
                           ("enemy_only", _tr("Enemy Only")), ("show_roles", _tr("Show Roles")),
                           ("team_filter", _tr("Team Filter"))]:
            clo.addWidget(self._chk(label, cfg))
        lo.addWidget(card)

        lo.addStretch()

    def _build_health_tab(self):
        p = self._pages["HEALTH"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(10)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("STATUS BARS"), self.C["bad"]))
        self.cb_hp = self._chk(_tr("Health Bar"), "health_bar")
        self.cb_shield = self._chk(_tr("Shield Bar"), "shield_bar")
        clo.addWidget(self.cb_hp)
        clo.addWidget(self.cb_shield)
        lo.addWidget(card)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("BOX GEOMETRY")))
        hr = self._labeled_row(_tr("Model Height:"), self._spin(int(self.config.box_height_world), 50, 250, 1, lambda v: setattr(self.config, "box_height_world", float(v))))
        clo.addLayout(hr)
        yr = self._labeled_row(_tr("Y Offset:"), self._spin(self.config.box_y_offset, -50, 50, 1, lambda v: setattr(self.config, "box_y_offset", v)))
        clo.addLayout(yr)
        lo.addWidget(card)

        lo.addStretch()

    def _build_visual_tab(self):
        p = self._pages["VISUALS"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(10)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("PER-ROLE VISUALS"), self.C["accent2"]))
        self.cb_hunter = self._chk(_tr("Hunter ESP"), "hunter_esp")
        self.cb_survivor = self._chk(_tr("Survivor ESP"), "survivor_esp")
        clo.addWidget(self.cb_hunter)
        clo.addWidget(self.cb_survivor)
        lo.addWidget(card)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("DRAW OPTIONS")))
        for cfg, label in [("draw_all", _tr("Draw All Actors")), ("draw_all_names", _tr("Draw All Names")),
                           ("invincible_detect", _tr("Detect Invincible")),
                           ("disable_buried", _tr("Disable Too Buried")),
                           ("show_background_geo", _tr("Show Background Geometry")),
                           ("show_cursor", _tr("Show Cursor"))]:
            clo.addWidget(self._chk(label, cfg))
        dr = self._labeled_row(_tr("Draw All Range:"),
                               self._spin(int(self.config.draw_all_max_distance), 500, 50000, 500,
                                          lambda v: setattr(self.config, "draw_all_max_distance", float(v))))
        clo.addLayout(dr)
        lo.addWidget(card)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("APPEARANCE")))
        lr = self._labeled_row(_tr("Line Thickness:"),
                               self._spin(self.config.line_thickness, 1, 8, 1,
                                          lambda v: setattr(self.config, "line_thickness", v)))
        clo.addLayout(lr)
        pr = self._labeled_row(_tr("Point Size:"),
                               self._spin(self.config.point_size, 1, 8, 1,
                                          lambda v: setattr(self.config, "point_size", v)))
        clo.addLayout(pr)
        lo.addWidget(card)

        lo.addStretch()

    def _build_radar_tab(self):
        p = self._pages["RADAR"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(10)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("RADAR"), self.C["cyan"]))
        self.cb_radar = self._chk(_tr("Radar Enabled"), "radar_enabled")
        clo.addWidget(self.cb_radar)
        sr = self._labeled_row(_tr("Radar Size:"),
                               self._spin(self.config.radar_size, 80, 400, 1,
                                          lambda v: setattr(self.config, "radar_size", v)))
        clo.addLayout(sr)
        rr = self._labeled_row(_tr("Radar Range:"),
                               self._spin(int(self.config.radar_range), 1000, 50000, 500,
                                          lambda v: setattr(self.config, "radar_range", float(v))))
        clo.addLayout(rr)
        lo.addWidget(card)

        lo.addStretch()

    def _build_aimbot_tab(self):
        p = self._pages["AIM/ASSIST"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(10)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("AIMBOT"), self.C["bad"]))
        self.cb_aimbot = self._chk(_tr("Aimbot Enabled"), "aimbot_enabled")
        self.cb_aim_fov = self._chk(_tr("Show FOV Circle"), "aimbot_show_fov")
        clo.addWidget(self.cb_aimbot)
        clo.addWidget(self.cb_aim_fov)
        kr_lbl = QLabel(_tr("Aim Key: {key}", key=self.config.aimbot_key))
        kr_btn = QPushButton(_tr("Record Key"))
        kr_btn.clicked.connect(self._start_aim_key_record)
        kr = self._key_record_row(None, kr_lbl, kr_btn)
        self.lbl_aim_key = kr_lbl
        self.btn_record_key = kr_btn
        clo.addLayout(kr)
        fr = self._labeled_row(_tr("FOV Radius:"),
                               self._spin(self.config.aimbot_fov, 10, 600, 1,
                                          lambda v: setattr(self.config, "aimbot_fov", v)))
        clo.addLayout(fr)
        sr = self._labeled_row(_tr("Smooth:"),
                               self._spin(self.config.aimbot_smooth, 0.01, 1.0, 0.05,
                                          lambda v: setattr(self.config, "aimbot_smooth", v), double=True))
        clo.addLayout(sr)
        ar = self._labeled_row(_tr("Target Offset:"),
                               self._spin(int(self.config.aimbot_target_offset), -200, 200, 1,
                                          lambda v: setattr(self.config, "aimbot_target_offset", float(v))))
        clo.addLayout(ar)
        lo.addWidget(card)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("MAGNET AIM ASSIST"), self.C["warn"]))
        self.cb_magnet = self._chk(_tr("Magnet Enabled"), "magnet_enabled")
        clo.addWidget(self.cb_magnet)
        mkr_lbl = QLabel(self.config.magnet_hold_key)
        mkr_btn = QPushButton(_tr("Record"))
        mkr_btn.clicked.connect(self._start_magnet_key_record)
        mkr = self._key_record_row(None, mkr_lbl, mkr_btn)
        self.lbl_magnet_key = mkr_lbl
        self.btn_record_magnet = mkr_btn
        clo.addLayout(mkr)
        mfr = self._labeled_row(_tr("Magnet FOV:"),
                                self._spin(self.config.magnet_fov, 10, 300, 1,
                                           lambda v: setattr(self.config, "magnet_fov", v)))
        clo.addLayout(mfr)
        msr = self._labeled_row(_tr("Magnet Strength:"),
                                self._spin(self.config.magnet_strength, 0.1, 1.0, 0.1,
                                           lambda v: setattr(self.config, "magnet_strength", v), double=True))
        clo.addLayout(msr)
        lo.addWidget(card)

        lo.addStretch()

    def _build_player_tab(self):
        p = self._pages["PLAYER"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(10)

        notice = QLabel(_tr("\u26a0 Host Only - These features only work when you are the game host"))
        notice.setStyleSheet(
            f"color: {self.C['warn']}; font-size: 10px; font-weight: bold; "
            f"background-color: #2a2418; padding: 6px 8px; border-radius: 6px; "
            f"border: 1px solid {self.C['border']};"
        )
        notice.setWordWrap(True)
        lo.addWidget(notice)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("PLAYER MODIFICATION"), self.C["good"]))
        self.cb_player_mod = self._chk(_tr("Player Mod Enabled"), "player_mod_enabled")
        clo.addWidget(self.cb_player_mod)
        sr = self._labeled_row(_tr("Speed Multiplier:"),
                               self._spin(self.config.player_speed_mult, 0.5, 10.0, 0.5,
                                          lambda v: setattr(self.config, "player_speed_mult", v), double=True))
        clo.addLayout(sr)
        jr = self._labeled_row(_tr("Jump Multiplier:"),
                               self._spin(self.config.player_jump_mult, 0.5, 10.0, 0.5,
                                          lambda v: setattr(self.config, "player_jump_mult", v), double=True))
        clo.addLayout(jr)
        lo.addWidget(card)

        card, clo = self._card()
        clo.addWidget(self._section_header(_tr("COMMANDS")))
        tkr_lbl = QLabel(self.config.teleport_collectible_key)
        tkr_btn = QPushButton(_tr("Record"))
        tkr_btn.clicked.connect(self._start_tp_key_record)
        tkr = self._key_record_row(None, tkr_lbl, tkr_btn)
        self.lbl_tp_key = tkr_lbl
        self.btn_record_tp = tkr_btn
        clo.addLayout(tkr)
        info = QLabel(_tr("Hold the key above to teleport nearest item to you.\nSet speed/jump mult and enable Player Mod to apply."))
        info.setStyleSheet(f"color: {self.C['text_dim']}; font-size: 10px;")
        info.setWordWrap(True)
        clo.addWidget(info)
        lo.addWidget(card)

        lo.addStretch()

    def _build_camouflage_tab(self):
        p = self._pages["CAMOUFLAGE"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(10)

        hdr = QLabel(_tr("CAMOUFLAGE"))
        hdr.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {self.C['accent2']};")
        lo.addWidget(hdr)

        self.lbl_camo_status = QLabel("Ready")
        self.lbl_camo_status.setWordWrap(True)
        self.lbl_camo_status.setStyleSheet(
            f"color: {self.C['accent2']}; font-size: 11px; font-weight: bold; "
            f"background-color: {self.C['surface']}; padding: 8px 10px; "
            f"border-radius: 8px; border: 1px solid {self.C['border']};"
        )
        lo.addWidget(self.lbl_camo_status)

        self.lbl_bridge_status = QLabel("Bridge: checking...")
        self.lbl_bridge_status.setStyleSheet(f"color: {self.C['text_dim']}; font-size: 10px;")
        lo.addWidget(self.lbl_bridge_status)

        card, clo = self._card(spacing=8)
        for text, color, cmd in [
            (_tr("Start Painting"), self.C["good"], self._on_paint_now),
            (_tr("Stop Painting"), self.C["bad"], self._on_stop_camo),
            (_tr("Review"), self.C["accent"], self._on_preview),
            (_tr("Unreview"), self.C["warn"], self._on_unpreview),
        ]:
            btn = QPushButton(text)
            btn.setStyleSheet(
                f"QPushButton {{ background-color: {self.C['surface2']}; color: {color}; "
                f"border: 1px solid {self.C['border2']}; padding: 9px; border-radius: 8px; "
                f"font-size: 11px; font-weight: bold; }}"
                f" QPushButton:hover {{ background-color: {self.C['surface3']}; border-color: {color}; }}"
            )
            btn.clicked.connect(cmd)
            clo.addWidget(btn)
        lo.addWidget(card)

        lo.addStretch()

        self._bridge_timer = QTimer(self)
        self._bridge_timer.timeout.connect(self._update_bridge_status)
        self._bridge_timer.start(3000)
        QTimer.singleShot(500, self._update_bridge_status)

    def _update_bridge_status(self):
        def _check():
            alive = is_bridge_alive()
            QTimer.singleShot(0, lambda: self._set_bridge_status(alive))
        threading.Thread(target=_check, daemon=True).start()

    def _set_bridge_status(self, alive):
        if alive:
            self.lbl_bridge_status.setText("Bridge: Connected")
            self.lbl_bridge_status.setStyleSheet("color: #8f8; font-size: 10px;")
        else:
            self.lbl_bridge_status.setText("Bridge: Disconnected")
            self.lbl_bridge_status.setStyleSheet("color: #f88; font-size: 10px;")

    def _on_paint_now(self):
        self.lbl_camo_status.setText("Painting...")
        def _do():
            try:
                err = ensure_bridge_ready(self.config.game_process_name)
                if err:
                    self.lbl_camo_status.setText(f"Error: {err}")
                    return
                resp = paint_now(self.config)
                if resp.get("success") is True:
                    self.lbl_camo_status.setText("Paint Complete!")
                else:
                    msg = resp.get("message", "Paint Failed")
                    self.lbl_camo_status.setText(f"Error: {msg}")
            except Exception as e:
                self.lbl_camo_status.setText(f"Error: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _on_stop_camo(self):
        def _do():
            try:
                stop_paint()
            except Exception:
                pass
            QTimer.singleShot(0, lambda: self.lbl_camo_status.setText("Stopped"))
        threading.Thread(target=_do, daemon=True).start()

    def _on_preview(self):
        self.lbl_camo_status.setText("Previewing...")
        def _do():
            try:
                err = ensure_bridge_ready(self.config.game_process_name)
                if err:
                    self.lbl_camo_status.setText(f"Error: {err}")
                    return
                resp = send_preview(self.config)
                if resp.get("success") is True:
                    self.lbl_camo_status.setText("Preview applied.")
                else:
                    msg = resp.get("message", "Preview failed")
                    self.lbl_camo_status.setText(f"Error: {msg}")
            except Exception as e:
                self.lbl_camo_status.setText(f"Error: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _on_unpreview(self):
        self.lbl_camo_status.setText("Unreviewing...")
        def _do():
            try:
                resp = send_unpreview(self.config)
                if resp.get("success") is True:
                    self.lbl_camo_status.setText("Preview restored.")
                else:
                    msg = resp.get("message", "UnPreview failed")
                    self.lbl_camo_status.setText(f"Error: {msg}")
            except Exception as e:
                self.lbl_camo_status.setText(f"Error: {e}")
        threading.Thread(target=_do, daemon=True).start()

    def _chk(self, text, attr):
        cb = QCheckBox(text)
        cb.setChecked(getattr(self.config, attr))
        cb.stateChanged.connect(lambda s, a=attr: setattr(self.config, a, bool(s)))
        return cb

    def _start_aim_key_record(self):
        self.btn_record_key.setEnabled(False)
        self.btn_record_key.setText(_tr("Press key..."))
        self._key_recorder = KeyRecorder(self._on_key_recorded)
        self._key_recorder.start()

    def _start_magnet_key_record(self):
        self.btn_record_magnet.setEnabled(False)
        self.btn_record_magnet.setText(_tr("Press key..."))
        self._key_recorder = KeyRecorder(self._on_magnet_key_recorded)
        self._key_recorder.start()

    def _start_tp_key_record(self):
        self.btn_record_tp.setEnabled(False)
        self.btn_record_tp.setText(_tr("Press key..."))
        self._key_recorder = KeyRecorder(self._on_tp_key_recorded)
        self._key_recorder.start()

    def _save_config(self):
        if save_config(self.config):
            self.btn_save.setText(_tr("Config Saved!"))
            QTimer.singleShot(1500, lambda: self.btn_save.setText(_tr("Save Config")))
        else:
            self.btn_save.setText(_tr("Save Failed!"))
            QTimer.singleShot(1500, lambda: self.btn_save.setText(_tr("Save Config")))

    def _load_config(self):
        loaded = load_config()
        from dataclasses import fields as dc_fields
        for field in dc_fields(self.config):
            if hasattr(loaded, field.name):
                setattr(self.config, field.name, getattr(loaded, field.name))
        self.btn_load.setText(_tr("Config Loaded!"))
        QTimer.singleShot(1500, lambda: self.btn_load.setText(_tr("Load Config")))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() == Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None


# ---------------------------------------------------------------------------
# Overlay widget
# ---------------------------------------------------------------------------
class Overlay(QWidget):
    def __init__(self, esp: MecchaESP, config: Config):
        super().__init__()
        self.esp = esp
        self.config = config
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setWindowTitle("Meccha Chameleon Tools - Overlay")
        self._key_states = {}
        self._cursor_shown = True
        self._tp_key_state = False
        self._player_mod_active = False
        self._camo_notification = ""
        self._camo_notification_tick = 0

        # ESP data is produced by a background worker so the paint thread never
        # blocks on memory reads (fixes lag) and keeps camera+positions coherent.
        self._snapshot = {"cam": None, "players": [], "actors": [], "ok": False}
        self._snapshot_lock = threading.Lock()
        self._cached_w = 1920
        self._cached_h = 1080
        self._tracked = {}          # ps key -> {"data":..., "last_seen": monotonic}
        self._esp_running = True
        self._esp_thread = threading.Thread(target=self._esp_worker, daemon=True)
        self._esp_thread.start()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_overlay)
        self.timer.start(16)

        self.game_hwnd = self._find_game_window()
        self._resize_to_game()
        self._resize_counter = 0

        self.key_timer = QTimer(self)
        self.key_timer.timeout.connect(self._poll_keys)
        self.key_timer.start(50)

    # How long (seconds) a player keeps being drawn after the last successful
    # read, so momentary read failures never make the ESP flicker/disappear.
    PLAYER_GRACE_S = 0.5

    def _find_game_window(self):
        try:
            import win32gui
            return win32gui.FindWindow(None, "Chameleon  ")
        except Exception:
            return 0

    def _resize_to_game(self):
        try:
            import win32gui
            if self.game_hwnd:
                rect = win32gui.GetClientRect(self.game_hwnd)
                tl = win32gui.ClientToScreen(self.game_hwnd, (rect[0], rect[1]))
                br = win32gui.ClientToScreen(self.game_hwnd, (rect[2], rect[3]))
                self.setGeometry(tl[0], tl[1], br[0] - tl[0], br[1] - tl[1])
            else:
                self.setGeometry(0, 0, 1920, 1080)
        except Exception:
            self.setGeometry(0, 0, 1920, 1080)

    def update_overlay(self):
        # Cache dims on the GUI thread so the worker never touches QWidget geometry.
        self._cached_w = self.width()
        self._cached_h = self.height()
        # Resizing does win32 calls; no need to do it every frame.
        self._resize_counter = getattr(self, "_resize_counter", 0) + 1
        if self._resize_counter % 15 == 0:
            self._resize_to_game()
        self.update()

    def closeEvent(self, event):
        self._esp_running = False
        super().closeEvent(event)

    def _poll_keys(self):
        VK_INSERT = 0x2D
        VK_END = 0x23
        for vk, name in [(VK_INSERT, "insert"), (0x70, "f1")]:
            state = ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
            if state and not self._key_states.get(name):
                for w in QApplication.topLevelWidgets():
                    if isinstance(w, Menu):
                        w.setVisible(not w.isVisible())
                        break
            self._key_states[name] = bool(state)
        paint_vk = vk_from_name(self.config.paint_hotkey)
        paint_down = bool(ctypes.windll.user32.GetAsyncKeyState(paint_vk) & 0x8000)
        if paint_down and not self._key_states.get("camo_paint"):
            import threading
            threading.Thread(target=self._run_paint, daemon=True).start()
        self._key_states["camo_paint"] = paint_down
        stop_vk = vk_from_name(self.config.stop_hotkey)
        stop_down = bool(ctypes.windll.user32.GetAsyncKeyState(stop_vk) & 0x8000)
        if stop_down and not self._key_states.get("camo_stop"):
            stop_paint()
        self._key_states["camo_stop"] = stop_down
        end_down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_END) & 0x8000)
        if end_down and not self._key_states.get("end"):
            QApplication.quit()
        self._key_states["end"] = end_down
        cursor_should_be = not self.config.show_cursor
        if cursor_should_be != self._cursor_shown:
            while ctypes.windll.user32.ShowCursor(cursor_should_be) >= 0:
                pass
            while ctypes.windll.user32.ShowCursor(not cursor_should_be) < 0:
                pass
            ctypes.windll.user32.ShowCursor(cursor_should_be)
            self._cursor_shown = cursor_should_be
        tp_vk = vk_from_name(self.config.teleport_collectible_key)
        tp_down = bool(ctypes.windll.user32.GetAsyncKeyState(tp_vk) & 0x8000)
        if tp_down and not self._tp_key_state:
            self.esp.teleport_collectible(self.config.teleport_collectible_key)
        self._tp_key_state = tp_down
        if self.config.player_mod_enabled and not self._player_mod_active:
            self.esp.player_mod(self.config.player_speed_mult, self.config.player_jump_mult)
            self._player_mod_active = True
        elif not self.config.player_mod_enabled and self._player_mod_active:
            self.esp.player_mod(1.0, 1.0)
            self._player_mod_active = False

    # -----------------------------------------------------------------------
    # Background ESP reader — keeps all memory reads off the paint thread.
    # -----------------------------------------------------------------------
    def _esp_worker(self):
        while self._esp_running:
            try:
                if not self.config.enabled:
                    with self._snapshot_lock:
                        self._snapshot = {"cam": None, "players": [], "actors": [], "ok": False, "off": True}
                    self._tracked.clear()
                    time.sleep(0.05)
                    continue
                snap = self._build_snapshot()
                if snap is not None:
                    with self._snapshot_lock:
                        self._snapshot = snap
                    self._apply_aim(snap)
            except Exception:
                # Never let the worker die; keep last snapshot on transient errors.
                pass
            time.sleep(0.002)

    def _build_snapshot(self):
        cam = self.esp.get_camera()
        if not cam:
            return {"cam": None, "players": [], "actors": [], "ok": False, "off": False}

        cfg = self.config
        now = time.monotonic()
        current = {}
        try:
            for pdata in self.esp.iter_players(
                include_local=cfg.show_local,
                team_filter=cfg.team_filter,
                enemy_only=cfg.enemy_only,
            ):
                is_local = pdata["is_local"]
                actor = pdata["actor"]
                ps = pdata["player_state"]
                is_hunter = pdata.get("is_hunter", False)
                is_survivor = pdata.get("is_survivor", False)

                entry = {
                    "is_local": is_local,
                    "pos": pdata["pos"],
                    "actor": actor,
                    "player_state": ps,
                    "idx": pdata["idx"],
                    "role": pdata.get("role", "Unknown"),
                    "is_enemy": pdata.get("is_enemy", False),
                    "is_hunter": is_hunter,
                    "is_survivor": is_survivor,
                    "invincible": False,
                    "visible": None,
                    "rot": None,
                    "bones": None,
                    "health": None,
                }

                if cfg.invincible_detect and not is_local:
                    entry["invincible"] = self.esp.get_invincible(actor)
                if (not is_local) and cfg.enemy_only and not is_hunter and not is_survivor:
                    entry["visible"] = self.esp._is_visible(actor)
                if actor and (cfg.box_esp or cfg.corner_box):
                    entry["rot"] = self.esp.get_actor_root_rotation(actor)
                if cfg.skeleton_esp and actor and not is_local:
                    bones = self.esp.get_skeleton_positions(actor)
                    if not bones:
                        bones = self.esp.get_skeleton_positions_by_indices(actor, cfg.bone_indices)
                    entry["bones"] = bones
                if cfg.health_bar or cfg.shield_bar:
                    entry["health"] = self.esp.get_health(actor, ps)

                current[ps] = entry
                self._tracked[ps] = {"data": entry, "last_seen": now}
        except Exception:
            pass

        # Persistence: include recently-seen players that were missed this cycle
        # so momentary read failures never make the ESP flicker/disappear.
        players = []
        for ps, tracked in list(self._tracked.items()):
            if ps in current:
                players.append(current[ps])
            elif now - tracked["last_seen"] <= self.PLAYER_GRACE_S:
                players.append(tracked["data"])
            else:
                del self._tracked[ps]

        actors = []
        if cfg.draw_all:
            try:
                for adata in self.esp.iter_actors(max_actors=500, class_filter="Collectible"):
                    d = dist(adata["pos"], cam["loc"])
                    if d > cfg.draw_all_max_distance:
                        continue
                    actors.append({"pos": adata["pos"], "class_name": adata.get("class_name", "")})
            except Exception:
                pass

        best_target = None
        if cfg.aimbot_enabled or cfg.magnet_enabled:
            try:
                magnet_active = cfg.magnet_enabled and self._magnet_key_held()
                if magnet_active:
                    fov = cfg.magnet_fov
                elif cfg.aimbot_enabled:
                    fov = cfg.aimbot_fov
                else:
                    fov = 0
                best_target = self._find_best_target(cam, self._cached_w, self._cached_h, fov if fov > 0 else None)
            except Exception:
                best_target = None

        return {"cam": cam, "players": players, "actors": actors,
                "best_target": best_target, "ok": True, "off": False}

    def _apply_aim(self, snap):
        cfg = self.config
        best_target = snap.get("best_target")
        if not best_target:
            return
        if cfg.magnet_enabled and self._magnet_key_held():
            self._magnet_at(best_target[0], best_target[1])
        elif cfg.aimbot_enabled and self._aim_key_held():
            self._aim_at(best_target[0], best_target[1])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Consolas", 10)
        painter.setFont(font)

        w = self.width()
        h = self.height()

        with self._snapshot_lock:
            snap = self._snapshot

        if snap.get("off") or not self.config.enabled:
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(10, 20, _tr("ESP OFF"))
            return

        cam = snap.get("cam")
        if not cam:
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(10, 20, _tr("NO CAMERA"))
            return

        all_players = snap.get("players", [])

        local_pos = None
        local_is_hunter = None
        if all_players:
            for p in all_players:
                if p["is_local"]:
                    local_pos = p["pos"]
                    local_is_hunter = p["is_hunter"]
                    break

        for pdata in all_players:
            is_local = pdata["is_local"]
            pos = pdata["pos"]
            actor = pdata["actor"]
            ps = pdata["player_state"]
            idx = pdata["idx"]
            role = pdata.get("role", "Unknown")
            is_enemy = pdata.get("is_enemy", False)

            d = dist(pos, cam["loc"])
            scale = 1.0
            if self.config.distance_scaling and d > 0:
                scale = self.config.scale_reference_dist / d
                scale = max(0.3, min(scale, 3.0))

            screen_center = w2s(pos, cam, w, h)
            if not screen_center:
                continue

            sx, sy = screen_center
            sy += self.config.box_y_offset

            is_hunter = pdata.get("is_hunter", False)
            is_survivor = pdata.get("is_survivor", False)
            if not is_local:
                if is_hunter and not self.config.hunter_esp:
                    continue
                if is_survivor and not self.config.survivor_esp:
                    continue
            invincible = pdata.get("invincible", False)
            if is_local:
                color = self.config.local_color
            elif invincible:
                color = self.config.invincible_color
            elif is_hunter:
                color = self.config.hunter_visual_color
            elif is_survivor:
                color = self.config.survivor_visual_color
            else:
                if self.config.enemy_only:
                    if pdata.get("visible"):
                        color = self.config.visible_color
                    else:
                        color = self.config.not_visible_color
                else:
                    color = self.config.enemy_color

            dsx, dsy = clamp_screen(sx, sy - self.config.box_y_offset, w, h)
            dsy += self.config.box_y_offset

            if self.config.dot_esp:
                radius = int(self.config.dot_radius * scale)
                self._draw_dot(painter, dsx, dsy, max(2, radius), color)

            rot = pdata.get("rot")
            hw = self.config.box_height_world / 3.0
            pen_width = max(1, self.config.line_thickness)
            if self.config.box_esp and not self.config.corner_box:
                draw_2d_box(painter, pos, cam, w, h,
                            self.config.box_height_world, hw, rot, color, scale, pen_width)
            if self.config.corner_box:
                draw_corner_box(painter, pos, cam, w, h,
                                self.config.box_height_world, hw, rot, color, scale, 0.25, pen_width)

            if self.config.skeleton_esp and not is_local:
                bones = pdata.get("bones")
                if bones:
                    draw_skeleton(painter, bones, cam, w, h, self.config.skeleton_color)

            if self.config.health_bar or self.config.shield_bar:
                health_info = pdata.get("health")
                if health_info and health_info[0] is not None:
                    hp, sh = health_info
                    bar_x = dsx - 12 * scale
                    bar_y = dsy - 20 * scale
                    draw_health_bar(painter, bar_x, bar_y, 24 * scale, 4, hp, sh if self.config.shield_bar else None)

            if self.config.snap_lines:
                painter.setPen(QPen(QColor(*color), 1))
                painter.drawLine(int(w / 2), int(h), int(sx), int(sy))

            label_parts = []
            if self.config.show_names:
                label_parts.append(_tr("YOU") if is_local else _tr("Enemy {idx}", idx=idx))
            if self.config.show_roles and role != "Unknown":
                label_parts.append(_tr(role))
            if invincible:
                label_parts.append(_tr("INVINCIBLE"))
            if self.config.show_distance:
                dm = int(d / 100)
                label_parts.append(f"{dm}m")
            if label_parts:
                painter.setPen(QPen(QColor(*color)))
                text = " | ".join(label_parts)
                label_x = int(dsx + self.config.dot_radius * scale + 4)
                label_y = int(dsy)
                painter.drawText(label_x, label_y, text)

        if self.config.draw_all:
            actor_count = 0
            for adata in snap.get("actors", []):
                s = w2s(adata["pos"], cam, w, h)
                if not s:
                    continue
                actor_count += 1
                act_color = (100, 255, 100)
                painter.setPen(QPen(QColor(*act_color), 1))
                sx_a, sy_a = int(s[0]), int(s[1])
                painter.drawEllipse(sx_a - 2, sy_a - 2, 4, 4)
                if self.config.draw_all_names:
                    cname = adata["class_name"][:20] if adata["class_name"] else "Actor"
                    painter.drawText(sx_a + 4, sy_a + 4, cname)
            if actor_count > 0:
                painter.setPen(QPen(QColor(150, 255, 150)))
                painter.drawText(w - 200, 60, _tr("Items: {count}", count=actor_count))

        non_local = [p for p in all_players if not p["is_local"]]
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(10, 20, _tr("Players: {count}", count=len(non_local)))

        # Aim is applied in the background worker; here we only draw the FOV ring.
        if self.config.aimbot_enabled and self.config.aimbot_show_fov:
            cx, cy = w / 2, h / 2
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(
                int(cx - self.config.aimbot_fov),
                int(cy - self.config.aimbot_fov),
                self.config.aimbot_fov * 2,
                self.config.aimbot_fov * 2,
            )

        painter.setPen(QPen(QColor(255, 255, 255, 40)))
        wm_font = QFont("Segoe UI", 8)
        painter.setFont(wm_font)
        painter.drawText(w - 160, h - 10, _tr("Meccha Chameleon Tools"))
        painter.setFont(font)

        if self._camo_notification:
            elapsed = ctypes.windll.kernel32.GetTickCount() - self._camo_notification_tick
            if elapsed < 5000:
                painter.setPen(QPen(QColor(255, 200, 100, 220)))
                notif_font = QFont("Consolas", 12)
                painter.setFont(notif_font)
                painter.drawText(12, 50, self._camo_notification)
                painter.setFont(font)
            else:
                self._camo_notification = ""

        if self.config.radar_enabled and local_pos:
            radar_x = w - self.config.radar_size - 20
            radar_y = 20 + self.config.radar_size // 2
            enemy_list = [p for p in all_players if not p["is_local"]]
            for p in enemy_list:
                p["color"] = self.config.enemy_color
            draw_radar(painter, cam, local_pos, enemy_list,
                       radar_x, radar_y,
                       self.config.radar_size, self.config.radar_range,
                       self.config.radar_color, self.config.radar_opacity)

    def _draw_dot(self, painter, cx, cy, r, color):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*color))
        painter.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)

    # -----------------------------------------------------------------------
    # Aimbot
    # -----------------------------------------------------------------------
    def _run_paint(self):
        """Paint operation triggered by hotkey."""
        err = ensure_bridge_ready(self.config.game_process_name)
        if err:
            self._camo_notification = f"Camo: {err}"
        else:
            result = paint_now(self.config)
            if result.get("success") is True:
                self._camo_notification = "Camo: Painting..."
            else:
                msg = result.get("message", "Camo failed")
                self._camo_notification = f"Camo: {msg}"
        self._camo_notification_tick = ctypes.windll.kernel32.GetTickCount()

    def _aim_key_held(self):
        vk = vk_from_name(self.config.aimbot_key)
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

    def _magnet_key_held(self):
        vk = vk_from_name(self.config.magnet_hold_key)
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

    def _find_best_target(self, camera, screen_w, screen_h, fov_override=None):
        world = self.esp._get_world()
        local_pc = self.esp._get_local_controller(world) if world else 0
        local_pawn = rp(self.esp.pm, local_pc + self.esp.offsets["APlayerController::AcknowledgedPawn"]) if local_pc else 0
        local_pos = None
        if local_pawn:
            root = rp(self.esp.pm, local_pawn + self.esp.offsets["AActor::RootComponent"])
            if root:
                local_pos = rvec3(self.esp.pm, root + self.esp.offsets["USceneComponent::RelativeLocation"])

        if not local_pawn:
            return None
        cx, cy = screen_w / 2, screen_h / 2
        cam_loc = camera["loc"]
        best_dist = float("inf")
        best_target = None
        for pdata in self.esp.iter_players(include_local=False, team_filter=self.config.team_filter):
            if pdata["is_local"]:
                continue
            pos = pdata["pos"]
            if local_pos:
                dself = dist(pos, local_pos)
                if dself < 150.0:
                    continue
            dcam = dist(pos, cam_loc)
            if dcam < 100.0:
                continue
            aim_pos = (
                pos[0], pos[1],
                pos[2] + self.config.aimbot_target_offset,
            )
            s = w2s(aim_pos, camera, screen_w, screen_h)
            if not s:
                continue
            dx = s[0] - cx
            dy = s[1] - cy
            d = math.sqrt(dx * dx + dy * dy)
            max_fov = fov_override if fov_override is not None else self.config.aimbot_fov
            if d <= max_fov and d < best_dist:
                best_dist = d
                best_target = (aim_pos, camera)
        return best_target

    def _vector_to_rotation(self, vec):
        x, y, z = vec
        length = math.sqrt(x * x + y * y + z * z)
        if length == 0:
            return (0.0, 0.0, 0.0)
        x, y, z = x / length, y / length, z / length
        pitch = -math.degrees(math.asin(z))
        yaw = math.degrees(math.atan2(y, x))
        return (pitch, yaw, 0.0)

    def _read_control_rotation(self):
        world = self.esp._get_world()
        if not world:
            return None
        pc = self.esp._get_local_controller(world)
        if not pc:
            return None
        addr = pc + self.esp.offsets["AController::ControlRotation"]
        return (
            rfloat(self.esp.pm, addr),
            rfloat(self.esp.pm, addr + 4),
            rfloat(self.esp.pm, addr + 8),
        )

    def _write_control_rotation(self, rot):
        world = self.esp._get_world()
        if not world:
            return False
        pc = self.esp._get_local_controller(world)
        if not pc:
            return False
        addr = pc + self.esp.offsets["AController::ControlRotation"]
        wfloat(self.esp.pm, addr, rot[0])
        wfloat(self.esp.pm, addr + 4, rot[1])
        wfloat(self.esp.pm, addr + 8, rot[2])
        return True

    def _aim_at(self, target_pos, camera):
        if not camera:
            return
        current = self._read_control_rotation()
        if current is None:
            return
        dx = target_pos[0] - camera["loc"][0]
        dy = target_pos[1] - camera["loc"][1]
        dz = target_pos[2] - camera["loc"][2]
        target_rot = self._vector_to_rotation((dx, dy, dz))
        smooth = self.config.aimbot_smooth
        new_pitch = current[0] + (target_rot[0] - current[0]) * smooth
        new_yaw = current[1] + (target_rot[1] - current[1]) * smooth
        self._write_control_rotation((new_pitch, new_yaw, current[2]))

    def _magnet_at(self, target_pos, camera):
        """Magnet aim: instant snap with smoothing option."""
        if not camera:
            return
        current = self._read_control_rotation()
        if current is None:
            return
        dx = target_pos[0] - camera["loc"][0]
        dy = target_pos[1] - camera["loc"][1]
        dz = target_pos[2] - camera["loc"][2]
        target_rot = self._vector_to_rotation((dx, dy, dz))
        strength = self.config.magnet_strength
        new_pitch = current[0] + (target_rot[0] - current[0]) * strength
        new_yaw = current[1] + (target_rot[1] - current[1]) * strength
        self._write_control_rotation((new_pitch, new_yaw, current[2]))
