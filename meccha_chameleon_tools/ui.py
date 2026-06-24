#!/usr/bin/env python3
"""Qt5 overlay and menu widgets for MECCHA CHAMELEON ESP."""
import math
import ctypes
import sys
import time
import webbrowser
from typing import Tuple, Optional

from PyQt5.QtWidgets import (
    QApplication, QWidget, QCheckBox, QComboBox, QLabel,
    QVBoxLayout, QHBoxLayout, QPushButton, QFrame, QColorDialog,
    QSpinBox, QDoubleSpinBox, QSlider, QStackedWidget, QButtonGroup,
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QBrush, QPolygonF, QPixmap, QFontMetrics
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
# GitHub banner widget
# ---------------------------------------------------------------------------
GITHUB_URL = "https://github.com/SilentJMA/Meccha-Chameleon-Tools"

# Official GitHub octocat silhouette (filled path, viewBox 24x24)
_GITHUB_OCTOCAT_SVG = b'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="#E6EDF3">
<path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/>
</svg>'''


def _render_octocat_pixmap(size=22):
    """Render the GitHub octocat icon to a QPixmap. Returns None on failure."""
    try:
        from PyQt5.QtSvg import QSvgRenderer
        renderer = QSvgRenderer(_GITHUB_OCTOCAT_SVG)
        if not renderer.isValid():
            return None
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        renderer.render(p)
        p.end()
        return pm
    except Exception:
        return None


class GithubBanner(QFrame):
    """Black GitHub-style banner with octocat icon + repo name. Clickable."""

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(46)
        self.setObjectName("githubBanner")
        self._apply_style(hover=False)

        lo = QHBoxLayout(self)
        lo.setContentsMargins(14, 6, 14, 6)
        lo.setSpacing(8)

        # Icon label (rendered SVG octocat or fallback star)
        self.lbl_icon = QLabel()
        pm = _render_octocat_pixmap(22)
        if pm is not None:
            self.lbl_icon.setPixmap(pm)
            self.lbl_icon.setStyleSheet("background: transparent;")
        else:
            self.lbl_icon.setText("\u2605")  # ★ fallback
            self.lbl_icon.setStyleSheet("color: #E6EDF3; font-size: 16px; background: transparent;")
        self.lbl_icon.setFixedSize(22, 22)
        lo.addWidget(self.lbl_icon)

        # "GitHub" title (bold white)
        self.lbl_title = QLabel("GitHub")
        self.lbl_title.setStyleSheet(
            "color: #E6EDF3; font-size: 11px; font-weight: bold; "
            "font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        lo.addWidget(self.lbl_title)

        # Separator dot
        self.lbl_sep = QLabel("\u00b7")
        self.lbl_sep.setStyleSheet(
            "color: #484F58; font-size: 13px; background: transparent;"
        )
        lo.addWidget(self.lbl_sep)

        # Repo path (gray, monospace-ish)
        self.lbl_repo = QLabel("SilentJMA / Meccha-Chameleon-Tools")
        self.lbl_repo.setStyleSheet(
            "color: #8B949E; font-size: 10px; "
            "font-family: 'Segoe UI', sans-serif; background: transparent;"
        )
        lo.addWidget(self.lbl_repo)

        lo.addStretch()

        # Arrow indicator
        self.lbl_arrow = QLabel("\u2197")  # ↗ north-east arrow
        self.lbl_arrow.setStyleSheet(
            "color: #8B949E; font-size: 14px; background: transparent;"
        )
        lo.addWidget(self.lbl_arrow)

    def _apply_style(self, hover=False):
        if hover:
            self.setStyleSheet("""
                QFrame#githubBanner {
                    background-color: #161B22;
                    border: 1px solid #8B949E;
                    border-radius: 8px;
                }
            """)
        else:
            self.setStyleSheet("""
                QFrame#githubBanner {
                    background-color: #0D1117;
                    border: 1px solid #30363D;
                    border-radius: 8px;
                }
            """)

    def enterEvent(self, event):
        self._apply_style(hover=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(hover=False)
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            webbrowser.open(self.url)


# ---------------------------------------------------------------------------
# Menu widget
# ---------------------------------------------------------------------------
TAB_NAMES = ["ESP", "HEALTH", "RADAR", "AIMBOT", "COLORS", "CAMO", "SETTINGS"]


class Menu(QWidget):
    STYLE = """
        QFrame#menuFrame {
            background-color: #0B0D14;
            border: 1px solid #161922;
            border-radius: 14px;
        }
        QLabel {
            color: #9CA3AF; font-size: 11px;
            font-family: "Segoe UI", "Inter", "SF Pro Text", sans-serif;
            background: transparent;
        }
        QLabel#titleLbl {
            color: #F3F4F6; font-size: 14px; font-weight: bold;
            letter-spacing: 4px; padding: 0;
        }
        QLabel#subtitleLbl {
            color: #5B6270; font-size: 9px; letter-spacing: 2px;
            padding: 2px 0 0 0;
        }
        QLabel#sectionLbl {
            color: #8B5CF6; font-size: 9px; font-weight: bold;
            letter-spacing: 2.5px; padding: 12px 0 4px 4px;
            background: transparent;
        }
        QLabel#hintLbl {
            color: #4B5563; font-size: 9px;
        }
        QLabel#statusOn {
            color: #10B981; font-size: 10px; font-weight: bold;
            padding: 4px 8px; background: transparent;
        }
        QLabel#statusOff {
            color: #6B7280; font-size: 10px; font-weight: bold;
            padding: 4px 8px; background: transparent;
        }
        QLabel#linkLbl {
            color: #8B5CF6; font-size: 10px; padding: 4px 0;
        }
        QLabel#linkLbl:hover { color: #A78BFA; }
        QCheckBox {
            color: #D1D5DB; font-size: 11px; spacing: 8px; padding: 3px 0;
            font-family: "Segoe UI", sans-serif; background: transparent;
        }
        QCheckBox::indicator {
            width: 14px; height: 14px; border-radius: 4px;
            border: 1px solid #2D3142; background: #161922;
        }
        QCheckBox::indicator:hover { border-color: #8B5CF6; }
        QCheckBox::indicator:checked {
            background: #8B5CF6; border-color: #A78BFA;
        }
        QComboBox {
            background-color: #161922; color: #E5E7EB;
            border: 1px solid #2D3142; padding: 4px 8px; border-radius: 6px;
            font-size: 11px; min-height: 20px;
        }
        QComboBox:hover { border-color: #8B5CF6; }
        QComboBox::drop-down { border: none; width: 20px; }
        QComboBox::down-arrow {
            image: none; border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            border-top: 5px solid #6B7280; width: 0; height: 0;
            margin-right: 6px;
        }
        QComboBox QAbstractItemView {
            background-color: #161922; color: #E5E7EB;
            selection-background-color: #8B5CF6; selection-color: #FFFFFF;
            border: 1px solid #2D3142; outline: none; padding: 4px;
        }
        QPushButton {
            background-color: #161922; color: #D1D5DB;
            border: 1px solid #2D3142; padding: 7px 14px; border-radius: 6px;
            font-size: 11px; font-family: "Segoe UI", sans-serif;
        }
        QPushButton:hover {
            background-color: #1B1F2E; border-color: #8B5CF6; color: #F3F4F6;
        }
        QPushButton:pressed { background-color: #11141D; }
        QPushButton#primaryBtn {
            background-color: #8B5CF6; border: 1px solid #A78BFA;
            color: #FFFFFF; font-weight: bold;
        }
        QPushButton#primaryBtn:hover {
            background-color: #A78BFA; border-color: #C4B5FD;
        }
        QPushButton#primaryBtn:pressed { background-color: #7C3AED; }
        QPushButton#dangerBtn {
            background-color: #161922; border: 1px solid #3B1D1D; color: #FCA5A5;
        }
        QPushButton#dangerBtn:hover {
            background-color: #1F1518; border-color: #DC2626; color: #FEE2E2;
        }
        QSpinBox, QDoubleSpinBox {
            background-color: #161922; color: #E5E7EB;
            border: 1px solid #2D3142; padding: 3px 6px; border-radius: 4px;
            font-size: 11px; min-height: 20px; min-width: 70px;
        }
        QSpinBox:focus, QDoubleSpinBox:focus { border-color: #8B5CF6; }
        QSpinBox::up-button, QDoubleSpinBox::up-button {
            background-color: #1B1F2E; border: none; width: 16px; border-radius: 2px;
        }
        QSpinBox::down-button, QDoubleSpinBox::down-button {
            background-color: #1B1F2E; border: none; width: 16px; border-radius: 2px;
        }
        QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
        QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
            background-color: #8B5CF6;
        }
        QSlider::groove:horizontal {
            border: none; height: 4px; background: #161922; border-radius: 2px;
        }
        QSlider::sub-page:horizontal {
            background: #8B5CF6; border-radius: 2px;
        }
        QSlider::handle:horizontal {
            background: #F3F4F6; border: 2px solid #8B5CF6;
            width: 12px; height: 12px; margin: -6px 0; border-radius: 9px;
        }
        QSlider::handle:horizontal:hover {
            background: #A78BFA; border-color: #C4B5FD;
        }
    """

    TAB_BTN_STYLE = """
        QPushButton {
            background: transparent;
            border: none;
            color: #5B6270;
            padding: 11px 10px;
            text-align: left;
            font-size: 10px;
            font-weight: bold;
            letter-spacing: 1.5px;
            border-radius: 6px;
            font-family: "Segoe UI", sans-serif;
        }
        QPushButton:hover:!checked {
            background: #161922;
            color: #D1D5DB;
        }
        QPushButton:checked {
            background: #8B5CF6;
            color: #FFFFFF;
        }
        QPushButton:checked:hover {
            background: #A78BFA;
        }
    """

    def __init__(self, config: Config, esp: MecchaESP):
        super().__init__()
        self.config = config
        self.esp = esp
        # Ensure auto_start_with_game attribute exists on config (for older Config classes)
        if not hasattr(self.config, 'auto_start_with_game'):
            setattr(self.config, 'auto_start_with_game', False)
        self.setWindowTitle("Meccha Chameleon Tools")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self._drag_pos = None
        self._key_recorder = KeyRecorder(self._on_key_recorded)
        self._build_ui()
        self.setFixedSize(560, 640)
        # Auto-start polling timer (checks for game window every 2s)
        self._auto_start_timer = QTimer(self)
        self._auto_start_timer.timeout.connect(self._poll_auto_start)
        self._auto_start_timer.start(2000)
        self._poll_auto_start()  # initial check

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
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(10)

        # GitHub banner
        self.banner = GithubBanner(GITHUB_URL, container)
        outer.addWidget(self.banner)

        # Title block (with accent bar on left)
        title_row = QHBoxLayout()
        title_row.setSpacing(10)
        title_row.setContentsMargins(0, 0, 0, 0)
        accent = QFrame()
        accent.setFixedSize(3, 18)
        accent.setStyleSheet("background-color: #8B5CF6; border: none; border-radius: 1px;")
        title_row.addStretch()
        title_row.addWidget(accent)
        title = QLabel("MECCHA CHAMELEON TOOLS")
        title.setObjectName("titleLbl")
        title_row.addWidget(title)
        title_row.addStretch()
        outer.addLayout(title_row)
        subtitle = QLabel("ESP  \u2022  RADAR  \u2022  AIMBOT  \u2022  CAMOUFLAGE")
        subtitle.setObjectName("subtitleLbl")
        subtitle.setAlignment(Qt.AlignCenter)
        outer.addWidget(subtitle)

        # Tab list + stacked pages
        body = QHBoxLayout()
        body.setSpacing(10)

        # Tab bar (QPushButton-based for clean rendering, no QListWidget quirks)
        tab_container = QWidget()
        tab_container.setStyleSheet("background: transparent;")
        tab_lo = QVBoxLayout(tab_container)
        tab_lo.setContentsMargins(0, 0, 0, 0)
        tab_lo.setSpacing(2)
        self.tab_buttons = []
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for i, name in enumerate(TAB_NAMES):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setStyleSheet(self.TAB_BTN_STYLE)
            btn.clicked.connect(lambda checked=False, idx=i: self._switch_tab(idx))
            self.tab_group.addButton(btn, i)
            self.tab_buttons.append(btn)
            tab_lo.addWidget(btn)
        tab_lo.addStretch()
        tab_container.setFixedWidth(112)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("background: transparent;")
        self.stack.setFrameShape(QFrame.NoFrame)

        self._pages = {}
        for tab_name in TAB_NAMES:
            page = QWidget()
            page.setStyleSheet("background: transparent;")
            self._pages[tab_name] = page
            self.stack.addWidget(page)

        body.addWidget(tab_container)
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        # Bottom bar
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.btn_save = QPushButton("Save Config")
        self.btn_save.setObjectName("primaryBtn")
        self.btn_save.setCursor(Qt.PointingHandCursor)
        self.btn_save.clicked.connect(self._save_config)
        self.btn_close = QPushButton("Close")
        self.btn_close.setObjectName("dangerBtn")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self._close_app)

        hint = QLabel("Ins / F1 toggle  \u00b7  Drag to move")
        hint.setObjectName("hintLbl")
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
        self._build_colors_tab()
        self._build_camouflage_tab()
        self._build_settings_tab()

    def _switch_tab(self, idx):
        if 0 <= idx < len(TAB_NAMES):
            self.stack.setCurrentIndex(idx)
            # Keep button checked state in sync (in case tab switched programmatically)
            if idx < len(self.tab_buttons):
                self.tab_buttons[idx].setChecked(True)

    def _section(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("sectionLbl")
        return lbl

    def _build_esp_tab(self):
        p = self._pages["ESP"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)
        lo.addWidget(self._section("DISPLAY"))
        self.cb_enabled = self._chk("ESP Enabled", "enabled")
        lo.addWidget(self.cb_enabled)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.cb_dot = self._chk("Dot", "dot_esp")
        self.cb_box = self._chk("2D Box", "box_esp")
        self.cb_skeleton = self._chk("Skeleton", "skeleton_esp")
        for w in (self.cb_dot, self.cb_box, self.cb_skeleton):
            row.addWidget(w)
        lo.addLayout(row)
        lo.addWidget(self._section("OPTIONS"))
        for cfg, label in [("show_local", "Show Local Player"), ("show_names", "Show Names"),
                           ("show_distance", "Show Distance"), ("snap_lines", "Snap Lines"),
                           ("team_filter", "Team Filter"), ("distance_scaling", "Dist. Scaling")]:
            cb = self._chk(label, cfg)
            lo.addWidget(cb)
        lo.addWidget(self._section("SIZING"))
        dr = QHBoxLayout()
        dr.addWidget(QLabel("Dot Radius:"))
        self.spn_dot = QSpinBox()
        self.spn_dot.setRange(2, 32)
        self.spn_dot.setValue(self.config.dot_radius)
        self.spn_dot.valueChanged.connect(lambda v: setattr(self.config, "dot_radius", v))
        dr.addWidget(self.spn_dot)
        dr.addStretch()
        lo.addLayout(dr)
        lo.addStretch()

    def _build_health_tab(self):
        p = self._pages["HEALTH"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)
        lo.addWidget(self._section("BARS"))
        self.cb_hp = self._chk("Health Bar", "health_bar")
        self.cb_shield = self._chk("Shield Bar", "shield_bar")
        lo.addWidget(self.cb_hp)
        lo.addWidget(self.cb_shield)
        lo.addWidget(self._section("MODEL"))
        hr = QHBoxLayout()
        hr.addWidget(QLabel("Model Height:"))
        self.spn_height = QSpinBox()
        self.spn_height.setRange(50, 250)
        self.spn_height.setValue(int(self.config.box_height_world))
        self.spn_height.valueChanged.connect(lambda v: setattr(self.config, "box_height_world", float(v)))
        hr.addWidget(self.spn_height)
        hr.addStretch()
        lo.addLayout(hr)
        yr = QHBoxLayout()
        yr.addWidget(QLabel("Y Offset:"))
        self.spn_yoff = QSpinBox()
        self.spn_yoff.setRange(-50, 50)
        self.spn_yoff.setValue(self.config.box_y_offset)
        self.spn_yoff.valueChanged.connect(lambda v: setattr(self.config, "box_y_offset", v))
        yr.addWidget(self.spn_yoff)
        yr.addStretch()
        lo.addLayout(yr)
        lo.addStretch()

    def _build_radar_tab(self):
        p = self._pages["RADAR"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)
        lo.addWidget(self._section("RADAR"))
        self.cb_radar = self._chk("Radar Enabled", "radar_enabled")
        lo.addWidget(self.cb_radar)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Radar Size:"))
        self.spn_radar_size = QSpinBox()
        self.spn_radar_size.setRange(80, 400)
        self.spn_radar_size.setValue(self.config.radar_size)
        self.spn_radar_size.valueChanged.connect(lambda v: setattr(self.config, "radar_size", v))
        sr.addWidget(self.spn_radar_size)
        sr.addStretch()
        lo.addLayout(sr)
        rr = QHBoxLayout()
        rr.addWidget(QLabel("Radar Range:"))
        self.spn_radar_range = QSpinBox()
        self.spn_radar_range.setRange(1000, 50000)
        self.spn_radar_range.setSingleStep(500)
        self.spn_radar_range.setValue(int(self.config.radar_range))
        self.spn_radar_range.valueChanged.connect(lambda v: setattr(self.config, "radar_range", float(v)))
        rr.addWidget(self.spn_radar_range)
        rr.addStretch()
        lo.addLayout(rr)
        lo.addStretch()

    def _build_aimbot_tab(self):
        p = self._pages["AIMBOT"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)
        lo.addWidget(self._section("AIMBOT"))
        self.cb_aimbot = self._chk("Aimbot Enabled", "aimbot_enabled")
        self.cb_aim_fov = self._chk("Show FOV Circle", "aimbot_show_fov")
        lo.addWidget(self.cb_aimbot)
        lo.addWidget(self.cb_aim_fov)
        lo.addWidget(self._section("KEY"))
        kr = QHBoxLayout()
        self.lbl_aim_key = QLabel("Aim Key: " + self.config.aimbot_key)
        self.btn_record_key = QPushButton("Record Key")
        self.btn_record_key.setCursor(Qt.PointingHandCursor)
        self.btn_record_key.clicked.connect(self._start_aim_key_record)
        kr.addWidget(self.lbl_aim_key)
        kr.addWidget(self.btn_record_key)
        kr.addStretch()
        lo.addLayout(kr)
        lo.addWidget(self._section("TUNING"))
        fr = QHBoxLayout()
        fr.addWidget(QLabel("FOV Radius:"))
        self.spn_aim_fov = QSpinBox()
        self.spn_aim_fov.setRange(10, 600)
        self.spn_aim_fov.setValue(self.config.aimbot_fov)
        self.spn_aim_fov.valueChanged.connect(lambda v: setattr(self.config, "aimbot_fov", v))
        fr.addWidget(self.spn_aim_fov)
        fr.addStretch()
        lo.addLayout(fr)
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Smooth:"))
        self.spn_aim_smooth = QDoubleSpinBox()
        self.spn_aim_smooth.setRange(0.01, 1.0)
        self.spn_aim_smooth.setSingleStep(0.05)
        self.spn_aim_smooth.setValue(self.config.aimbot_smooth)
        self.spn_aim_smooth.valueChanged.connect(lambda v: setattr(self.config, "aimbot_smooth", v))
        sr.addWidget(self.spn_aim_smooth)
        sr.addStretch()
        lo.addLayout(sr)
        ar = QHBoxLayout()
        ar.addWidget(QLabel("Target Offset:"))
        self.spn_aim_off = QSpinBox()
        self.spn_aim_off.setRange(-200, 200)
        self.spn_aim_off.setValue(int(self.config.aimbot_target_offset))
        self.spn_aim_off.valueChanged.connect(lambda v: setattr(self.config, "aimbot_target_offset", float(v)))
        ar.addWidget(self.spn_aim_off)
        ar.addStretch()
        lo.addLayout(ar)
        lo.addStretch()

    def _build_colors_tab(self):
        p = self._pages["COLORS"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(6)
        lo.addWidget(self._section("COLOR PICKER"))
        self.btn_enemy_color = QPushButton("Enemy Color")
        self.btn_enemy_color.setCursor(Qt.PointingHandCursor)
        self.btn_enemy_color.clicked.connect(lambda: self._pick_color("enemy_color"))
        self.btn_local_color = QPushButton("Local Color")
        self.btn_local_color.setCursor(Qt.PointingHandCursor)
        self.btn_local_color.clicked.connect(lambda: self._pick_color("local_color"))
        self.btn_skeleton_color = QPushButton("Skeleton Color")
        self.btn_skeleton_color.setCursor(Qt.PointingHandCursor)
        self.btn_skeleton_color.clicked.connect(lambda: self._pick_color("skeleton_color"))
        lo.addWidget(self.btn_enemy_color)
        lo.addWidget(self.btn_local_color)
        lo.addWidget(self.btn_skeleton_color)
        hint = QLabel("Click a button to open the color picker.")
        hint.setObjectName("hintLbl")
        lo.addWidget(hint)
        lo.addStretch()

    def _build_camouflage_tab(self):
        p = self._pages["CAMO"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)
        lo.addWidget(self._section("CAMOUFLAGE  (WIP)"))
        self.cb_camo = self._chk("Camouflage Enabled (WIP - In Progress)", "camouflage_enabled")
        lo.addWidget(self.cb_camo)
        lbl = QLabel("Press F10 to sample and apply camouflage (WIP)")
        lbl.setObjectName("hintLbl")
        lo.addWidget(lbl)
        lo.addWidget(self._section("SAMPLING"))
        sr = QHBoxLayout()
        sr.addWidget(QLabel("Sample Grid:"))
        self.spn_camo_size = QSpinBox()
        self.spn_camo_size.setRange(3, 30)
        self.spn_camo_size.setValue(self.config.camouflage_sample_size)
        self.spn_camo_size.valueChanged.connect(lambda v: setattr(self.config, "camouflage_sample_size", v))
        sr.addWidget(self.spn_camo_size)
        sr.addWidget(QLabel("(N\u00d7N)"))
        sr.addStretch()
        lo.addLayout(sr)
        # Opacity slider
        or_ = QHBoxLayout()
        or_.addWidget(QLabel("Blend:"))
        self.sld_camo_opacity = QSlider(Qt.Horizontal)
        self.sld_camo_opacity.setRange(0, 255)
        self.sld_camo_opacity.setValue(self.config.camouflage_opacity)
        self.sld_camo_opacity.valueChanged.connect(lambda v: setattr(self.config, "camouflage_opacity", v))
        or_.addWidget(self.sld_camo_opacity)
        self.lbl_camo_val = QLabel(str(self.config.camouflage_opacity))
        self.lbl_camo_val.setStyleSheet("color: #E5E7EB; font-size: 11px; min-width: 30px;")
        self.sld_camo_opacity.valueChanged.connect(lambda v: self.lbl_camo_val.setText(str(v)))
        or_.addWidget(self.lbl_camo_val)
        lo.addLayout(or_)
        lo.addStretch()

    def _build_settings_tab(self):
        p = self._pages["SETTINGS"]
        lo = QVBoxLayout(p)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)
        lo.addWidget(self._section("AUTOMATION"))
        self.cb_auto_start = self._chk("Auto-start when game is detected", "auto_start_with_game")
        lo.addWidget(self.cb_auto_start)
        hint = QLabel("When enabled, this menu will automatically appear when the game window is detected.")
        hint.setObjectName("hintLbl")
        hint.setWordWrap(True)
        lo.addWidget(hint)
        lo.addWidget(self._section("GAME STATUS"))
        self.lbl_game_status = QLabel("\u25cf  Checking...")
        self.lbl_game_status.setObjectName("statusOff")
        lo.addWidget(self.lbl_game_status)
        lo.addWidget(self._section("ABOUT"))
        about = QLabel("Meccha Chameleon Tools \u2014 ESP / radar / aimbot / camouflage overlay for the Chameleon game.")
        about.setObjectName("hintLbl")
        about.setWordWrap(True)
        lo.addWidget(about)
        lo.addWidget(self._section("REPOSITORY"))
        link = QLabel(f'<a href="{GITHUB_URL}" style="color:#8B5CF6; text-decoration: none;">{GITHUB_URL}</a>')
        link.setObjectName("linkLbl")
        link.setOpenExternalLinks(True)
        link.setTextFormat(Qt.RichText)
        link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lo.addWidget(link)
        lo.addStretch()

    def _chk(self, text, attr):
        cb = QCheckBox(text)
        cb.setChecked(getattr(self.config, attr))
        cb.stateChanged.connect(lambda s, a=attr: setattr(self.config, a, bool(s)))
        return cb

    def _pick_color(self, attr):
        current = getattr(self.config, attr)
        c = QColorDialog.getColor(QColor(*current), self)
        if c.isValid():
            setattr(self.config, attr, (c.red(), c.green(), c.blue()))

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

    def _find_game_window(self):
        try:
            import win32gui
            return win32gui.FindWindow(None, "Chameleon  ")
        except Exception:
            return 0

    def _poll_auto_start(self):
        """Poll for game window and auto-show menu if toggle is enabled."""
        hwnd = self._find_game_window()
        game_running = bool(hwnd)
        # Update status label
        if hasattr(self, 'lbl_game_status'):
            if game_running:
                self.lbl_game_status.setText("\u25cf  Game detected")
                self.lbl_game_status.setObjectName("statusOn")
            else:
                self.lbl_game_status.setText("\u25cf  Waiting for game...")
                self.lbl_game_status.setObjectName("statusOff")
            # Force style refresh
            self.lbl_game_status.style().unpolish(self.lbl_game_status)
            self.lbl_game_status.style().polish(self.lbl_game_status)
        # Auto-show menu if enabled and game is detected
        if getattr(self.config, 'auto_start_with_game', False) and game_running:
            if not self.isVisible():
                self.show()
                self.raise_()
                self.activateWindow()

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
        self._camouflage_active = False
        self._camouflage_color = None  # Tuple[int,int,int] when sampled
        self._camo_key_held = False    # edge detection for F10
        self._camo_feedback = ""       # brief status text ("Sampling...", "Camo ON", etc.)
        self._camo_feedback_count = 0
        self._original_pawn_color = None  # (r,g,b) to restore when camo toggled off
        self._paint_indicator_active = False  # True when C++ mod paint pipeline is running
        self._paint_indicator_start = 0.0     # time.time() when paint started
        self._paint_indicator_est_sec = 10.0  # estimated duration (reduced from 60s)
        # F9 direct texture paint (independent of mod's F10 camo)
        self._f9_key_held = False
        self._f9_color = None        # (r,g,b) last sampled color
        self._f9_feedback = ""
        self._f9_feedback_count = 0
        self._paint_tiles = None       # list of (offset, data) for tile writes
        self._paint_tile_cursor = 0
        self._paint_tile_total = 0

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

        # Camouflage hotkey (F10)
        VK_F10 = 0x79
        f10_down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_F10) & 0x8000)
        if f10_down and not self._camo_key_held:
            if self.config.camouflage_enabled:
                self._toggle_camouflage()
                # Only show paint indicator when camouflage was actually toggled
                if self._camouflage_active:
                    self._paint_indicator_active = True
                    self._paint_indicator_start = time.time()
            else:
                # Brief feedback that camouflage is disabled
                self._camo_feedback = "CAMO DISABLED (Enable in menu)"
                self._camo_feedback_count = 120  # ~2 seconds
        self._camo_key_held = f10_down

        # F9: sample color and start tile-based texture paint
        VK_F9 = 0x78
        f9_down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_F9) & 0x8000)
        if f9_down and not self._f9_key_held:
            self._trigger_f9_paint()
        self._f9_key_held = f9_down

    def _toggle_camouflage(self):
        """Toggle camouflage on/off. When turning on, sample screen and write to 3D model."""
        if self._camouflage_active:
            # Turn OFF: restore original color
            restored = False
            if self._original_pawn_color:
                local_pawn = self.esp._get_local_pawn()
                if local_pawn:
                    r, g, b = self._original_pawn_color
                    restored = self.esp.set_camouflage_color(local_pawn, r, g, b)
            self._camouflage_active = False
            self._camouflage_color = None
            self._original_pawn_color = None
            self._camo_feedback = "RESTORED" if restored else "CAMO OFF"
            self._camo_feedback_count = 120
        else:
            # Turn ON: sample screen and apply to local pawn
            self._camo_feedback = "SAMPLING..."
            self._camo_feedback_count = 60
            color = self._sample_screen_color()
            if not color:
                self._camo_feedback = "SAMPLE FAIL"
                self._camo_feedback_count = 120
                return

            r, g, b = color
            local_pawn = self.esp._get_local_pawn()
            if not local_pawn:
                self._camo_feedback = "NO PAWN FOUND"
                self._camo_feedback_count = 120
                return

            # Save original color
            orig = self.esp.read_camouflage_color(local_pawn)
            if orig:
                self._original_pawn_color = orig

            # Apply new color to 3D model
            ok = self.esp.set_camouflage_color(local_pawn, r, g, b)
            if ok:
                self._camouflage_color = color
                self._camouflage_active = True
                self._camo_feedback = "CAMO ON"
                self._camo_feedback_count = 150
            else:
                self._camo_feedback = "MATL FAIL"
                self._camo_feedback_count = 120

    def _sample_screen_color(self):
        """Sample N×N pixels around crosshair. Tries game DC, desktop DC, then BitBlt fallback."""
        try:
            import win32gui
            w = self.width()
            h = self.height()
            if w < 100 or h < 100:
                return None
            cx, cy = w // 2, h // 2
            grid = self.config.camouflage_sample_size
            half = grid // 2

            # Try game window DC first, then desktop DC
            hdc = None
            hwnd_used = 0
            if self.game_hwnd:
                hdc = win32gui.GetDC(self.game_hwnd)
                hwnd_used = self.game_hwnd
            if not hdc:
                hdc = win32gui.GetDC(0)
            if not hdc:
                return None

            total = 0
            r_sum = g_sum = b_sum = 0
            CLR_INVALID = 0xFFFFFFFF
            for dx in range(-half, half + 1):
                for dy in range(-half, half + 1):
                    px = cx + dx * 4
                    py = cy + dy * 4
                    pixel = win32gui.GetPixel(hdc, px, py)
                    if pixel != CLR_INVALID:
                        r_sum += pixel & 0xFF
                        g_sum += (pixel >> 8) & 0xFF
                        b_sum += (pixel >> 16) & 0xFF
                        total += 1

            win32gui.ReleaseDC(hwnd_used, hdc)

            if total > 0:
                return (r_sum // total, g_sum // total, b_sum // total)

            # Fallback: BitBlt the crosshair region
            return self._sample_screen_bitblt(cx, cy, half)
        except Exception:
            return None

    def _sample_screen_bitblt(self, cx, cy, half):
        """Fallback: capture region via BitBlt then read pixels."""
        try:
            import win32gui, win32ui, win32con
            hwnd = self.game_hwnd if self.game_hwnd else 0
            hdc_src = win32gui.GetDC(hwnd) if hwnd else win32gui.GetDC(0)
            if not hdc_src:
                return None

            step = 4
            region_w = (half * 2 + 1) * step
            region_h = (half * 2 + 1) * step
            x0 = cx - half * step
            y0 = cy - half * step

            hdc_mem = win32gui.CreateCompatibleDC(hdc_src)
            bmp = win32gui.CreateCompatibleBitmap(hdc_src, region_w, region_h)
            win32gui.SelectObject(hdc_mem, bmp)

            win32gui.BitBlt(hdc_mem, 0, 0, region_w, region_h,
                           hdc_src, x0, y0, win32con.SRCCOPY)

            # Read pixels: GetBitmapBits returns bytes (BGR format)
            bits = win32gui.GetBitmapBits(bmp, True)

            win32gui.DeleteObject(bmp)
            win32gui.DeleteDC(hdc_mem)
            win32gui.ReleaseDC(hwnd, hdc_src)

            total = 0
            r_sum = g_sum = b_sum = 0
            stride = region_w * 4
            for dy in range(0, region_h, step):
                for dx in range(0, region_w, step):
                    idx = dy * stride + dx * 4
                    if idx + 3 < len(bits):
                        # BMP stores BGR, we want RGB
                        b = bits[idx]
                        g = bits[idx + 1]
                        r = bits[idx + 2]
                        r_sum += r
                        g_sum += g
                        b_sum += b
                        total += 1

            if total == 0:
                return None
            return (r_sum // total, g_sum // total, b_sum // total)
        except Exception:
            return None

    def _trigger_f9_paint(self):
        """F9 direct paint: sample screen color, write to paint texture."""
        self._f9_feedback = "PIX..."
        self._f9_feedback_count = 5
        color = self._sample_screen_color()
        if not color:
            self._f9_feedback = "NO SAMPLE"
            self._f9_feedback_count = 20
            return
        r, g, b = color
        self._f9_color = (r, g, b)
        local_pawn = self.esp._get_local_pawn()
        if not local_pawn:
            self._f9_feedback = "NO PAWN"
            self._f9_feedback_count = 20
            return
        # Try direct paint — this uses the texture write in set_camouflage_color
        ok = self.esp.set_camouflage_color(local_pawn, r, g, b)
        if ok:
            self._f9_feedback = f"PIX OK ({r},{g},{b})"
            self._f9_feedback_count = 30
            # Now queue tile-progressive paint for the visual "bit by bit" effect
            self._queue_tile_paint(local_pawn, r, g, b)
        else:
            self._f9_feedback = "PIX FAIL"
            self._f9_feedback_count = 20

    def _queue_tile_paint(self, pawn, r, g, b):
        """For F9 tile-progressive mode: find texture, split into tiles, queue writes.
        Each frame writes one tile, creating a 'painting' effect on the model."""
        comp = self.esp._find_runtime_paint_component(pawn)
        if not comp:
            return
        tex = None
        cls = self.esp.objects.obj_class(comp)
        if cls:
            tex = self.esp._find_texture_on_component(pawn)
        if not tex:
            return
        # Check tex_cache first
        if tex in self.esp._tex_cache:
            cached = self.esp._tex_cache[tex]
            dptr = cached["data_ptr"]
            sz = cached["size"]
        else:
            # Force cache by writing once more
            self.esp._write_texture_flat(tex, b, g, r)
            if tex not in self.esp._tex_cache:
                return
            cached = self.esp._tex_cache[tex]
            dptr = cached["data_ptr"]
            sz = cached["size"]
        # Split into tiles (16x16 grid)
        b_val = int(b)
        g_val = int(g)
        r_val = int(r)
        tile_count = 16
        tile_sz = sz // tile_count
        tiles = []
        for i in range(tile_count):
            offset = i * tile_sz
            actual_sz = tile_sz if i < tile_count - 1 else sz - offset
            # Build tile data
            tile_data = bytearray([b_val, g_val, r_val, 255]) * (actual_sz // 4)
            tiles.append((dptr + offset, bytes(tile_data)))
        self._paint_tiles = tiles
        self._paint_tile_cursor = 0
        self._paint_tile_total = len(tiles)
        self._f9_feedback = f"TILES {self._paint_tile_total}"
        self._f9_feedback_count = 10

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

        # Gather all player data
        all_players = list(self.esp.iter_players(
            include_local=self.config.show_local,
            team_filter=self.config.team_filter,
        ))

        # Get local player position for radar
        local_pos = None
        if all_players:
            for p in all_players:
                if p["is_local"]:
                    local_pos = p["pos"]
                    break

        # Draw each player
        for pdata in all_players:
            is_local = pdata["is_local"]
            pos = pdata["pos"]
            actor = pdata["actor"]
            ps = pdata["player_state"]
            idx = pdata["idx"]

            # Distance scaling
            d = dist(pos, cam["loc"])
            scale = 1.0
            if self.config.distance_scaling and d > 0:
                scale = self.config.scale_reference_dist / d
                scale = max(0.3, min(scale, 3.0))

            # Project center position
            screen_center = w2s(pos, cam, w, h)
            if not screen_center:
                continue

            sx, sy = screen_center
            sy += self.config.box_y_offset
            if is_local:
                color = self.config.local_color
            elif self._camouflage_active and self._camouflage_color:
                blend = self.config.camouflage_opacity / 255.0
                camo = self._camouflage_color
                orig = self.config.enemy_color
                color = (
                    int(camo[0] * blend + orig[0] * (1 - blend)),
                    int(camo[1] * blend + orig[1] * (1 - blend)),
                    int(camo[2] * blend + orig[2] * (1 - blend)),
                )
            else:
                color = self.config.enemy_color

            # Clamped coords for on-screen elements (dots, bars, labels)
            # Snap lines use raw sx/sy so they reach screen edges
            dsx, dsy = clamp_screen(sx, sy - self.config.box_y_offset, w, h)
            dsy += self.config.box_y_offset

            # Dot ESP
            if self.config.dot_esp:
                radius = int(self.config.dot_radius * scale)
                self._draw_dot(painter, dsx, dsy, max(2, radius), color)

            # 2D Box ESP
            if self.config.box_esp:
                rot = self.esp.get_actor_root_rotation(actor) if actor else None
                hw = self.config.box_height_world / 3.0
                draw_2d_box(painter, pos, cam, w, h,
                            self.config.box_height_world, hw, rot, color, scale)

            # Skeleton ESP
            if self.config.skeleton_esp and actor and not is_local:
                bones = self.esp.get_skeleton_positions(actor)
                if bones:
                    draw_skeleton(painter, bones, cam, w, h, self.config.skeleton_color)
                else:
                    # Fallback: try indexed bones
                    indices = self.config.bone_indices
                    bones2 = self.esp.get_skeleton_positions_by_indices(actor, indices)
                    if bones2:
                        draw_skeleton(painter, bones2, cam, w, h, self.config.skeleton_color)

            # Health / Shield bars
            if self.config.health_bar or self.config.shield_bar:
                health_info = self.esp.get_health(actor, ps)
                if health_info and health_info[0] is not None:
                    hp, sh = health_info
                    bar_x = dsx - 12 * scale
                    bar_y = dsy - 20 * scale
                    draw_health_bar(painter, bar_x, bar_y, 24 * scale, 4, hp, sh if self.config.shield_bar else None)

            # Snap lines
            if self.config.snap_lines:
                painter.setPen(QPen(QColor(*color), 1))
                painter.drawLine(int(w / 2), int(h), int(sx), int(sy))

            # Labels
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

        # Player count
        non_local = [p for p in all_players if not p["is_local"]]
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(10, 20, f"Players: {len(non_local)}")
        # Camouflage status — always show
        if self._camo_feedback_count > 0 and self._camo_feedback:
            self._camo_feedback_count -= 1
            if self._camouflage_active and self._camouflage_color:
                painter.setPen(QPen(QColor(*self._camouflage_color)))
            else:
                painter.setPen(QPen(QColor(200, 200, 200)))
            painter.drawText(10, 40, self._camo_feedback)
        elif self._camouflage_active and self._camouflage_color:
            painter.setPen(QPen(QColor(*self._camouflage_color)))
            painter.drawText(10, 40, "CAMO ON (F10)")
        elif self.config.camouflage_enabled:
            painter.setPen(QPen(QColor(80, 80, 80)))
            painter.drawText(10, 40, "CAMO OFF (F10)")

        # F9 direct paint feedback
        if self._f9_feedback_count > 0 and self._f9_feedback:
            self._f9_feedback_count -= 1
            painter.setPen(QPen(QColor(0, 220, 120)))
            painter.drawText(10, 56, self._f9_feedback)
        elif self._paint_tiles is not None:
            painter.setPen(QPen(QColor(0, 220, 120)))
            painter.drawText(10, 56, f"TILING {self._paint_tile_cursor}/{self._paint_tile_total}")
        else:
            painter.setPen(QPen(QColor(80, 80, 80)))
            painter.drawText(10, 56, "F9 = DIRECT PAINT")

        # F9 tile-progressive paint (writes tiles per frame for smooth effect)
        if self._paint_tiles is not None and self._paint_tile_cursor < self._paint_tile_total:
            tiles = self._paint_tiles
            cursor = self._paint_tile_cursor
            # Write up to 4 tiles per frame for faster completion
            batch_end = min(cursor + 4, self._paint_tile_total)
            for i in range(cursor, batch_end):
                addr, data = tiles[i]
                try:
                    self.esp.pm.write_bytes(addr, data, len(data))
                except Exception:
                    pass
            self._paint_tile_cursor = batch_end
            progress = batch_end / self._paint_tile_total
            bar_x, bar_y = 10, 80
            bar_w, bar_h = 200, 12
            painter.setPen(QPen(QColor(60, 60, 60), 1))
            painter.setBrush(QBrush(QColor(30, 30, 30)))
            painter.drawRect(bar_x, bar_y, bar_w, bar_h)
            fill_w = int(bar_w * progress)
            if fill_w > 0:
                painter.setBrush(QBrush(QColor(0, 220, 120)))
                painter.setPen(Qt.NoPen)
                painter.drawRect(bar_x + 1, bar_y + 1, max(1, fill_w - 2), bar_h - 2)
            painter.setPen(QPen(QColor(255, 255, 255)))
            painter.setBrush(Qt.NoBrush)
            painter.drawText(bar_x + 5, bar_y + 10, f"F9 TILE {batch_end}/{self._paint_tile_total}")
            if batch_end >= self._paint_tile_total:
                self._paint_tiles = None
                self._f9_feedback = "TILE DONE"
                self._f9_feedback_count = 30

        # Paint pipeline progress indicator (C++ mod activity)
        if self._paint_indicator_active:
            elapsed = time.time() - self._paint_indicator_start
            progress = min(1.0, elapsed / self._paint_indicator_est_sec)
            if progress >= 1.0:
                self._paint_indicator_active = False
            else:
                bar_x, bar_y = 10, 60
                bar_w, bar_h = 200, 16
                # Background
                painter.setPen(QPen(QColor(60, 60, 60), 1))
                painter.setBrush(QBrush(QColor(30, 30, 30)))
                painter.drawRect(bar_x, bar_y, bar_w, bar_h)
                # Fill
                fill_w = int(bar_w * progress)
                if fill_w > 0:
                    painter.setBrush(QBrush(QColor(0, 160, 230)))
                    painter.setPen(Qt.NoPen)
                    painter.drawRect(bar_x + 1, bar_y + 1, max(1, fill_w - 2), bar_h - 2)
                # Text
                painter.setPen(QPen(QColor(255, 255, 255)))
                painter.setBrush(Qt.NoBrush)
                painter.drawText(bar_x + 5, bar_y + 13, f"PAINTING... {int(progress * 100)}%")

        # Aimbot
        if self.config.aimbot_enabled:
            cx, cy = w / 2, h / 2
            if self.config.aimbot_show_fov:
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(
                    int(cx - self.config.aimbot_fov),
                    int(cy - self.config.aimbot_fov),
                    self.config.aimbot_fov * 2,
                    self.config.aimbot_fov * 2,
                )
            best_target = self._find_best_target(cam, w, h)
            if best_target and self._aim_key_held():
                self._aim_at(best_target)

        # Radar
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
                if dself < 50.0:
                    continue
            dcam = dist(pos, cam_loc)
            if dcam < 50.0:
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
                best_target = aim_pos
        return best_target

    def _vector_to_rotation(self, vec):
        x, y, z = vec
        length = math.sqrt(x * x + y * y + z * z)
        if length == 0:
            return (0.0, 0.0, 0.0)
        x, y, z = x / length, y / length, z / length
        pitch = math.degrees(math.asin(z))
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

    def _aim_at(self, target_pos):
        cam = self.esp.get_camera()
        if not cam:
            return
        current = self._read_control_rotation()
        if current is None:
            return
        dx = target_pos[0] - cam["loc"][0]
        dy = target_pos[1] - cam["loc"][1]
        dz = target_pos[2] - cam["loc"][2]
        target_rot = self._vector_to_rotation((dx, dy, dz))
        smooth = self.config.aimbot_smooth
        new_pitch = current[0] + (target_rot[0] - current[0]) * smooth
        new_yaw = current[1] + (target_rot[1] - current[1]) * smooth
        self._write_control_rotation((new_pitch, new_yaw, current[2]))
