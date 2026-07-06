#!/usr/bin/env python3
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Tuple, List

CONFIG_FILE = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "MecchaCamouflage", "esp_config.json"
)


@dataclass
class Config:
    # Language (EN, DE, FR, ES, CN, JP, KR)
    language: str = "EN"

    # Color mode: "team" | "role" | "hybrid"
    color_mode: str = "hybrid"

    # ESP basics
    enabled: bool = True
    dot_esp: bool = True
    box_esp: bool = False
    corner_box: bool = False
    skeleton_esp: bool = False
    show_local: bool = True
    show_names: bool = True
    show_roles: bool = True
    show_distance: bool = True
    snap_lines: bool = True
    team_filter: bool = False
    enemy_only: bool = False

    # Performance
    esp_fps: int = 30

    # Team-based colors
    enemy_color: Tuple[int, int, int] = (255, 0, 0)
    teammate_color: Tuple[int, int, int] = (255, 255, 0)
    local_color: Tuple[int, int, int] = (0, 255, 0)
    unknown_color: Tuple[int, int, int] = (0, 80, 180)

    # Role-based colors (override enemy_color per role when color_by_role is on)
    hunter_visual_color: Tuple[int, int, int] = (255, 60, 60)
    survivor_visual_color: Tuple[int, int, int] = (60, 180, 255)
    hunter_esp: bool = True
    survivor_esp: bool = True

    # Other colors
    skeleton_color: Tuple[int, int, int] = (0, 255, 255)
    box_color: Tuple[int, int, int] = (255, 255, 255)
    radar_color: Tuple[int, int, int] = (255, 255, 255)
    visible_color: Tuple[int, int, int] = (0, 255, 0)
    not_visible_color: Tuple[int, int, int] = (128, 0, 128)
    invincible_color: Tuple[int, int, int] = (255, 215, 0)

    # Filter: check to hide that category
    filter_hide_enemy: bool = False
    filter_hide_self: bool = False
    filter_hide_teammate: bool = False
    filter_hide_unknown: bool = False

    # Sizing
    dot_radius: int = 8
    box_height_world: float = 100.0
    box_y_offset: int = 0
    line_thickness: int = 1
    point_size: int = 2

    # Distance scaling
    distance_scaling: bool = True
    scale_reference_dist: float = 1500.0

    # Health bar
    health_bar: bool = True
    shield_bar: bool = True

    # Draw All (nearby actors)
    draw_all: bool = False
    draw_all_max_distance: float = 3000.0
    draw_all_names: bool = True

    # Invincible flag
    invincible_detect: bool = True

    # Disable too buried
    disable_buried: bool = True

    # Background geometry
    show_background_geo: bool = False

    # Show cursor
    show_cursor: bool = False

    # Aimbot
    aimbot_enabled: bool = False
    aimbot_key: str = "MB5"
    aimbot_fov: int = 150
    aimbot_smooth: float = 0.30
    aimbot_target_offset: float = 90.0
    aimbot_show_fov: bool = True
    aimbot_visible_check: bool = False

    # Magnet aim assist
    magnet_enabled: bool = False
    magnet_strength: float = 1.0
    magnet_fov: int = 90
    magnet_hold_key: str = "MB4"

    # Radar
    radar_enabled: bool = False
    radar_size: int = 180
    radar_range: float = 5000.0
    radar_opacity: int = 160

    # Player Mod
    player_speed_mult: float = 1.0
    player_jump_mult: float = 1.0
    player_mod_enabled: bool = False
    teleport_collectible_key: str = "Y"

    # Camouflage
    camouflage_enabled: bool = False
    camouflage_status: str = "Ready — Press F10 to paint"

    # Game directory
    game_directory: str = r"C:\Program Files (x86)\Steam\steamapps\common\MECCA CHAMELEON\Chameleon\Binaries\Win64"

    # Bone indices (fallback if name resolution fails)
    bone_indices: dict = field(default_factory=lambda: {
        "head": 66, "neck_01": 65, "spine_03": 52,
        "spine_02": 36, "spine_01": 5, "pelvis": 1,
        "clavicle_l": 13, "upperarm_l": 14, "lowerarm_l": 15, "hand_l": 16,
        "clavicle_r": 30, "upperarm_r": 31, "lowerarm_r": 32, "hand_r": 33,
        "thigh_l": 59, "calf_l": 60, "foot_l": 61,
        "thigh_r": 72, "calf_r": 73, "foot_r": 74,
    })


def config_to_dict(config: Config) -> dict:
    d = asdict(config)
    for key in ("enemy_color", "teammate_color", "local_color", "unknown_color",
                 "skeleton_color", "box_color", "radar_color", "visible_color",
                 "not_visible_color", "invincible_color",
                 "hunter_visual_color", "survivor_visual_color"):
        d[key] = list(d[key])
    return d


def config_from_dict(d: dict) -> Config:
    for key in ("enemy_color", "teammate_color", "local_color", "unknown_color",
                 "skeleton_color", "box_color", "radar_color", "visible_color",
                 "not_visible_color", "invincible_color",
                 "hunter_visual_color", "survivor_visual_color"):
        if key in d and isinstance(d[key], list):
            d[key] = tuple(d[key])
    if "bone_indices" in d and isinstance(d["bone_indices"], list):
        d["bone_indices"] = {k: v for k, v in d["bone_indices"]}
    return Config(**d)


def save_config(config: Config, path: str = CONFIG_FILE):
    try:
        d = config_to_dict(config)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        return True
    except Exception:
        return False


def load_config(path: str = CONFIG_FILE) -> Config:
    config = Config()
    if not os.path.exists(path):
        return config
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return config_from_dict(d)
    except Exception:
        return config
