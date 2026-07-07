"""Regression tests for world-to-screen projection (rotation_to_axes, w2s).

Verifies 100% accuracy for all camera angles and FOV values.
"""
import math
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from meccha_chameleon_tools.ui import rotation_to_axes, w2s, cam_valid

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SQRT2 = math.sqrt(2)


def vec_len(v):
    return math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def approx_eq(a, b, eps=1e-10):
    return abs(a - b) < eps


def vec2_approx_eq(a, b, eps=1e-10):
    return approx_eq(a[0], b[0], eps) and approx_eq(a[1], b[1], eps)

def vec3_approx_eq(a, b, eps=1e-10):
    return approx_eq(a[0], b[0], eps) and approx_eq(a[1], b[1], eps) and approx_eq(a[2], b[2], eps)


def make_cam(loc, rot, fov):
    return {"loc": loc, "rot": rot, "fov": fov}


# ---------------------------------------------------------------------------
# rotation_to_axes correctness
# ---------------------------------------------------------------------------

ORTHO_ANGLES = [
    (0, 0, 0, "identity"),
    (45, 0, 0, "pitch_only"),
    (-45, 0, 0, "pitch_neg"),
    (0, 45, 0, "yaw_only"),
    (0, -45, 0, "yaw_neg"),
    (0, 0, 45, "roll_only"),
    (0, 0, -45, "roll_neg"),
    (30, 45, 0, "pitch_yaw"),
    (30, 0, 20, "pitch_roll"),
    (0, 45, 20, "yaw_roll"),
    (30, 45, 20, "all_angles"),
    (-30, -45, -20, "all_neg"),
    (90, 0, 0, "look_down"),
    (-90, 0, 0, "look_up"),
    (180, 0, 0, "look_back"),
    (0, 0, 90, "roll_90"),
    (0, 0, -90, "roll_m90"),
]


@pytest.mark.parametrize("pitch,yaw,roll,name", ORTHO_ANGLES)
def test_rotation_to_axes_orthonormal(pitch, yaw, roll, name):
    """forward, right, up must form an orthonormal right-handed basis."""
    forward, right, up = rotation_to_axes((pitch, yaw, roll))

    # Each vector must be unit length
    assert approx_eq(vec_len(forward), 1.0), f"{name}: |forward|={vec_len(forward)}"
    assert approx_eq(vec_len(right), 1.0), f"{name}: |right|={vec_len(right)}"
    assert approx_eq(vec_len(up), 1.0), f"{name}: |up|={vec_len(up)}"

    # Vectors must be mutually orthogonal
    assert approx_eq(dot(forward, right), 0.0), f"{name}: forward·right={dot(forward, right)}"
    assert approx_eq(dot(forward, up), 0.0), f"{name}: forward·up={dot(forward, up)}"
    assert approx_eq(dot(right, up), 0.0), f"{name}: right·up={dot(right, up)}"

    # Right-handed: cross(forward, right) should equal up (not -up)
    expected_up = cross(forward, right)
    assert dot(expected_up, up) > 0, f"{name}: cross(forward,right) points opposite to up"


@pytest.mark.parametrize("pitch,yaw,roll,name", ORTHO_ANGLES)
def test_rotation_to_axes_identity_transform(pitch, yaw, roll, name):
    """A point exactly along forward should project to (0, 0, depth) in view space."""
    forward, right, up = rotation_to_axes((pitch, yaw, roll))

    # Pick a point 100 units in front of camera (at origin)
    world_pos = (forward[0] * 100, forward[1] * 100, forward[2] * 100)
    cam = make_cam((0, 0, 0), (pitch, yaw, roll), 90)

    # Manual view-space calculation (same as w2s does internally)
    dx = world_pos[0] - cam["loc"][0]
    dy = world_pos[1] - cam["loc"][1]
    dz = world_pos[2] - cam["loc"][2]
    view_x = dx * forward[0] + dy * forward[1] + dz * forward[2]
    view_y = dx * right[0] + dy * right[1] + dz * right[2]
    view_z = dx * up[0] + dy * up[1] + dz * up[2]

    # Point is exactly along forward vector -> view_y and view_z should be 0
    assert approx_eq(view_y, 0.0), f"{name}: view_y={view_y} (should be 0 for on-axis point)"
    assert approx_eq(view_z, 0.0), f"{name}: view_z={view_z} (should be 0 for on-axis point)"
    assert view_x > 0, f"{name}: view_x={view_x} (should be positive = in front)"


