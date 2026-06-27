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
    QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QColorDialog,
    QSpinBox, QDoubleSpinBox, QSlider, QListWidget, QStackedWidget,
)
from PyQt5.QtCore import Qt, QTimer, QObject, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QBrush, QPolygonF
from PyQt5.QtCore import QPointF

from meccha_chameleon_tools.core import (
    MecchaESP, rp, ru32, rfloat, wfloat, rvec3, rvec3_f, dist,
    read_array, OFFSETS,
)
from meccha_chameleon_tools.config import Config, save_config


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
    up = (-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp)
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
    # Shield bar (bottom)
    if shield_pct is not None and shield_pct > 0:
        sy = y + bar_h + spacing
        sfill = int(bar_w * min(shield_pct / 100.0, 1.0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 180))
        painter.drawRect(int(x), int(sy), int(bar_w), bar_h)
        painter.setBrush(QColor(0, 120, 255, 220))
        painter.drawRect(int(x), int(sy), int(sfill), bar_h)
    # Health bar (above)
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
                height_world, half_width_world, rot, color, scale=1.0):
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
        # Rotate around Y axis (yaw)
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
    # Draw connected lines for the 4 vertical edges
    painter.setPen(QPen(QColor(*color), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawRect(int(min_x), int(min_y), int(max_x - min_x), int(max_y - min_y))


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
    # Crosshair
    painter.drawLine(int(radar_cx - half), int(radar_cy), int(radar_cx + half), int(radar_cy))
    painter.drawLine(int(radar_cx), int(radar_cy - half), int(radar_cx), int(radar_cy + half))
    # Draw local player at center
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 255, 0, 220))
    painter.drawEllipse(int(radar_cx - 2), int(radar_cy - 2), 5, 5)
    # Draw enemies
    cam_yaw = math.radians(cam["rot"][1])
    for p in players:
        pos = p["pos"]
        dx = pos[0] - local_pos[0]
        dz = pos[2] - local_pos[2]
        d2d = math.sqrt(dx * dx + dz * dz)
        if d2d > radar_range or d2d < 1.0:
            continue
        # Rotate by inverse camera yaw
        angle = math.atan2(dx, dz) - cam_yaw
        r = (d2d / radar_range) * (half - 8)
        rx = radar_cx + r * math.sin(angle)
        ry = radar_cy - r * math.cos(angle)
        color_rgba = QColor(*p.get("color", color), 220) if not p["is_local"] else QColor(0, 255, 0, 220)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color_rgba)
        painter.drawEllipse(int(rx - 2), int(ry - 2), 5, 5)


