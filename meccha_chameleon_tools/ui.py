#!/usr/bin/env python3
"""Qt5 overlay and menu widgets for MECCHA CHAMELEON ESP."""
import math
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
    QSystemTrayIcon, QMenu, QMessageBox,
)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QBrush, QPolygonF, QPixmap, QIcon, QPainter as QPixPainter
from PyQt5.QtCore import QPointF

from meccha_chameleon_tools.core import (
    MecchaESP, rp, ru32, rfloat, wfloat, rvec3, rvec3_f, dist,
    read_array, OFFSETS,
)
from meccha_chameleon_tools.config import Config, save_config, load_config
from meccha_chameleon_tools.translations import _tr, LANGUAGE_NAMES
from meccha_chameleon_tools.camouflage import ensure_bridge_ready, paint_now, paint_start, paint_single, stop_paint, is_bridge_alive, send_preview, send_unpreview
from meccha_chameleon_tools import logger as log
# HyperVision disabled — not functional in current release
# from meccha_chameleon_tools.hypervision import (ping_fast, bg_scan_terrain, bg_visibility_scan,
#                                                   bg_path_find, bg_start_hv, bg_update_hv, bg_stop_hv,
#                                                   bg_ensure_bridge, simplify_segments)


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
    up = (-(cr * sp * cy + sr * sy), sr * cy - cr * sp * sy, cr * cp)
    return forward, right, up


def cam_valid(cam):
    return (cam and "loc" in cam and "rot" in cam and "fov" in cam and
            all(math.isfinite(v) for v in cam["loc"]) and
            all(math.isfinite(v) for v in cam["rot"]) and
            math.isfinite(cam["fov"]) and cam["fov"] > 0)


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


def norm_color_mode(cm):
    """Normalize color_mode from config (handles old values)."""
    if cm in ("team", "hybrid"):
        return "relative"
    if cm == "role":
        return "absolute"
    return cm if cm in ("relative", "absolute") else "relative"





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


def draw_radar(painter, cam, local_pos, players, radar_cx, radar_cy, radar_size, radar_range, color, opacity,
               terrain_segments=None, current_z=0.0):
    if not cam_valid(cam) or not local_pos or not all(math.isfinite(v) for v in local_pos):
        return
    half = radar_size / 2
    painter.setPen(QPen(QColor(255, 255, 255, opacity), 1))
    painter.setBrush(QBrush(QColor(0, 0, 0, opacity)))
    painter.drawEllipse(int(radar_cx - half), int(radar_cy - half), radar_size, radar_size)
    painter.drawLine(int(radar_cx - half), int(radar_cy), int(radar_cx + half), int(radar_cy))
    painter.drawLine(int(radar_cx), int(radar_cy - half), int(radar_cx), int(radar_cy + half))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 255, 0, 220))
    painter.drawEllipse(int(radar_cx - 2), int(radar_cy - 2), 5, 5)
    # Terrain segment rendering disabled (not functional)
    # (terrain code omitted)

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


_tab_map = {"ESP": "ESP", "HEALTH": "HEALTH", "VISUAL": "VISUAL", "RADAR": "RADAR", "AIMBOT": "AIMBOT", "PLAYER": "PLAYER", "CAMOUFLAGE": "CAMOUFLAGE"}