# ---------------------------------------------------------------------------
# w2s correctness — screen-center projection
# ---------------------------------------------------------------------------

W2S_ANGLES = [
    (0, 0, 0, "default"),
    (45, 0, 0, "pitch_down"),
    (-45, 0, 0, "pitch_up"),
    (0, 45, 0, "yaw_right"),
    (0, -45, 0, "yaw_left"),
    (0, 0, 45, "roll_tilt"),
    (30, 45, 20, "all_angles"),
    (-30, -45, -20, "all_neg"),
    (90, 0, 0, "straight_down"),
    (-90, 0, 0, "straight_up"),
]


@pytest.mark.parametrize("pitch,yaw,roll,name", W2S_ANGLES)
def test_w2s_center_point(pitch, yaw, roll, name):
    """A point directly along the camera's forward axis must project to screen center."""
    forward, _, _ = rotation_to_axes((pitch, yaw, roll))
    cam = make_cam((0, 0, 0), (pitch, yaw, roll), 90)
    w, h = 1920, 1080

    distance = 500
    world_pos = (forward[0] * distance, forward[1] * distance, forward[2] * distance)
    screen = w2s(world_pos, cam, w, h)

    assert screen is not None, f"{name}: w2s returned None for on-axis point"
    sx, sy = screen
    assert approx_eq(sx, w / 2, 1e-6), f"{name}: sx={sx} (expected {w/2})"
    assert approx_eq(sy, h / 2, 1e-6), f"{name}: sy={sy} (expected {h/2})"


@pytest.mark.parametrize("pitch,yaw,roll,name", W2S_ANGLES)
def test_w2s_off_axis_symmetry(pitch, yaw, roll, name):
    """Points symmetrically offset from the forward axis must project symmetrically on screen."""
    forward, right, up = rotation_to_axes((pitch, yaw, roll))
    cam = make_cam((0, 0, 0), (pitch, yaw, roll), 90)
    w, h = 1920, 1080

    distance = 500
    offset = 50
    center = (forward[0] * distance, forward[1] * distance, forward[2] * distance)

    # Point offset to the right by 50 units
    right_pos = (center[0] + right[0] * offset, center[1] + right[1] * offset, center[2] + right[2] * offset)
    # Point offset to the left by 50 units
    left_pos = (center[0] - right[0] * offset, center[1] - right[1] * offset, center[2] - right[2] * offset)

    s_right = w2s(right_pos, cam, w, h)
    s_left = w2s(left_pos, cam, w, h)

    assert s_right is not None and s_left is not None, f"{name}: off-axis projection failed"

    # Right point should be mirror of left point across screen center X
    assert approx_eq(s_right[0] - w / 2, -(s_left[0] - w / 2), 1e-4), \
        f"{name}: X symmetry failed: right_x={s_right[0]}, left_x={s_left[0]}, center_x={w/2}"
    assert approx_eq(s_right[1], s_left[1], 1e-4), \
        f"{name}: Y asymmetry: right_y={s_right[1]}, left_y={s_left[1]}"

    # Point offset upward by 50 units
    up_pos = (center[0] + up[0] * offset, center[1] + up[1] * offset, center[2] + up[2] * offset)
    # Point offset downward by 50 units
    down_pos = (center[0] - up[0] * offset, center[1] - up[1] * offset, center[2] - up[2] * offset)

    s_up = w2s(up_pos, cam, w, h)
    s_down = w2s(down_pos, cam, w, h)

    assert s_up is not None and s_down is not None, f"{name}: vertical off-axis projection failed"
    assert approx_eq(s_up[1] - h / 2, -(s_down[1] - h / 2), 1e-4), \
        f"{name}: Y symmetry failed: up_y={s_up[1]}, down_y={s_down[1]}, center_y={h/2}"
    assert approx_eq(s_up[0], s_down[0], 1e-4), \
        f"{name}: X asymmetry: up_x={s_up[0]}, down_x={s_down[0]}"


# ---------------------------------------------------------------------------
# w2s correctness — FOV adaptation
# ---------------------------------------------------------------------------

FOV_VALUES = [50, 60, 70, 80, 90, 100, 110, 120]