# ---------------------------------------------------------------------------
# Menu widget
# ---------------------------------------------------------------------------
class Menu(QWidget):
    STYLE = """
        QFrame {
            background-color: rgba(14, 14, 20, 240);
            border: 1px solid #2a2a3e;
            border-radius: 10px;
        }
        QLabel { color: #bbb; font-size: 11px; }
        QCheckBox { color: #ccc; font-size: 11px; spacing: 8px; padding: 1px 0; }
        QCheckBox::indicator { width: 15px; height: 15px; border-radius: 3px; border: 1px solid #444; background: #1a1a28; }
        QCheckBox::indicator:checked {
            background: #3a6ea5; border-color: #5a8ec5;
        }
        QComboBox {
            background-color: #333; color: #eee;
            border: 1px solid #555; padding: 4px;
        }
        QPushButton {
            background-color: #22223a; color: #ccc;
            border: 1px solid #33334a; padding: 5px 10px; border-radius: 5px;
            font-size: 11px;
        }
        QPushButton:hover { background-color: #2e2e4a; border-color: #4a4a6a; }
        QPushButton:pressed { background-color: #3a3a5a; }
        QSpinBox, QDoubleSpinBox {
            background-color: #1a1a28; color: #ccc;
            border: 1px solid #33334a; padding: 1px 3px; border-radius: 3px;
            font-size: 11px; min-height: 20px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus { border-color: #5a8ec5; }
    """

    def __init__(self, config: Config, esp: MecchaESP):
        super().__init__()
        self.config = config
        self.esp = esp
        self.setWindowTitle("Meccha Chameleon Tools")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None
        self._key_recorder = KeyRecorder(self._on_key_recorded)
        self._build_ui()
        self.setFixedSize(500, 560)

    def _close_app(self):
        QApplication.quit()

    def _on_key_recorded(self, name):
        self.config.aimbot_key = name
        self.lbl_aim_key.setText(f"Aim Key: {name}")
        self.btn_record_key.setEnabled(True)
        self.btn_record_key.setText("Record Key")

    def _build_ui(self):
        container = QFrame(self)
        container.setObjectName("menuFrame")
        container.setStyleSheet(self.STYLE)
        outer = QVBoxLayout(container)
        outer.setContentsMargins(12, 8, 12, 8)
        outer.setSpacing(6)

        # Title
        title = QLabel("MECCA CHAMELION TOOLS")
        title.setObjectName("titleLbl")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)

        # Tab list + stacked pages
        body = QHBoxLayout()
        body.setSpacing(8)

        self.tab_list = QListWidget()
        self.tab_list.setFixedWidth(90)
        self.tab_list.setFocusPolicy(Qt.NoFocus)
        self.tab_list.setStyleSheet("""
            QListWidget {
                background: #1a1a28; border: 1px solid #2a2a3e;
                border-radius: 6px; padding: 4px; outline: none;
            }
            QListWidget::item {
                color: #888; padding: 8px 6px; border-radius: 4px;
                font-size: 11px; font-weight: bold;
            }
            QListWidget::item:selected {
                background: #2a3a5a; color: #8ab4f8;
            }
            QListWidget::item:hover:!selected {
                background: #22223a; color: #aaa;
            }
        """)
        self.tab_list.addItems(["ESP","HEALTH","RADAR","AIMBOT","Camouflage"])
        self.tab_list.currentRowChanged.connect(self._switch_tab)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")

        self._pages = {}
        for tab_name in ["ESP","HEALTH","RADAR","AIMBOT","Camouflage"]:
            page = QWidget()
            page.setStyleSheet("background: transparent;")
            self._pages[tab_name] = page
            self.stack.addWidget(page)

        body.addWidget(self.tab_list)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        # Bottom bar
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_save = QPushButton("Save Config")
        self.btn_save.clicked.connect(self._save_config)
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self._close_app)
        self.btn_close.setStyleSheet("QPushButton { background-color: #3a1a1a; border-color: #5a2a2a; } QPushButton:hover { background-color: #5a2a2a; }")

        hint = QLabel("Ins/F1 toggle | Drag to move")
        hint.setStyleSheet("color: #555; font-size: 9px;")
        bar.addWidget(self.btn_save)
        bar.addWidget(self.btn_close)
        bar.addStretch()
        bar.addWidget(hint)
        outer.addLayout(bar)

        outer2 = QVBoxLayout(self)
        outer2.addWidget(container)
        outer2.setContentsMargins(0, 0, 0, 0)
        self.setLayout(outer2)

        # Build each tab page
        self._build_esp_tab()
        self._build_health_tab()
        self._build_radar_tab()
        self._build_aimbot_tab()
        self._build_camo_tab()

    def _switch_tab(self, idx):
        names = ["ESP","HEALTH","RADAR","AIMBOT","Camouflage"]
        if 0 <= idx < len(names):
            self.stack.setCurrentIndex(idx)

    def _build_esp_tab(self):
        p = self._pages["ESP"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        self.cb_enabled = self._chk("ESP Enabled","enabled")
        lo.addWidget(self.cb_enabled)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.cb_dot = self._chk("Dot","dot_esp")
        self.cb_box = self._chk("2D Box","box_esp")
        self.cb_skeleton = self._chk("Skeleton","skeleton_esp")
        row.addWidget(self.cb_dot)
        row.addWidget(self.cb_box)
        row.addWidget(self.cb_skeleton)
        lo.addLayout(row)
        for cfg, label in [("show_local","Show Local Player"), ("show_names","Show Names"),
                           ("show_distance","Show Distance"), ("snap_lines","Snap Lines"),
                           ("team_filter","Team Filter"), ("distance_scaling","Dist. Scaling")]:
            cb = self._chk(label, cfg)
            lo.addWidget(cb)
        dr = QHBoxLayout()
        dr.addWidget(QLabel("Dot Radius:"))
        self.spn_dot = QSpinBox()
        self.spn_dot.setRange(2, 32)
        self.spn_dot.setValue(self.config.dot_radius)
        self.spn_dot.valueChanged.connect(lambda v: setattr(self.config, "dot_radius", v))
        dr.addWidget(self.spn_dot)
        lo.addLayout(dr)
        lo.addStretch()

    def _build_health_tab(self):
        p = self._pages["HEALTH"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        self.cb_hp = self._chk("Health Bar","health_bar")
        self.cb_shield = self._chk("Shield Bar","shield_bar")
        lo.addWidget(self.cb_hp)
        lo.addWidget(self.cb_shield)
        hr = QHBoxLayout()
        hr.addWidget(QLabel("Model Height:"))
        self.spn_height = QSpinBox()
        self.spn_height.setRange(50, 250)
        self.spn_height.setValue(int(self.config.box_height_world))
        self.spn_height.valueChanged.connect(lambda v: setattr(self.config, "box_height_world", float(v)))
        hr.addWidget(self.spn_height)
        lo.addLayout(hr)
        yr = QHBoxLayout()
        yr.addWidget(QLabel("Y Offset:"))
        self.spn_yoff = QSpinBox()
        self.spn_yoff.setRange(-50, 50)
        self.spn_yoff.setValue(self.config.box_y_offset)
        self.spn_yoff.valueChanged.connect(lambda v: setattr(self.config, "box_y_offset", v))
        yr.addWidget(self.spn_yoff)
        lo.addLayout(yr)
        lo.addStretch()

    def _build_radar_tab(self):
        p = self._pages["RADAR"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(4, 4, 4, 4)
        lo.setSpacing(4)
        self.cb_radar = self._chk("Radar Enabled","radar_enabled")
        lo.addWidget(self.cb_radar)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Radar Size:"))
        self.spn_radar_size = QSpinBox()
        self.spn_radar_size.setRange(80, 400)
        self.spn_radar_size.setValue(self.config.radar_size)
        self.spn_radar_size.valueChanged.connect(lambda v: setattr(self.config, "radar_size", v))
        sr.addWidget(self.spn_radar_size)
        lo.addLayout(sr)
        rr = QHBoxLayout()
        rr.addWidget(QLabel("Radar Range:"))
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
        self.cb_aimbot = self._chk("Aimbot Enabled","aimbot_enabled")
        self.cb_aim_fov = self._chk("Show FOV Circle","aimbot_show_fov")
        lo.addWidget(self.cb_aimbot)
        lo.addWidget(self.cb_aim_fov)
        kr = QHBoxLayout()
        self.lbl_aim_key = QLabel("Aim Key: " + self.config.aimbot_key)
        self.btn_record_key = QPushButton("Record Key")
        self.btn_record_key.clicked.connect(self._start_aim_key_record)
        kr.addWidget(self.lbl_aim_key)
        kr.addWidget(self.btn_record_key)
        lo.addLayout(kr)
        fr = QHBoxLayout()
        fr.addWidget(QLabel("FOV Radius:"))
        self.spn_aim_fov = QSpinBox()
        self.spn_aim_fov.setRange(10, 600)
        self.spn_aim_fov.setValue(self.config.aimbot_fov)
        self.spn_aim_fov.valueChanged.connect(lambda v: setattr(self.config, "aimbot_fov", v))
        fr.addWidget(self.spn_aim_fov)
        lo.addLayout(fr)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Smooth:"))
        self.spn_aim_smooth = QDoubleSpinBox()
        self.spn_aim_smooth.setRange(0.01, 1.0)
        self.spn_aim_smooth.setSingleStep(0.05)
        self.spn_aim_smooth.setValue(self.config.aimbot_smooth)
        self.spn_aim_smooth.valueChanged.connect(lambda v: setattr(self.config, "aimbot_smooth", v))
        sr.addWidget(self.spn_aim_smooth)
        lo.addLayout(sr)
        ar = QHBoxLayout()
        ar.addWidget(QLabel("Target Offset:"))
        self.spn_aim_off = QSpinBox()
        self.spn_aim_off.setRange(-200, 200)
        self.spn_aim_off.setValue(int(self.config.aimbot_target_offset))
        self.spn_aim_off.valueChanged.connect(lambda v: setattr(self.config, "aimbot_target_offset", float(v)))
        ar.addWidget(self.spn_aim_off)
        lo.addLayout(ar)
        lo.addStretch()

    def _build_camo_tab(self):
        p = self._pages["Camouflage"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(6)
        hdr = QLabel("CAMOUFLAGE")
        hdr.setStyleSheet("font-size: 13px; font-weight: bold; color: #8ab4f8; padding: 2px 0;")
        lo.addWidget(hdr)
        self.cb_camo = self._chk("Enable Camouflage","camouflage_enabled")
        lo.addWidget(self.cb_camo)
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color: #2a2a3e;")
        lo.addWidget(sep)
        info = QLabel("Press F10 in-game to apply camouflage paint.\nThe tool auto-launches the bridge and triggers F10 for you.")
        info.setStyleSheet("color: #aaa; font-size: 11px; padding: 4px 0;")
        info.setWordWrap(True)
        lo.addWidget(info)
        self.lbl_camo_status = QLabel("Ready \u2014 Press F10 to paint")
        self.lbl_camo_status.setStyleSheet("color: #888; font-size: 10px; padding: 4px 0;")
        lo.addWidget(self.lbl_camo_status)
        btn_paint_now = QPushButton("Paint Now")
        btn_paint_now.setFixedHeight(32)
        btn_paint_now.setStyleSheet(
            "QPushButton { background-color: #2a4a3a; border: 1px solid #3a6a4a;"
            " border-radius: 4px; font-weight: bold; font-size: 12px; }"
            " QPushButton:hover { background-color: #3a6a4a; }"
        )
        btn_paint_now.clicked.connect(self._paint_camo_now)
        lo.addWidget(btn_paint_now)
        btn_stop_camo = QPushButton("Stop Camo (F9)")
        btn_stop_camo.setFixedHeight(32)
        btn_stop_camo.setStyleSheet(
            "QPushButton { background-color: #4a2a2a; border: 1px solid #6a3a3a;"
            " border-radius: 4px; font-weight: bold; font-size: 12px; }"
            " QPushButton:hover { background-color: #6a3a3a; }"
        )
        btn_stop_camo.clicked.connect(self._stop_camo_now)
        lo.addWidget(btn_stop_camo)
        lo.addStretch()

    def _chk(self, text, attr):
        cb = QCheckBox(text)
        cb.setChecked(getattr(self.config, attr))
        cb.stateChanged.connect(lambda s, a=attr: setattr(self.config, a, bool(s)))
        return cb

    def _start_aim_key_record(self):
        self.btn_record_key.setEnabled(False)
        self.btn_record_key.setText('Press key...')
        self._key_recorder.start()

    def _save_config(self):
        if save_config(self.config):
            self.btn_save.setText('Config Saved!')
            QTimer.singleShot(1500, lambda: self.btn_save.setText('Save Config'))
        else:
            self.btn_save.setText('Save Failed!')
            QTimer.singleShot(1500, lambda: self.btn_save.setText('Save Config'))

    def _paint_camo_now(self):
        if hasattr(self, '_camo_thread') and self._camo_thread and self._camo_thread.is_alive():
            return
        self.lbl_camo_status.setText("Painting...")
        self._camo_thread = threading.Thread(target=self._camo_menu_worker, daemon=True)
        self._camo_thread.start()

    def _camo_menu_worker(self):
        ok = self.esp.camo_apply()
        QTimer.singleShot(0, lambda: self._camo_menu_done(ok))

    def _camo_menu_done(self, ok):
        self.lbl_camo_status.setText("Painted!" if ok else "Paint failed")
        QTimer.singleShot(2000, lambda: self.lbl_camo_status.setText("Ready \u2014 Press F10 to paint"))

    def _stop_camo_now(self):
        if hasattr(self, '_stop_thread') and self._stop_thread and self._stop_thread.is_alive():
            return
        self.lbl_camo_status.setText("Stopping...")
        self._stop_thread = threading.Thread(target=self._stop_camo_worker, daemon=True)
        self._stop_thread.start()

    def _stop_camo_worker(self):
        ok = self.esp.camo_stop()
        QTimer.singleShot(0, lambda: self._stop_camo_done(ok))

    def _stop_camo_done(self, ok):
        self.lbl_camo_status.setText("Stopped" if ok else "Stop failed")
        QTimer.singleShot(2000, lambda: self.lbl_camo_status.setText("Ready \u2014 Press F10 to paint"))

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
    camo_done = pyqtSignal(bool)

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
        self._f9_feedback = ""
        self._f9_feedback_count = 0
        # Debounce counters for phantom GetAsyncKeyState reads
        self._f10_down_count = 0
        self._f10_up_count = 0
        self._f9_down_count = 0
        self._f9_up_count = 0
        self._camo_thread = None
        self._camo_stop_event = threading.Event()
        self.camo_done.connect(self._on_camo_done)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_overlay)
        self.timer.start(16)

        self.game_hwnd = self._find_game_window()
        self._resize_to_game()

        # Poll menu toggle key
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

    def update_overlay(self):
        self._resize_to_game()
        self.update()

    def _poll_keys(self):
        VK_INSERT = 0x2D
        VK_F1 = 0x70
        for vk, name in [(VK_INSERT, "insert"), (VK_F1, "f1")]:
            state = ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000
            if state and not self._key_states.get(name):
                for w in QApplication.topLevelWidgets():
                    if isinstance(w, Menu):
                        w.setVisible(not w.isVisible())
                        break
            self._key_states[name] = bool(state)
        # F10: Camouflage paint start (debounced against phantom GetAsyncKeyState reads)
        VK_F10 = 0x79
        f10_raw = bool(ctypes.windll.user32.GetAsyncKeyState(VK_F10) & 0x8000)
        if f10_raw:
            self._f10_down_count += 1
            self._f10_up_count = 0
        else:
            self._f10_up_count += 1
            self._f10_down_count = 0
        # fire only when key is held for >=2 consecutive polls AND was released for >=2 polls
        f10_armed = self._f10_up_count >= 2
        if self._f10_down_count >= 2 and f10_armed and not self._key_states.get("f10"):
            self._trigger_photo_paint()
            self._key_states["f10"] = True
            self._f10_up_count = 0
        if self._f10_down_count == 0:
            self._key_states["f10"] = False
        # F9: Camouflage paint stop (cancel) - debounced
        VK_F9 = 0x78
        f9_raw = bool(ctypes.windll.user32.GetAsyncKeyState(VK_F9) & 0x8000)
        if f9_raw:
            self._f9_down_count += 1
            self._f9_up_count = 0
        else:
            self._f9_up_count += 1
            self._f9_down_count = 0
        f9_armed = self._f9_up_count >= 2
        if self._f9_down_count >= 2 and f9_armed and not self._key_states.get("f9_camo"):
            self._trigger_camo_stop()
            self._key_states["f9_camo"] = True
            self._f9_up_count = 0
        if self._f9_down_count == 0:
            self._key_states["f9_camo"] = False
        # Decrement F10 feedback counter every poll tick
        if self._f9_feedback_count > 0:
            self._f9_feedback_count -= 1

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont("Consolas", 10)
        painter.setFont(font)

        w = self.width()
        h = self.height()

        if not self.config.enabled:
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(10, 20, "ESP OFF")
            return

        cam = self.esp.get_camera()
        if not cam:
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawText(10, 20, "NO CAMERA")
            return

        all_players = list(self.esp.iter_players(
            include_local=self.config.show_local,
            team_filter=self.config.team_filter,
        ))

        local_pos = None
        if all_players:
            for p in all_players:
                if p["is_local"]:
                    local_pos = p["pos"]
                    break

        for pdata in all_players:
            is_local = pdata["is_local"]
            pos = pdata["pos"]
            actor = pdata["actor"]
            ps = pdata["player_state"]
            idx = pdata["idx"]

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
            if is_local:
                color = self.config.local_color
            else:
                color = self.config.enemy_color

            dsx, dsy = clamp_screen(sx, sy - self.config.box_y_offset, w, h)
            dsy += self.config.box_y_offset

            if self.config.dot_esp:
                radius = int(self.config.dot_radius * scale)
                self._draw_dot(painter, dsx, dsy, max(2, radius), color)

            if self.config.box_esp:
                rot = self.esp.get_actor_root_rotation(actor) if actor else None
                hw = self.config.box_height_world / 3.0
                draw_2d_box(painter, pos, cam, w, h,
                            self.config.box_height_world, hw, rot, color, scale)

            if self.config.skeleton_esp and actor and not is_local:
                bones = self.esp.get_skeleton_positions(actor)
                if bones:
                    draw_skeleton(painter, bones, cam, w, h, self.config.skeleton_color)
                else:
                    indices = self.config.bone_indices
                    bones2 = self.esp.get_skeleton_positions_by_indices(actor, indices)
                    if bones2:
                        draw_skeleton(painter, bones2, cam, w, h, self.config.skeleton_color)

            if self.config.health_bar or self.config.shield_bar:
                health_info = self.esp.get_health(actor, ps)
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
                label_parts.append("YOU" if is_local else f"Enemy {idx}")
            if self.config.show_distance:
                dm = int(d / 100)
                label_parts.append(f"{dm}m")
            if label_parts:
                painter.setPen(QPen(QColor(*color)))
                text = " | ".join(label_parts)
                label_x = int(dsx + self.config.dot_radius * scale + 4)
                label_y = int(dsy)
                painter.drawText(label_x, label_y, text)

        non_local = [p for p in all_players if not p["is_local"]]
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(10, 20, f"Players: {len(non_local)}")

        if self._f9_feedback_count > 0 and self._f9_feedback:
            painter.setPen(QPen(QColor(0, 220, 120)))
            painter.drawText(10, 40, self._f9_feedback)
        else:
            painter.setPen(QPen(QColor(80, 80, 80)))
            painter.drawText(10, 40, "F10 = CAMOUFLAGE")

        if self.config.aimbot_enabled:
            cx, cy = w / 2, h / 2
            best_target = self._find_best_target(cam, w, h)
            if best_target:
                if self.config.aimbot_show_fov:
                    painter.setPen(QPen(QColor(255, 255, 255), 1))
                    painter.setBrush(Qt.NoBrush)
                    painter.drawEllipse(
                        int(cx - self.config.aimbot_fov),
                        int(cy - self.config.aimbot_fov),
                        self.config.aimbot_fov * 2,
                        self.config.aimbot_fov * 2,
                    )
                if self._aim_key_held():
                    self._aim_at(best_target[0], best_target[1])

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
    def _trigger_photo_paint(self):
        if self._camo_thread and self._camo_thread.is_alive():
            return
        self._f9_feedback = "PAINTING..."
        self._f9_feedback_count = 600
        self._camo_thread = threading.Thread(target=self._camo_worker, daemon=True)
        self._camo_thread.start()

    def _camo_worker(self):
        ok = self.esp.camo_apply()
        self.camo_done.emit(ok)

    def _on_camo_done(self, ok):
        if ok:
            self._f9_feedback = "CAMO F10 TRIGGERED"
            self._f9_feedback_count = 200
        else:
            if self._camo_stop_event.is_set():
                self._f9_feedback = "CAMO STOPPED (F9)"
            else:
                self._f9_feedback = "CAMO FAIL"
            self._f9_feedback_count = 120
        self._camo_thread = None
        self._camo_stop_event.clear()

    def _trigger_camo_stop(self):
        if not self._camo_thread or not self._camo_thread.is_alive():
            return
        self._camo_stop_event.set()
        self.esp.camo_stop()

    def _aim_key_held(self):
        vk = vk_from_name(self.config.aimbot_key)
        return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)

    def _find_best_target(self, camera, screen_w, screen_h):
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
            if d <= self.config.aimbot_fov and d < best_dist:
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