class Menu(QWidget):
    STYLE = """
        QFrame#menuFrame {
            background-color: rgba(14, 14, 22, 240);
            border: 1px solid #2a2a3e;
            border-radius: 10px;
        }
        QLabel { color: #ccc; font-size: 11px; background: transparent; }
        QCheckBox { color: #ccc; font-size: 11px; spacing: 8px; padding: 1px 0; }
        QCheckBox::indicator { width: 15px; height: 15px; border-radius: 3px; border: 1px solid #3a3a50; background: #1a1a26; }
        QCheckBox::indicator:checked { background: #3a6ea5; border-color: #5a8ec5; }
        QComboBox {
            background-color: #1a1a26; color: #ccc;
            border: 1px solid #2a2a3e; padding: 4px 8px; border-radius: 4px;
            font-size: 11px; min-height: 22px;
        }
        QComboBox:hover { border-color: #4a4a6a; }
        QComboBox::drop-down {
            subcontrol-origin: padding; subcontrol-position: top right;
            width: 22px; border-left: 1px solid #2a2a3e;
            border-top-right-radius: 4px; border-bottom-right-radius: 4px;
        }
        QComboBox::down-arrow { width: 8px; height: 8px; }
        QComboBox QAbstractItemView {
            background-color: #1a1a26; color: #ccc;
            border: 1px solid #2a2a3e; border-radius: 4px;
            selection-background-color: #3a6ea5; selection-color: #fff;
            outline: none; font-size: 11px; padding: 2px;
        }
        QPushButton {
            background-color: #22223a; color: #ccc;
            border: 1px solid #2a2a3e; padding: 5px 10px; border-radius: 5px;
            font-size: 11px;
        }
        QPushButton:hover { background-color: #2e2e4a; border-color: #4a4a6a; }
        QPushButton:pressed { background-color: #3a3a5a; }
        QSpinBox, QDoubleSpinBox {
            background-color: #1a1a26; color: #ccc;
            border: 1px solid #2a2a3e; padding: 1px 6px; border-radius: 4px;
            font-size: 11px; min-height: 22px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus { border-color: #5a8ec5; }
        QSpinBox::up-button, QDoubleSpinBox::up-button,
        QSpinBox::down-button, QDoubleSpinBox::down-button {
            background-color: #22223a; border: 1px solid #2a2a3e;
            width: 18px;
        }
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
            background-color: #2e2e4a;
        }
        QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { width: 6px; height: 6px; }
        QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { width: 6px; height: 6px; }
        QSlider::groove:horizontal {
            background: #1a1a26; border: 1px solid #2a2a3e;
            height: 6px; border-radius: 3px;
        }
        QSlider::handle:horizontal {
            background: #3a6ea5; border: 1px solid #5a8ec5;
            width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;
        }
        QSlider::handle:horizontal:hover { background: #4a7eb5; }
        QSlider::sub-page:horizontal { background: #3a6ea5; border-radius: 3px; }
        QLabel#titleLbl {
            font-size: 14px; font-weight: bold; color: #8ab4f8;
            padding: 4px 0; letter-spacing: 1px;
        }
    """

    def __init__(self, config: Config, esp: MecchaESP, tabs=None):
        super().__init__()
        self.config = config
        self.esp = esp
        self._active_tabs = tabs or ["ESP", "HEALTH", "VISUAL", "RADAR", "AIMBOT", "PLAYER", "CAMOUFLAGE"]
        self.setWindowTitle("Meccha Chameleon Tools")
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None
        self._key_recorder = KeyRecorder(self._on_key_recorded)
        self._container = None
        self._outer_layout = QVBoxLayout(self)
        self._outer_layout.setContentsMargins(0, 0, 0, 0)
        self._build_ui()
        self.resize(640, 720)
        self.setMinimumSize(540, 600)
        self._setup_tray()

    def _close_app(self):
        QApplication.quit()

    def _setup_tray(self):
        icon = QApplication.windowIcon()
        if icon.isNull():
            pix = QPixmap(16, 16)
            pix.fill(Qt.transparent)
            pp = QPixPainter(pix)
            pp.setBrush(QColor(0, 180, 255))
            pp.setPen(Qt.NoPen)
            pp.drawEllipse(1, 1, 14, 14)
            pp.end()
            icon = QIcon(pix)
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("Meccha Camouflage v1.9.0-wow")
        tray_menu = QMenu()
        act_toggle = tray_menu.addAction(_tr("Show/Hide Menu"))
        act_toggle.triggered.connect(lambda: self.setVisible(not self.isVisible()))
        tray_menu.addSeparator()
        act_quit = tray_menu.addAction(_tr("Quit"))
        act_quit.triggered.connect(QApplication.quit)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(lambda reason: (
            self.setVisible(not self.isVisible()) if reason == QSystemTrayIcon.DoubleClick else None
        ))
        self.tray_icon.show()

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
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)

        title = QLabel(_tr("MECCA CHAMELION TOOLS"))
        title.setObjectName("titleLbl")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        body = QHBoxLayout()
        body.setSpacing(8)

        self.tab_list = QListWidget()
        self.tab_list.setFixedWidth(90)
        self.tab_list.setFocusPolicy(Qt.NoFocus)
        self.tab_list.setStyleSheet("""
            QListWidget {
                background: #1a1a26; border: 1px solid #2a2a3e;
                border-radius: 6px; padding: 4px; outline: none;
            }
            QListWidget::item {
                color: #777; padding: 8px 6px; border-radius: 4px;
                font-size: 11px; font-weight: bold;
            }
            QListWidget::item:selected {
                background: #2a3a5a; color: #8ab4f8;
            }
            QListWidget::item:hover:!selected {
                background: #22223a; color: #aaa;
            }
            QListWidget::vertical-scrollbar {
                background: #12121a; width: 8px; border-radius: 4px;
            }
            QListWidget::vertical-scrollbar-handle {
                background: #2a2a3e; min-height: 20px; border-radius: 4px;
            }
            QListWidget::vertical-scrollbar-handle:hover {
                background: #3a3a5a;
            }
            QListWidget::vertical-scrollbar-add-line, QListWidget::vertical-scrollbar-sub-line {
                height: 0px;
            }
        """)
        self.tab_list.addItems([_tr(t) for t in self._active_tabs])
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

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_save = QPushButton(_tr("Save Config"))
        self.btn_save.clicked.connect(self._save_config)
        self.btn_load = QPushButton(_tr("Load Config"))
        self.btn_load.clicked.connect(self._load_config)
        self.btn_close = QPushButton(_tr("Close"))
        self.btn_close.clicked.connect(self._close_app)
        self.btn_close.setStyleSheet("QPushButton { background-color: #3a1a1a; border-color: #5a2a2a; color: #e88; } QPushButton:hover { background-color: #5a2a2a; color: #faa; }")

        hint = QLabel(_tr("Ins/F1 toggle | Drag to move | END=Exit"))
        hint.setStyleSheet("color: #555; font-size: 9px;")
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_load)
        bar.addWidget(self.btn_close)
        bar.addStretch()
        bar.addWidget(hint)
        outer.addLayout(bar)

        lang_row = QHBoxLayout()
        lang_row.setSpacing(6)
        lang_label = QLabel(_tr("Language:"))
        lang_label.setStyleSheet("color: #888; font-size: 10px;")
        self.lang_combo = QComboBox()
        lang_codes = list(LANGUAGE_NAMES.keys())
        self.lang_combo.addItems([LANGUAGE_NAMES[k] for k in lang_codes])
        self.lang_combo.setCurrentIndex(lang_codes.index(self.config.language) if self.config.language in lang_codes else 0)
        self.lang_combo.currentIndexChanged.connect(lambda idx: self._switch_language(lang_codes[idx]))
        self.lang_combo.setFixedWidth(130)
        lang_row.addWidget(lang_label)
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch()
        grip = QSizeGrip(container)
        grip.setFixedSize(16, 16)
        grip.setStyleSheet("background: transparent;")
        lang_row.addWidget(grip)
        outer.addLayout(lang_row)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        github_link = QLabel('<a href="https://github.com/SilentJMA/Meccha-Chameleon-Tools" style="color: #8ab4f8; text-decoration: none; font-size: 9px;">GitHub</a>')
        github_link.setOpenExternalLinks(True)
        github_link.setStyleSheet("font-size: 9px;")
        release_label = QLabel("v1.9.0-wow")
        release_label.setStyleSheet("color: #666; font-size: 9px;")
        copyright_link = QLabel('<a href="https://github.com/SilentJMA" style="color: #888; text-decoration: none; font-size: 9px;">\u00a9 2026 SilentJMA</a>')
        copyright_link.setOpenExternalLinks(True)
        copyright_link.setStyleSheet("font-size: 9px;")
        footer.addWidget(github_link)
        footer.addStretch()
        footer.addWidget(release_label)
        footer.addStretch()
        footer.addWidget(copyright_link)
        outer.addLayout(footer)

        self._outer_layout.addWidget(container)

        if "ESP" in self._active_tabs:
            self._build_esp_tab()
        if "HEALTH" in self._active_tabs:
            self._build_health_tab()
        if "VISUAL" in self._active_tabs:
            self._build_visual_tab()
        if "RADAR" in self._active_tabs:
            self._build_radar_tab()
        if "AIMBOT" in self._active_tabs:
            self._build_aimbot_tab()
        if "PLAYER" in self._active_tabs:
            self._build_player_tab()
        if "CAMOUFLAGE" in self._active_tabs:
            self._build_camouflage_tab()

    def _switch_tab(self, idx):
        if 0 <= idx < len(self._active_tabs):
            self.stack.setCurrentIndex(idx)

    def _build_esp_tab(self):
        p = self._pages["ESP"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        self.cb_enabled = self._chk(_tr("ESP Enabled"), "enabled")
        lo.addWidget(self.cb_enabled)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.cb_dot = self._chk(_tr("Dot"), "dot_esp")
        self.cb_box = self._chk(_tr("2D Box"), "box_esp")
        self.cb_skeleton = self._chk(_tr("Skeleton"), "skeleton_esp")
        row.addWidget(self.cb_dot)
        row.addWidget(self.cb_box)
        row.addWidget(self.cb_skeleton)
        lo.addLayout(row)
        for cfg, label in [("show_local", _tr("Show Local Player")), ("show_names", _tr("Show Names")),
                           ("show_distance", _tr("Show Distance")), ("snap_lines", _tr("Snap Lines")),
                           ("enemy_only", _tr("Enemy Only")), ("show_roles", _tr("Show Roles")),
                           ("team_filter", _tr("Team Filter")), ("distance_scaling", _tr("Dist. Scaling"))]:
            cb = self._chk(label, cfg)
            lo.addWidget(cb)
        self.cb_corner = self._chk(_tr("Corner Box"), "corner_box")
        lo.addWidget(self.cb_corner)
        dr = QHBoxLayout()
        dr.addWidget(QLabel(_tr("Dot Radius:")))
        self.spn_dot = QSpinBox()
        self.spn_dot.setRange(2, 32)
        self.spn_dot.setValue(self.config.dot_radius)
        self.spn_dot.valueChanged.connect(lambda v: setattr(self.config, "dot_radius", v))
        dr.addWidget(self.spn_dot)
        lo.addLayout(dr)
        fr = QHBoxLayout()
        fr.addWidget(QLabel(_tr("Refresh FPS:")))
        self.spn_fps = QSpinBox()
        self.spn_fps.setRange(10, 60)
        self.spn_fps.setValue(self.config.esp_fps)
        self.spn_fps.valueChanged.connect(lambda v: setattr(self.config, "esp_fps", v))
        fr.addWidget(self.spn_fps)
        lo.addLayout(fr)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a2a3e;")
        lo.addWidget(sep)
        self.btn_filter = QPushButton(_tr("Filter Config"))
        self.btn_filter.clicked.connect(self._show_filter_dialog)
        lo.addWidget(self.btn_filter)
        lo.addStretch()

    def _build_health_tab(self):
        p = self._pages["HEALTH"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        self.cb_hp = self._chk(_tr("Health Bar"), "health_bar")
        self.cb_shield = self._chk(_tr("Shield Bar"), "shield_bar")
        lo.addWidget(self.cb_hp)
        lo.addWidget(self.cb_shield)
        hr = QHBoxLayout()
        hr.addWidget(QLabel(_tr("Model Height:")))
        self.spn_height = QSpinBox()
        self.spn_height.setRange(50, 250)
        self.spn_height.setValue(int(self.config.box_height_world))
        self.spn_height.valueChanged.connect(lambda v: setattr(self.config, "box_height_world", float(v)))
        hr.addWidget(self.spn_height)
        lo.addLayout(hr)
        yr = QHBoxLayout()
        yr.addWidget(QLabel(_tr("Y Offset:")))
        self.spn_yoff = QSpinBox()
        self.spn_yoff.setRange(-50, 50)
        self.spn_yoff.setValue(self.config.box_y_offset)
        self.spn_yoff.valueChanged.connect(lambda v: setattr(self.config, "box_y_offset", v))
        yr.addWidget(self.spn_yoff)
        lo.addLayout(yr)
        lo.addStretch()

    def _build_visual_tab(self):
        from PyQt5.QtWidgets import QScrollArea
        p = self._pages["VISUAL"]
        outer = QVBoxLayout(p)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; }")
        content = QWidget()
        lo = QVBoxLayout(content)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        outer.addWidget(scroll)
        scroll.setWidget(content)
        self.cb_hunter = self._chk(_tr("Hunter ESP"), "hunter_esp")
        self.cb_survivor = self._chk(_tr("Survivor ESP"), "survivor_esp")
        lo.addWidget(self.cb_hunter)
        lo.addWidget(self.cb_survivor)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a2a3e;")
        lo.addWidget(sep)
        hdr2 = QLabel(_tr("DRAW OPTIONS"))
        hdr2.setStyleSheet("font-size: 12px; font-weight: bold; color: #8ab4f8;")
        lo.addWidget(hdr2)
        for cfg, label in [("draw_all", _tr("Draw All Actors")), ("draw_all_names", _tr("Draw All Names")),
                           ("invincible_detect", _tr("Detect Invincible")),
                           ("disable_buried", _tr("Disable Too Buried")),
                           ("show_background_geo", _tr("Show Background Geometry")),
                           ("show_cursor", _tr("Show Cursor"))]:
            cb = self._chk(label, cfg)
            lo.addWidget(cb)
        dr = QHBoxLayout()
        dr.addWidget(QLabel(_tr("Draw All Range:")))
        self.spn_draw_range = QSpinBox()
        self.spn_draw_range.setRange(500, 50000)
        self.spn_draw_range.setSingleStep(500)
        self.spn_draw_range.setValue(int(self.config.draw_all_max_distance))
        self.spn_draw_range.valueChanged.connect(lambda v: setattr(self.config, "draw_all_max_distance", float(v)))
        dr.addWidget(self.spn_draw_range)
        lo.addLayout(dr)
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.HLine)
        sep2.setStyleSheet("color: #2a2a3e;")
        lo.addWidget(sep2)
        hdr3 = QLabel(_tr("APPEARANCE"))
        hdr3.setStyleSheet("font-size: 12px; font-weight: bold; color: #8ab4f8;")
        lo.addWidget(hdr3)
        lo.addWidget(QLabel(_tr("Color Mode:")))
        self.cmb_color_mode = QComboBox()
        cm_labels = {"relative": "Relative Team", "absolute": "Absolute Team"}
        self.cmb_color_mode.addItems([_tr(l) for l in ["Relative Team", "Absolute Team"]])
        cm_codes = list(cm_labels.keys())
        norm_cm = norm_color_mode(self.config.color_mode)
        self.cmb_color_mode.setCurrentIndex(cm_codes.index(norm_cm) if norm_cm in cm_codes else 0)
        self.cmb_color_mode.currentIndexChanged.connect(lambda idx: setattr(self.config, "color_mode", cm_codes[idx]))
        lo.addWidget(self.cmb_color_mode)
        lr = QHBoxLayout()
        lr.addWidget(QLabel(_tr("Line Thickness:")))
        self.spn_line = QSpinBox()
        self.spn_line.setRange(1, 8)
        self.spn_line.setValue(self.config.line_thickness)
        self.spn_line.valueChanged.connect(lambda v: setattr(self.config, "line_thickness", v))
        lr.addWidget(self.spn_line)
        lo.addLayout(lr)
        pr = QHBoxLayout()
        pr.addWidget(QLabel(_tr("Point Size:")))
        self.spn_point = QSpinBox()
        self.spn_point.setRange(1, 8)
        self.spn_point.setValue(self.config.point_size)
        self.spn_point.valueChanged.connect(lambda v: setattr(self.config, "point_size", v))
        pr.addWidget(self.spn_point)
        lo.addLayout(pr)
        # #HyperVision section disabled (not functional)
        # hvsep = QFrame()
        # hvsep.setFrameShape(QFrame.HLine)
        # hvsep.setStyleSheet("color: #2a2a3e;")
        # lo.addWidget(hvsep)
        # hvhdr = QLabel(_tr("HYPERVISION"))
        # hvhdr.setStyleSheet("font-size: 12px; font-weight: bold; color: #8ab4f8;")
        # lo.addWidget(hvhdr)
        # self.cb_hv = self._chk(_tr("HyperVision Enabled"), "hypervision_enabled")
        # lo.addWidget(self.cb_hv)
        # self.cb_hv_paths = self._chk(_tr("Show Paths"), "hv_show_paths")
        # self.cb_hv_exposure = self._chk(_tr("Show Exposure Volume"), "hv_show_exposure")
        # lo.addWidget(self.cb_hv_paths)
        # lo.addWidget(self.cb_hv_exposure)
        # Radar terrain disabled (not functional in current release)
        # self.cb_terrain = self._chk(_tr("Radar Terrain"), "radar_terrain")
        # lo.addWidget(self.cb_terrain)
        # self.cb_hv_paths_3d = self._chk(_tr("Show 3D Nav Lines"), "hv_show_3d")
        # lo.addWidget(self.cb_hv_paths_3d)
        # qr = QHBoxLayout()
        # qr.addWidget(QLabel(_tr("Scan Quality:")))
        # self.cmb_hv_q = QComboBox()
        # hv_q_labels = {"low": _tr("Low"), "medium": _tr("Medium"), "high": _tr("High"), "ultra": _tr("Ultra")}
        # hv_q_codes = list(hv_q_labels.keys())
        # self.cmb_hv_q.addItems(list(hv_q_labels.values()))
        # self.cmb_hv_q.setCurrentIndex(hv_q_codes.index(self.config.hv_quality) if self.config.hv_quality in hv_q_codes else 1)
        # self.cmb_hv_q.currentIndexChanged.connect(lambda idx: setattr(self.config, "hv_quality", hv_q_codes[idx]))
        # qr.addWidget(self.cmb_hv_q)
        # lo.addLayout(qr)
        lo.addStretch()

    def _build_radar_tab(self):
        p = self._pages["RADAR"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        self.cb_radar = self._chk(_tr("Radar Enabled"), "radar_enabled")
        lo.addWidget(self.cb_radar)
        sr = QHBoxLayout()
        sr.addWidget(QLabel(_tr("Radar Size:")))
        self.spn_radar_size = QSpinBox()
        self.spn_radar_size.setRange(80, 400)
        self.spn_radar_size.setValue(self.config.radar_size)
        self.spn_radar_size.valueChanged.connect(lambda v: setattr(self.config, "radar_size", v))
        sr.addWidget(self.spn_radar_size)
        lo.addLayout(sr)
        rr = QHBoxLayout()
        rr.addWidget(QLabel(_tr("Radar Range:")))
        self.spn_radar_range = QSpinBox()
        self.spn_radar_range.setRange(1000, 50000)
        self.spn_radar_range.setSingleStep(500)
        self.spn_radar_range.setValue(int(self.config.radar_range))
        self.spn_radar_range.valueChanged.connect(lambda v: setattr(self.config, "radar_range", float(v)))
        rr.addWidget(self.spn_radar_range)
        lo.addLayout(rr)
        lo.addStretch()

    def _build_aimbot_tab(self):
        p = self._pages["AIMBOT"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        self.cb_aimbot = self._chk(_tr("Aimbot Enabled"), "aimbot_enabled")
        self.cb_aim_fov = self._chk(_tr("Show FOV Circle"), "aimbot_show_fov")
        lo.addWidget(self.cb_aimbot)
        lo.addWidget(self.cb_aim_fov)
        kr = QHBoxLayout()
        self.lbl_aim_key = QLabel(_tr("Aim Key: {key}", key=self.config.aimbot_key))
        self.btn_record_key = QPushButton(_tr("Record Key"))
        self.btn_record_key.clicked.connect(self._start_aim_key_record)
        kr.addWidget(self.lbl_aim_key)
        kr.addWidget(self.btn_record_key)
        lo.addLayout(kr)
        fr = QHBoxLayout()
        fr.addWidget(QLabel(_tr("FOV Radius:")))
        self.spn_aim_fov = QSpinBox()
        self.spn_aim_fov.setRange(10, 600)
        self.spn_aim_fov.setValue(self.config.aimbot_fov)
        self.spn_aim_fov.valueChanged.connect(lambda v: setattr(self.config, "aimbot_fov", v))
        fr.addWidget(self.spn_aim_fov)
        lo.addLayout(fr)
        sr = QHBoxLayout()
        sr.addWidget(QLabel(_tr("Smooth:")))
        self.spn_aim_smooth = QDoubleSpinBox()
        self.spn_aim_smooth.setRange(0.01, 1.0)
        self.spn_aim_smooth.setSingleStep(0.05)
        self.spn_aim_smooth.setValue(self.config.aimbot_smooth)
        self.spn_aim_smooth.valueChanged.connect(lambda v: setattr(self.config, "aimbot_smooth", v))
        sr.addWidget(self.spn_aim_smooth)
        lo.addLayout(sr)
        ar = QHBoxLayout()
        ar.addWidget(QLabel(_tr("Target Offset:")))
        self.spn_aim_off = QSpinBox()
        self.spn_aim_off.setRange(-200, 200)
        self.spn_aim_off.setValue(int(self.config.aimbot_target_offset))
        self.spn_aim_off.valueChanged.connect(lambda v: setattr(self.config, "aimbot_target_offset", float(v)))
        ar.addWidget(self.spn_aim_off)
        lo.addLayout(ar)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a2a3e;")
        lo.addWidget(sep)
        hdr = QLabel(_tr("MAGNET AIM ASSIST"))
        hdr.setStyleSheet("font-size: 12px; font-weight: bold; color: #8ab4f8;")
        lo.addWidget(hdr)
        self.cb_magnet = self._chk(_tr("Magnet Enabled"), "magnet_enabled")
        lo.addWidget(self.cb_magnet)
        mkr = QHBoxLayout()
        mkr.addWidget(QLabel(_tr("Magnet Key:")))
        self.lbl_magnet_key = QLabel(self.config.magnet_hold_key)
        self.btn_record_magnet = QPushButton(_tr("Record"))
        self.btn_record_magnet.clicked.connect(self._start_magnet_key_record)
        mkr.addWidget(self.lbl_magnet_key)
        mkr.addWidget(self.btn_record_magnet)
        lo.addLayout(mkr)
        mfr = QHBoxLayout()
        mfr.addWidget(QLabel(_tr("Magnet FOV:")))
        self.spn_magnet_fov = QSpinBox()
        self.spn_magnet_fov.setRange(10, 300)
        self.spn_magnet_fov.setValue(self.config.magnet_fov)
        self.spn_magnet_fov.valueChanged.connect(lambda v: setattr(self.config, "magnet_fov", v))
        mfr.addWidget(self.spn_magnet_fov)
        lo.addLayout(mfr)
        msr = QHBoxLayout()
        msr.addWidget(QLabel(_tr("Magnet Strength:")))
        self.spn_magnet_str = QDoubleSpinBox()
        self.spn_magnet_str.setRange(0.1, 1.0)
        self.spn_magnet_str.setSingleStep(0.1)
        self.spn_magnet_str.setValue(self.config.magnet_strength)
        self.spn_magnet_str.valueChanged.connect(lambda v: setattr(self.config, "magnet_strength", v))
        msr.addWidget(self.spn_magnet_str)
        lo.addLayout(msr)
        lo.addStretch()

    def _build_player_tab(self):
        p = self._pages["PLAYER"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        hdr = QLabel(_tr("PLAYER MODIFICATION"))
        hdr.setStyleSheet("font-size: 12px; font-weight: bold; color: #8ab4f8;")
        lo.addWidget(hdr)
        notice = QLabel(_tr("\u26a0 Host Only - These features only work when you are the game host"))
        notice.setStyleSheet("color: #ff6b6b; font-size: 10px; font-weight: bold; background-color: #2a1a1a; padding: 4px; border-radius: 3px;")
        notice.setWordWrap(True)
        lo.addWidget(notice)
        self.cb_player_mod = self._chk(_tr("Player Mod Enabled"), "player_mod_enabled")
        lo.addWidget(self.cb_player_mod)
        sr = QHBoxLayout()
        sr.addWidget(QLabel(_tr("Speed Multiplier:")))
        self.spn_speed = QDoubleSpinBox()
        self.spn_speed.setRange(0.5, 10.0)
        self.spn_speed.setSingleStep(0.5)
        self.spn_speed.setValue(self.config.player_speed_mult)
        self.spn_speed.valueChanged.connect(lambda v: setattr(self.config, "player_speed_mult", v))
        sr.addWidget(self.spn_speed)
        lo.addLayout(sr)
        jr = QHBoxLayout()
        jr.addWidget(QLabel(_tr("Jump Multiplier:")))
        self.spn_jump = QDoubleSpinBox()
        self.spn_jump.setRange(0.5, 10.0)
        self.spn_jump.setSingleStep(0.5)
        self.spn_jump.setValue(self.config.player_jump_mult)
        self.spn_jump.valueChanged.connect(lambda v: setattr(self.config, "player_jump_mult", v))
        jr.addWidget(self.spn_jump)
        lo.addLayout(jr)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a2a3e;")
        lo.addWidget(sep)
        hdr2 = QLabel(_tr("COMMANDS"))
        hdr2.setStyleSheet("font-size: 12px; font-weight: bold; color: #8ab4f8;")
        lo.addWidget(hdr2)
        tkr = QHBoxLayout()
        tkr.addWidget(QLabel(_tr("Teleport Collectible Key:")))
        self.lbl_tp_key = QLabel(self.config.teleport_collectible_key)
        self.btn_record_tp = QPushButton(_tr("Record"))
        self.btn_record_tp.clicked.connect(self._start_tp_key_record)
        tkr.addWidget(self.lbl_tp_key)
        tkr.addWidget(self.btn_record_tp)
        lo.addLayout(tkr)
        info = QLabel(_tr("Hold the key above to teleport nearest item to you.\nSet speed/jump mult and enable Player Mod to apply."))
        info.setStyleSheet("color: #888; font-size: 10px;")
        info.setWordWrap(True)
        lo.addWidget(info)
        lo.addStretch()

    def _build_camouflage_tab(self):
        p = self._pages["CAMOUFLAGE"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(6)

        hdr = QLabel("CAMOUFLAGE")
        hdr.setStyleSheet("font-size: 14px; font-weight: bold; color: #8ab4f8;")
        lo.addWidget(hdr)

        self.lbl_camo_status = QLabel("Ready")
        self.lbl_camo_status.setWordWrap(True)
        self.lbl_camo_status.setStyleSheet("color: #8ab4f8; font-size: 11px; font-weight: bold; background-color: #12121c; padding: 6px; border-radius: 4px; border: 1px solid #2a2a3e;")
        lo.addWidget(self.lbl_camo_status)

        self.lbl_bridge_status = QLabel("Bridge: checking...")
        self.lbl_bridge_status.setStyleSheet("color: #aaa; font-size: 10px;")
        lo.addWidget(self.lbl_bridge_status)

        for text, color, cmd in [
            ("Start Painting", "#4fd16a", self._on_paint_now),
            ("Stop Painting", "#e74c3c", self._on_stop_camo),
            (_tr("Review"), "#3498db", self._on_preview),
            (_tr("Unreview"), "#f39c12", self._on_unpreview),
        ]:
            btn = QPushButton(text)
            btn.setStyleSheet(f"QPushButton {{ background-color: #1a1a1a; color: {color}; border: 1px solid #333; padding: 8px; border-radius: 6px; font-size: 11px; font-weight: bold; }} QPushButton:hover {{ background-color: #2a2a2a; }}")
            btn.clicked.connect(cmd)
            lo.addWidget(btn)

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
        cb._cfg_attr = attr
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
        for widget in self.findChildren(QCheckBox):
            attr = getattr(widget, "_cfg_attr", None)
            if attr and hasattr(self.config, attr):
                widget.setChecked(getattr(self.config, attr))
        for spin, attr in [(getattr(self, s, None), a) for s, a in [
            ("spn_dot", "dot_radius"), ("spn_height", "box_height_world"),
            ("spn_yoff", "box_y_offset"), ("spn_radar_size", "radar_size"),
            ("spn_radar_range", "radar_range"), ("spn_aim_fov", "aimbot_fov"),
            ("spn_aim_smooth", "aimbot_smooth"), ("spn_aim_off", "aimbot_target_offset"),
        ]]:
            if spin is not None and hasattr(self.config, attr):
                spin.setValue(getattr(self.config, attr))
        self.btn_load.setText(_tr("Config Loaded!"))
        QTimer.singleShot(1500, lambda: self.btn_load.setText(_tr("Load Config")))

    def _show_filter_dialog(self):
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QCheckBox, QPushButton, QLabel
        from PyQt5.QtCore import Qt
        dlg = QDialog(self)
        dlg.setWindowTitle(_tr("Filter Config"))
        dlg.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Dialog | Qt.WindowCloseButtonHint)
        dlg.setFixedSize(260, 220)
        dlg.setStyleSheet("""
            QDialog { background-color: #1a1a28; color: #ccc; }
            QLabel { color: #8ab4f8; font-size: 12px; font-weight: bold; }
            QCheckBox { color: #ccc; font-size: 11px; spacing: 8px; padding: 4px 0; }
            QCheckBox::indicator { width: 15px; height: 15px; border-radius: 3px; border: 1px solid #444; background: #1a1a28; }
            QCheckBox::indicator:checked { background: #3a6ea5; border-color: #5a8ec5; }
            QPushButton { background-color: #22223a; color: #ccc; border: 1px solid #33334a; padding: 5px 14px; border-radius: 4px; font-size: 11px; min-width: 60px; }
            QPushButton:hover { background-color: #2e2e4a; border-color: #4a4a6a; }
        """)
        lo = QVBoxLayout(dlg)
        lo.setContentsMargins(12, 8, 12, 8)
        lo.setSpacing(6)
        lo.addWidget(QLabel(_tr("Hide by category:")))
        cm = norm_color_mode(self.config.color_mode)
        if cm == "absolute":
            pairs = [("filter_hide_enemy", _tr("Hunter (Red)")), ("filter_hide_self", _tr("Green (Self)")),
                     ("filter_hide_teammate", _tr("Survivor (Blue)")), ("filter_hide_unknown", _tr("Unknown"))]
        else:
            pairs = [("filter_hide_enemy", _tr("Red (Enemy)")), ("filter_hide_self", _tr("Green (Self)")),
                     ("filter_hide_teammate", _tr("Yellow (Teammate)")), ("filter_hide_unknown", _tr("Blue (Unknown)"))]
        for attr, label in pairs:
            cb = QCheckBox(label)
            cb.setChecked(getattr(self.config, attr))
            cb.toggled.connect(lambda checked, a=attr: setattr(self.config, a, checked))
            lo.addWidget(cb)
        btn_ok = QPushButton(_tr("OK"))
        btn_ok.clicked.connect(dlg.accept)
        lo.addWidget(btn_ok)
        dlg.exec_()

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
# Overlay widget (Python reference - will be replaced by C++ after full parity)
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

        self._rendering = False
        self._cache_lock = threading.Lock()
        self._cached_cam = None
        self._cached_players = []
        self._reader_running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()
        # Terrain cache disabled (not functional)
        # self._terrain_cache = None
        # self._last_terrain_time = 0.0

        # #HyperVision state disabled (not functional)
        # self._hv_exposure_cloud = []
        # self._hv_paths = []
        # self._hv_bridge_ok = False
        # self._hv3d_started = False
        # self._hv_target_idx = 0
        # self._hv_timer = QTimer(self)
        # self._hv_timer.timeout.connect(self._hv_tick)
        # self._hv_timer.start(500)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_overlay)
        self.timer.start(1000 // max(10, min(60, self.config.esp_fps)))

        # Attachment is handled by _reader_loop; no separate timer needed

        self.game_hwnd = self._find_game_window()
        self._resize_to_game()

        self.key_timer = QTimer(self)
        self.key_timer.timeout.connect(self._poll_keys)
        self.key_timer.start(50)

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

    # Terrain scanning disabled (not functional)
    # def _tick_terrain(self, force=False):
    #     pass

    # HyperVision disabled (not functional in current release)
    # def _hv_tick(self):
    #     pass

    def _try_attach(self):
        if self.esp is not None:
            return
        try:
            from meccha_chameleon_tools.core import MecchaESP
            log.info("Attempting game attach...")
            self.esp = MecchaESP()
            log.info("Game attached successfully")
        except Exception as e:
            log.warn(f"Game attach failed: {e}")

    def _restart_timer(self):
        interval = max(8, min(100, 1000 // max(10, min(60, self.config.esp_fps))))
        self.timer.start(interval)

    def _reader_loop(self):
        fail_count = 0
        while getattr(self, '_reader_running', False):
            try:
                if self.config and self.config.enabled and self.esp and self.esp.is_process_alive():
                    cam = self.esp.get_camera()
                    if cam is not None:
                        players = list(self.esp.iter_players(
                            include_local=self.config.show_local,
                        ))
                        for p in players:
                            actor = p.get("actor")
                            if actor:
                                p["_health_info"] = self.esp.get_health(actor, p.get("player_state"))
                                p["_invincible"] = self.esp.get_invincible(actor)
                                p["_rot"] = self.esp.get_actor_root_rotation(actor)
                        with self._cache_lock:
                            self._cached_cam = cam
                            self._cached_players = players
                        fail_count = 0
                        if len(players) > 0:
                            n_h = sum(1 for p in players if p.get("is_hunter"))
                            n_s = sum(1 for p in players if p.get("is_survivor"))
                            log.debug(f"Reader: {len(players)} players ({n_h} hunters, {n_s} survivors)")
                elif self.esp is None:
                    self._try_attach()
                else:
                    log.info("Game process lost — cleaning up for re-attach")
                    try:
                        self.esp.cleanup()
                    except Exception:
                        pass
                    with self._cache_lock:
                        self.esp = None
                        self._cached_cam = None
                        self._cached_players = []
                    fail_count = 0
            except Exception as e:
                fail_count += 1
                if fail_count >= 30:
                    log.warn(f"Reader loop: {fail_count} consecutive failures, clearing cache")
                    with self._cache_lock:
                        self._cached_players = []
                    fail_count = 0

            time.sleep(0.1)

    def _tick_overlay(self):
        if self._rendering:
            return
        self._rendering = True
        self._resize_to_game()
        self.update()

    def update_overlay(self):
        self._resize_to_game()
        self.update()

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
        _esp = self.esp
        if tp_down and not self._tp_key_state and _esp:
            now = time.time()
            last = getattr(self, '_last_tp_time', 0.0)
            if now - last > 1.0:
                self._last_tp_time = now
                _esp.teleport_collectible(self.config.teleport_collectible_key)
        self._tp_key_state = tp_down
        if self.config.player_mod_enabled and not self._player_mod_active and _esp:
            _esp.player_mod(self.config.player_speed_mult, self.config.player_jump_mult)
            self._player_mod_active = True
        elif not self.config.player_mod_enabled and self._player_mod_active and _esp:
            _esp.player_mod(1.0, 1.0)
            self._player_mod_active = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Consolas", 10)
        painter.setFont(font)

        w = self.width()
        h = self.height()

        if not self.config.enabled:
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(10, 20, _tr("ESP OFF"))
            self._rendering = False
            return

        _esp = self.esp
        if _esp is None:
            painter.setPen(QPen(QColor(180, 180, 180)))
            painter.drawText(10, 20, _tr("Waiting for game..."))
            painter.setPen(QPen(QColor(100, 100, 100)))
            painter.drawText(10, 40, "Status: No Game Process")
            self._rendering = False
            return

        # Camera: read synchronously for pixel-accurate projection (fast, few reads)
        try:
            cam = _esp.get_camera()
        except Exception:
            cam = None

        # Players: from background thread cache (avoids freezing)
        with self._cache_lock:
            raw = self._cached_players
        all_players = list(raw)

        if not cam or not cam_valid(cam):
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(10, 20, _tr("NO CAMERA"))
            self._rendering = False
            return

        role_detection_ok = any(
            p.get("is_hunter") or p.get("is_survivor") for p in all_players
        )

        local_pos = None
        local_is_hunter = None
        local_is_survivor = None
        for p in all_players:
            if p["is_local"]:
                local_pos = p["pos"]
                local_is_hunter = p["is_hunter"]
                local_is_survivor = p["is_survivor"]
                break
        local_found = local_pos is not None
        local_has_role = local_found and (local_is_hunter or local_is_survivor)
        local_cm = norm_color_mode(self.config.color_mode)

        filtered = []
        for p in all_players:
            is_local = p["is_local"]
            pi_h = p.get("is_hunter", False)
            pi_s = p.get("is_survivor", False)
            pi_ghost = not is_local and not pi_h and not pi_s and role_detection_ok
            if pi_ghost:
                continue
            if is_local and self.config.filter_hide_self:
                continue
            if not local_has_role:
                filtered.append(p)
                continue
            is_unknown = not role_detection_ok and not is_local and not p.get("is_enemy", False)
            if not is_local and p.get("is_enemy", False) and self.config.filter_hide_enemy:
                continue
            if not is_local and not p.get("is_enemy", False) and not is_unknown and self.config.filter_hide_teammate:
                continue
            if is_unknown and self.config.filter_hide_unknown:
                continue
            filtered.append(p)
        all_players = filtered

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

            is_hunter = pdata.get("is_hunter", False)
            is_survivor = pdata.get("is_survivor", False)
            is_unknown = not role_detection_ok and not is_local and not is_enemy
            if not is_local and local_has_role:
                if is_hunter and not self.config.hunter_esp:
                    continue
                if is_survivor and not self.config.survivor_esp:
                    continue

            # --- Observer override: local player has no role reference yet ---
            observer_abs = not local_has_role and not is_local

            # Determine base color (team) and role color
            if is_local:
                base_color = self.config.local_color
            elif is_unknown:
                base_color = self.config.unknown_color
            elif is_enemy:
                base_color = self.config.enemy_color
            else:
                base_color = self.config.teammate_color

            role_color = None
            if is_hunter:
                role_color = self.config.hunter_visual_color
            elif is_survivor:
                role_color = self.config.survivor_visual_color

            # Color resolution: absolute/relative, with observer override
            if observer_abs:
                color = role_color if role_color else self.config.unknown_color
            elif local_cm == "absolute" and role_color:
                color = role_color
            else:
                color = base_color

            # Compute screen position (may be None for off-screen)
            screen_pos = w2s(pos, cam, w, h)

            # Skip on-screen rendering (dot/box/health/labels) if player is off-screen
            if not screen_pos:
                continue

            sx, sy = screen_pos
            sy += self.config.box_y_offset
            is_invincible = pdata.get("_invincible", False) and self.config.invincible_detect and not is_local

            # Snap line: bottom-center to player screen position (upstream reference logic)
            if self.config.snap_lines:
                painter.setPen(QPen(QColor(*color), 1))
                painter.drawLine(int(w / 2), int(h), int(sx), int(sy))
            dsx, dsy = clamp_screen(sx, sy - self.config.box_y_offset, w, h)
            dsy += self.config.box_y_offset

            if self.config.dot_esp:
                radius = int(self.config.dot_radius * scale)
                r = max(2, radius)
                self._draw_dot(painter, dsx, dsy, r, color)
                if is_invincible:
                    self._draw_invincible_x(painter, dsx, dsy, r)

            rot = pdata.get("_rot") if actor else None
            hw = self.config.box_height_world / 3.0
            pw = max(1, self.config.line_thickness)
            if self.config.box_esp and not self.config.corner_box:
                draw_2d_box(painter, pos, cam, w, h, self.config.box_height_world, hw, rot, color, scale, pw)
            if self.config.corner_box:
                draw_corner_box(painter, pos, cam, w, h, self.config.box_height_world, hw, rot, color, scale, 0.25, pw)

            if self.config.skeleton_esp and actor and not is_local:
                try:
                    bones = _esp.get_skeleton_positions(actor) or _esp.get_skeleton_positions_by_indices(actor, self.config.bone_indices) if _esp else None
                except Exception:
                    bones = None
                if bones:
                    draw_skeleton(painter, bones, cam, w, h, self.config.skeleton_color)

            if self.config.health_bar or self.config.shield_bar:
                hi = pdata.get("_health_info")
                if hi and hi[0] is not None:
                    hp, sh = hi
                    draw_health_bar(painter, dsx - 12 * scale, dsy - 20 * scale, 24 * scale, 4, hp, sh if self.config.shield_bar else None)

            label_parts = []
            if self.config.show_names:
                if is_local:
                    label_parts.append(_tr("YOU"))
                elif observer_abs:
                    label_parts.append(_tr("Player {idx}", idx=idx))
                elif is_unknown:
                    pass
                elif is_enemy:
                    label_parts.append(_tr("Enemy {idx}", idx=idx))
                else:
                    label_parts.append(_tr("Teammate {idx}", idx=idx))
            if self.config.show_roles and role != "Unknown":
                label_parts.append(_tr(role))
            if is_invincible:
                label_parts.append("[INV]")
            if self.config.show_distance:
                dm = int(d / 100)
                label_parts.append(f"{dm}m")
            if label_parts:
                label_x = int(dsx + self.config.dot_radius * scale + 4)
                label_y = int(dsy)
                painter.setPen(QPen(QColor(*color)))
                text = " | ".join(label_parts)
                painter.drawText(label_x, label_y, text)

        if self.config.draw_all and _esp:
            actor_count = 0
            try:
                for adata in _esp.iter_actors(max_actors=500, class_filter="Collectible"):
                    d = dist(adata["pos"], cam["loc"])
                    if d > self.config.draw_all_max_distance:
                        continue
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
            except Exception:
                pass
            if actor_count > 0:
                painter.setPen(QPen(QColor(150, 255, 150)))
                painter.drawText(w - 200, 60, _tr("Items: {count}", count=actor_count))

        status_parts = []
        status_parts.append(_tr("Players: {count}", count=len(all_players)))
        if cam:
            status_parts.append(_tr("Attached"))
        else:
            status_parts.append(_tr("Waiting..."))
        # #HyperVision status disabled
        # if self._hv_bridge_ok:
        #     status_parts.append("HV:ON")
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(10, 20, " | ".join(status_parts))

        # #HyperVision overlay disabled (not functional)
        # if self.config.hypervision_enabled and cam:
        #     try:
        #         for pt in self._hv_exposure_cloud:
        #             s = w2s((pt[0], pt[1], pt[2]) if not isinstance(pt, tuple) else pt, cam, w, h)
        #             if s:
        #                 dx, dy = int(s[0]), int(s[1])
        #                 painter.setPen(Qt.NoPen)
        #                 painter.setBrush(QColor(0, 255, 100, 40))
        #                 painter.drawEllipse(dx - 6, dy - 6, 12, 12)
        #         for path in self._hv_paths:
        #             pts_s = []
        #             for wp in path:
        #                 s = w2s((wp[0], wp[1], wp[2]), cam, w, h)
        #                 if s:
        #                     pts_s.append((int(s[0]), int(s[1])))
        #             for i in range(len(pts_s) - 1):
        #                 painter.setPen(QPen(QColor(0, 255, 50, 180), 2))
        #                 painter.drawLine(pts_s[i][0], pts_s[i][1], pts_s[i+1][0], pts_s[i+1][1])
        #             if pts_s:
        #                 painter.setPen(QPen(QColor(0, 255, 50), 3))
        #                 painter.setBrush(QColor(0, 255, 50, 180))
        #                 painter.drawEllipse(pts_s[-1][0] - 4, pts_s[-1][1] - 4, 8, 8)
        #     except Exception:
        #         pass

        if self.config.aimbot_enabled or self.config.magnet_enabled:
            cx, cy = w / 2, h / 2
            magnet_active = self.config.magnet_enabled and self._magnet_key_held()
            aim_active = self.config.aimbot_enabled and self._aim_key_held()
            if magnet_active:
                fov = self.config.magnet_fov
            elif self.config.aimbot_enabled:
                fov = self.config.aimbot_fov
            else:
                fov = 0
            best_target = self._find_best_target(cam, w, h, fov if fov > 0 else None)
            if best_target:
                if self.config.aimbot_show_fov and self.config.aimbot_enabled:
                    painter.setPen(QPen(QColor(255, 255, 255), 1))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(
                        int(cx - self.config.aimbot_fov),
                        int(cy - self.config.aimbot_fov),
                        self.config.aimbot_fov * 2,
                        self.config.aimbot_fov * 2,
                    )
                if magnet_active:
                    self._magnet_at(best_target[0], best_target[1])
                elif aim_active:
                    self._aim_at(best_target[0], best_target[1])

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
                pi_hunter = p.get("is_hunter", False)
                pi_survivor = p.get("is_survivor", False)
                pi_enemy = p.get("is_enemy", False)
                pi_ghost = not pi_hunter and not pi_survivor and role_detection_ok
                if pi_ghost:
                    p["color"] = self.config.unknown_color
                elif not local_has_role:
                    if pi_hunter:
                        p["color"] = self.config.hunter_visual_color
                    elif pi_survivor:
                        p["color"] = self.config.survivor_visual_color
                    else:
                        p["color"] = self.config.unknown_color
                else:
                    pi_unknown = not role_detection_ok and not pi_enemy
                    if pi_unknown:
                        p["color"] = self.config.unknown_color
                    elif pi_enemy:
                        p["color"] = self.config.enemy_color
                    else:
                        p["color"] = self.config.teammate_color
            draw_radar(painter, cam, local_pos, enemy_list,
                       radar_x, radar_y,
                       self.config.radar_size, self.config.radar_range,
                       self.config.radar_color, self.config.radar_opacity)

        self._rendering = False

    def _draw_dot(self, painter, cx, cy, r, color):
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(*color))
        painter.drawEllipse(int(cx - r), int(cy - r), r * 2, r * 2)

    def _draw_invincible_x(self, painter, cx, cy, r):
        gold = QColor(255, 215, 0)
        painter.setPen(QPen(gold, max(1, r // 2)))
        off = int(r * 0.4)
        painter.drawLine(int(cx - off), int(cy - off), int(cx + off), int(cy + off))
        painter.drawLine(int(cx + off), int(cy - off), int(cx - off), int(cy + off))

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