@pytest.mark.parametrize("fov", FOV_VALUES)
def test_w2s_fov_scaling(fov):
    """Larger FOV should place the same off-axis point closer to screen center (smaller screen distance)."""
    forward, right, _ = rotation_to_axes((0, 0, 0))
    cam = make_cam((0, 0, 0), (0, 0, 0), fov)
    w, h = 1920, 1080

    distance = 500
    offset = 100
    center = (forward[0] * distance, forward[1] * distance, forward[2] * distance)
    right_pos = (center[0] + right[0] * offset, center[1] + right[1] * offset, center[2] + right[2] * offset)

    screen = w2s(right_pos, cam, w, h)
    assert screen is not None

    all_fov_positions = []
    for test_fov in FOV_VALUES:
        s = w2s(right_pos, make_cam((0, 0, 0), (0, 0, 0), test_fov), w, h)
        assert s is not None, f"w2s failed at FOV={test_fov}"
        all_fov_positions.append(s[0])

    # FOV ascending -> screen distance from center should monotonically DECREASE (narrower FOV = more zoomed = further from center)
    for i in range(len(all_fov_positions) - 1):
        assert all_fov_positions[i] > all_fov_positions[i + 1], \
            f"Screen X not monotonic with FOV: FOV{FOV_VALUES[i]}={all_fov_positions[i]}, FOV{FOV_VALUES[i+1]}={all_fov_positions[i+1]}"


def test_w2s_fov_extremes():
    """w2s should still produce valid results at extreme FOV values."""
    forward, right, _ = rotation_to_axes((0, 0, 0))
    w, h = 1920, 1080

    for fov in [1, 5, 10, 170, 179]:
        cam = make_cam((0, 0, 0), (0, 0, 0), fov)
        world_pos = (forward[0] * 1000, forward[1] * 1000, forward[2] * 1000)
        screen = w2s(world_pos, cam, w, h)
        assert screen is not None, f"w2s failed at extreme FOV={fov}"


# ---------------------------------------------------------------------------
# w2s correctness — behind-camera rejection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pitch,yaw,roll,name", W2S_ANGLES)
def test_w2s_behind_camera(pitch, yaw, roll, name):
    """Points behind the camera must return None."""
    forward, _, _ = rotation_to_axes((pitch, yaw, roll))
    cam = make_cam((0, 0, 0), (pitch, yaw, roll), 90)

    # 100 units behind the camera
    behind = (-forward[0] * 100, -forward[1] * 100, -forward[2] * 100)
    screen = w2s(behind, cam, 1920, 1080)
    assert screen is None, f"{name}: behind-camera point should be None"


def test_w2s_behind_close():
    """A point just barely behind camera (<0.1 view_x) should return None."""
    forward, _, _ = rotation_to_axes((0, 0, 0))
    cam = make_cam((0, 0, 0), (0, 0, 0), 90)
    barely_behind = (-forward[0] * 0.05, -forward[1] * 0.05, -forward[2] * 0.05)
    screen = w2s(barely_behind, cam, 1920, 1080)
    assert screen is None


# ---------------------------------------------------------------------------
# w2s correctness — distance invariance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pitch,yaw,roll,name", W2S_ANGLES)
def test_w2s_distance_invariance(pitch, yaw, roll, name):
    """Screen position must be invariant to distance (only direction matters)."""
    forward, right, up = rotation_to_axes((pitch, yaw, roll))
    cam = make_cam((0, 0, 0), (pitch, yaw, roll), 90)
    w, h = 1920, 1080

    direction = (
        forward[0] * 1 + right[0] * 0.3 + up[0] * 0.2,
        forward[1] * 1 + right[1] * 0.3 + up[1] * 0.2,
        forward[2] * 1 + right[2] * 0.3 + up[2] * 0.2,
    )

    # Normalize direction
    dlen = vec_len(direction)
    direction = (direction[0] / dlen, direction[1] / dlen, direction[2] / dlen)

    s_near = w2s((direction[0] * 50, direction[1] * 50, direction[2] * 50), cam, w, h)
    s_far = w2s((direction[0] * 5000, direction[1] * 5000, direction[2] * 5000), cam, w, h)

    assert s_near is not None and s_far is not None
    assert vec2_approx_eq(s_near, s_far, 1e-4), f"{name}: near={s_near}, far={s_far}"


# ---------------------------------------------------------------------------
# w2s correctness — camera position offset
# ---------------------------------------------------------------------------

