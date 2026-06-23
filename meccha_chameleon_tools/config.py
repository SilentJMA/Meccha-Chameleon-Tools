#!/usr/bin/env python3
"""Config dataclass with JSON save/load persistence."""
import json
import os
from dataclasses import dataclass, field, asdict
from typing import Tuple, List

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "esp_config.json")


@dataclass
class Config:
    # ESP basics
    enabled: bool = True
    dot_esp: bool = True
    box_esp: bool = False
    skeleton_esp: bool = False
    show_local: bool = True
    show_names: bool = True
    show_distance: bool = True
    snap_lines: bool = True
    team_filter: bool = False

    # Colors
    enemy_color: Tuple[int, int, int] = (255, 0, 0)
    local_color: Tuple[int, int, int] = (0, 255, 0)
    skeleton_color: Tuple[int, int, int] = (0, 255, 255)
    box_color: Tuple[int, int, int] = (255, 255, 255)
    radar_color: Tuple[int, int, int] = (255, 255, 255)

    # Sizing
    dot_radius: int = 8
    box_height_world: float = 100.0
    box_y_offset: int = 0

    # Distance scaling
    distance_scaling: bool = True
    scale_reference_dist: float = 1500.0

    # Health bar
    health_bar: bool = True
    shield_bar: bool = True

    # Aimbot
    aimbot_enabled: bool = False
    aimbot_key: str = "MB5"
    aimbot_fov: int = 150
    aimbot_smooth: float = 0.30
    aimbot_target_offset: float = 90.0
    aimbot_show_fov: bool = True
    aimbot_visible_check: bool = False

    # Radar
    radar_enabled: bool = False
    radar_size: int = 180
    radar_range: float = 5000.0
    radar_opacity: int = 160

    # Camouflage
    camouflage_enabled: bool = False
    camouflage_sample_size: int = 10
    camouflage_opacity: int = 200

    # Bone indices (fallback if name resolution fails)
    # Common UE5 mannequin bone indices
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
    # Convert tuples to lists for JSON
    for key in ("enemy_color", "local_color", "skeleton_color", "box_color", "radar_color"):
        d[key] = list(d[key])
    return d


def config_from_dict(d: dict) -> Config:
    # Convert lists back to tuples
    for key in ("enemy_color", "local_color", "skeleton_color", "box_color", "radar_color"):
        if key in d and isinstance(d[key], list):
            d[key] = tuple(d[key])
    # Flatten bone_indices if stored as list of pairs
    if "bone_indices" in d and isinstance(d["bone_indices"], list):
        d["bone_indices"] = {k: v for k, v in d["bone_indices"]}
    return Config(**d)


def save_config(config: Config, path: str = CONFIG_FILE):
    try:
        d = config_to_dict(config)
        with open(path, "w") as f:
            json.dump(d, f, indent=2)
        return True
    except Exception:
        return False


def load_config(path: str = CONFIG_FILE) -> Config:
    config = Config()
    if not os.path.exists(path):
        return config
    try:
        with open(path) as f:
            d = json.load(f)
        return config_from_dict(d)
    except Exception:
        return config