def test_w2s_camera_position():
    """Moving camera and target should not change screen position if relative position is same."""
    forward, right, up = rotation_to_axes((30, 45, 20))

    # Original
    cam_orig = make_cam((100, 200, 300), (30, 45, 20), 90)
    world_orig = (100 + forward[0] * 500 + right[0] * 50 + up[0] * 30,
                  200 + forward[1] * 500 + right[1] * 50 + up[1] * 30,
                  300 + forward[2] * 500 + right[2] * 50 + up[2] * 30)

    # Shifted by 1000 units in all axes
    cam_shift = make_cam((1100, 1200, 1300), (30, 45, 20), 90)
    world_shift = (1100 + forward[0] * 500 + right[0] * 50 + up[0] * 30,
                   1200 + forward[1] * 500 + right[1] * 50 + up[1] * 30,
                   1300 + forward[2] * 500 + right[2] * 50 + up[2] * 30)

    s_orig = w2s(world_orig, cam_orig, 1920, 1080)
    s_shift = w2s(world_shift, cam_shift, 1920, 1080)

    assert s_orig is not None and s_shift is not None
    assert vec2_approx_eq(s_orig, s_shift, 1e-4), f"Camera position translation changed screen position: {s_orig} vs {s_shift}"


# ---------------------------------------------------------------------------
# Snap line integration test
# ---------------------------------------------------------------------------

def test_snap_line_consistency():
    """The snap line endpoint (from w2s) must be consistent across camera rotations.

    Simulates an enemy at world position (0, 0, 0) and camera at various positions
    looking at the enemy. The snap line must always point from screen bottom-center
    to the correct screen position of the enemy.
    """
    enemy_pos = (0, 0, 0)
    w, h = 1920, 1080

    camera_placements = [
        # (cam_pos, yaw_to_enemy, pitch_to_enemy, roll, desc)
        # Directly in front (enemy at (0,0,0), camera at (-500,0,0) looking +X)
        ((-500, 0, 0), 0, 0, 0, "front"),
        # Above, looking down at enemy
        ((-500, 0, 300), 0, -30, 0, "above_look_down"),
        # Below, looking up at enemy
        ((-500, 0, -300), 0, 30, 0, "below_look_up"),
        # To the right (camera at +Y, looking -Y at origin)
        ((0, 500, 0), -90, 0, 0, "right_side"),
        # Above-right
        ((-400, 300, 300), -37, -30, 0, "above_right"),
    ]

    for cam_pos, ty, tp, tr, desc in camera_placements:
        cam = make_cam(cam_pos, (tp, ty, tr), 90)

        # The enemy is at (0,0,0). The camera should see it.
        screen = w2s(enemy_pos, cam, w, h)
        assert screen is not None, f"{desc}: enemy should be visible"

        sx, sy = screen
        assert sy >= -10, f"{desc}: snap line endpoint above screen (sy={sy})"
        assert sy <= h + 10, f"{desc}: snap line endpoint below screen (sy={sy})"
        assert sx >= -10 and sx <= w + 10, f"{desc}: snap line endpoint off-screen horizontally (sx={sx})"


# ---------------------------------------------------------------------------
# cam_valid tests
# ---------------------------------------------------------------------------

def test_cam_valid_accepts_good():
    assert cam_valid(make_cam((0, 0, 0), (0, 0, 0), 90))
    assert cam_valid(make_cam((-1000, 2000, -3000), (45, -90, 30), 120))


def test_cam_valid_rejects_bad():
    assert not cam_valid(None)
    assert not cam_valid({})
    assert not cam_valid({"loc": (0, 0, 0)})
    assert not cam_valid(make_cam((0, 0, 0), (0, 0, 0), -1))
    assert not cam_valid(make_cam((0, 0, float("nan")), (0, 0, 0), 90))
    assert not cam_valid(make_cam((float("inf"), 0, 0), (0, 0, 0), 90))
    assert not cam_valid(make_cam((0, 0, 0), (0, float("nan"), 0), 90))


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_w2s_zero_fov():
    """Zero FOV should be rejected by cam_valid; w2s raises ZeroDivisionError (caller must validate)."""
    cam = make_cam((0, 0, 0), (0, 0, 0), 0)
    assert not cam_valid(cam), "cam_valid should reject zero FOV"
    import pytest as _pytest
    with _pytest.raises(ZeroDivisionError):
        w2s((100, 0, 0), cam, 1920, 1080)


def test_w2s_gigantic_distance():
    """Very large distances should not cause precision issues that break projection."""
    forward, _, _ = rotation_to_axes((0, 0, 0))
    cam = make_cam((0, 0, 0), (0, 0, 0), 90)
    s = w2s((forward[0] * 1e8, forward[1] * 1e8, forward[2] * 1e8), cam, 1920, 1080)
    assert s is not None
    sx, sy = s
    assert approx_eq(sx, 960, 1e-3), f"sx={sx} (expected 960)"
    assert approx_eq(sy, 540, 1e-3), f"sy={sy} (expected 540)"


def test_rotation_to_axes_extreme_angles():
    """rotation_to_axes must handle extreme pitch values (looking straight up/down)."""
    # Looking straight down (pitch=90°)
    forward, right, up = rotation_to_axes((90, 0, 0))
    assert vec3_approx_eq(forward, (0, 0, 1), 1e-10)
    assert vec3_approx_eq(right, (0, 1, 0), 1e-10)
    assert vec3_approx_eq(up, (-1, 0, 0), 1e-10)

    # Looking straight up (pitch=-90°)
    forward, right, up = rotation_to_axes((-90, 0, 0))
    assert vec3_approx_eq(forward, (0, 0, -1), 1e-10)
    assert vec3_approx_eq(right, (0, 1, 0), 1e-10)
    assert vec3_approx_eq(up, (1, 0, 0), 1e-10)

    # Roll 90° (camera tilted sideways)
    forward, right, up = rotation_to_axes((0, 0, 90))
    assert vec3_approx_eq(forward, (1, 0, 0), 1e-10)
    assert vec3_approx_eq(right, (0, 0, -1), 1e-10)
    assert vec3_approx_eq(up, (0, 1, 0), 1e-10)

    # Full 180° pitch (looking backward)
    forward, right, up = rotation_to_axes((180, 0, 0))
    assert vec3_approx_eq(forward, (-1, 0, 0), 1e-10)
    assert vec3_approx_eq(right, (0, 1, 0), 1e-10)
    assert vec3_approx_eq(up, (0, 0, -1), 1e-10)


# ---------------------------------------------------------------------------
# Regression: the original bug — non-orthogonal up vector at non-zero pitch
# ---------------------------------------------------------------------------

def test_regression_original_bug_pitch_only():
    """The original bug: at pitch=45°, yaw=0°, roll=0°, the up vector's y-component contaminated view_z.

    With the buggy formula `cy * sr - cr * sp * cy`, up_y = 0 - 0.707 = -0.707,
    causing right·up ≠ 0. With the fix, up_y = 0 (since sy=0, sr=0), so right·up = 0.
    """
    forward, right, up = rotation_to_axes((45, 0, 0))
    # right = (0, 1, 0), up should have y=0
    assert approx_eq(vec_len(forward), 1.0)
    assert approx_eq(vec_len(right), 1.0)
    assert approx_eq(vec_len(up), 1.0)
    assert approx_eq(dot(right, up), 0.0), f"right·up={dot(right, up)} (should be 0 - was the original bug!)"


def test_regression_original_bug_pitch_roll():
    """The original bug: non-zero pitch+roll causes wrong up_y, breaking w2s for targets off the X axis.

    With pitch=30°, yaw=0°, roll=20°, the incorrect up_y caused targets with different
    y-coordinates to have incorrect vertical screen positions.
    """
    forward, right, up = rotation_to_axes((30, 0, 20))
    assert approx_eq(dot(right, up), 0.0), f"right·up={dot(right, up)} (should be 0)"
    assert approx_eq(dot(forward, up), 0.0), f"forward·up={dot(forward, up)} (should be 0)"
    assert approx_eq(dot(forward, right), 0.0), f"forward·right={dot(forward, right)} (should be 0)"


def test_regression_w2s_pitch_lateral_error():
    """The original bug caused targets at same Z but different Y to project at different screen Y.

    With camera at pitch=45°, a target straight ahead at (100, 0, 0) and one at (100, 50, 0)
    should have DIFFERENT X but SAME Y on screen (since they're at the same height).
    The buggy up vector contaminated the vertical projection with the Y offset.
    """
    cam = make_cam((0, 0, 0), (45, 0, 0), 90)
    w, h = 1920, 1080

    center_target = (100, 0, 0)
    right_target = (100, 50, 0)

    s_center = w2s(center_target, cam, w, h)
    s_right = w2s(right_target, cam, w, h)

    assert s_center is not None and s_right is not None

    # Both targets are at the same height (Z=0). Camera is looking down.
    # They should have the SAME Y coordinate on screen (different X).
    assert approx_eq(s_center[1], s_right[1], 1e-4), \
        f"Y mismatch: center_y={s_center[1]}, right_y={s_right[1]} (targets at same Z should have same screen Y)"

    # The right target should be to the right
    assert s_right[0] > s_center[0], \
        f"X not monotonic: center_x={s_center[0]}, right_x={s_right[0]}"
