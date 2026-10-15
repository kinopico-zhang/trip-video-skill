#!/usr/bin/env python3
"""V5: top-down north-up, re-paced per user feedback on V4.

V4 problems: too fast overall / blurry; ends rushed; view transitions abrupt.
V5 pacing (same 10s total):
  0.0-2.6   DEPARTURE, slow: 0.35s hold, ~300px/s roll, gentle 2.5x zoom
  2.6-4.15  up-transition, fast but eased over 1.55s (V4: 0.5s!)
  4.15-6.20 OVERVIEW 2.05s, plane slides along route at ~220px/s
  6.20-7.50 down-transition 1.3s
  7.5-10.0  LANDING, slow: ~350px/s approach, 90px/s rollout

Smoothness: schedules use CUBIC HERMITE with hand-set tangents -> velocity
is CONTINUOUS at every anchor (no V4-style stutter where smoothstep eased
to zero speed at each keyframe). blend_mid uses quintic (must clamp 0..1).
Keyframes at 0.1s (101 kfs) halve ES's piecewise-linear stepping.
Screen-speed rule: while camera follows the plane, ground speed ~0.10*H
so apparent motion stays <=~450 px/s at all zoom levels.
"""
import json
import math

from flight import (ll2ecef, alt_to_value, lon_to_value, lat_to_value,
                    kf, build_esp)
from flight10 import (S_TOTAL, point_at_s, DENSE, CUM, TOTAL, FPS, DUR)

MID_S = S_TOTAL / 2.0


def q(u):
    """Quintic smootherstep (used only where the curve must clamp)."""
    u = max(0.0, min(1.0, u))
    return u * u * u * (u * (u * 6.0 - 15.0) + 10.0)


def hermite(ckpt, t):
    """Piecewise cubic Hermite through (t, value, tangent) anchors.

    Tangent units: value/second; continuity at anchors by construction.
    """
    if t <= ckpt[0][0]:
        return ckpt[0][1]
    for i in range(len(ckpt) - 1):
        t0, v0, m0 = ckpt[i]
        t1, v1, m1 = ckpt[i + 1]
        if t <= t1:
            dt = t1 - t0
            u = (t - t0) / dt if dt > 0 else 1.0
            u2, u3 = u * u, u * u * u
            return ((2 * u3 - 3 * u2 + 1) * v0
                    + (u3 - 2 * u2 + u) * m0 * dt
                    + (-2 * u3 + 3 * u2) * v1
                    + (u3 - u2) * m1 * dt)
    return ckpt[-1][1]


# ---- plane along-track schedule: slow ends, fast middle ----
# (t, s, tangent m = ds/dt in m/s)
S_CKPT = [
    (0.00, 0.0, 0.0),
    (0.35, 0.0, 0.0),          # hold at threshold (opening beat)
    (1.70, 1900.0, 2200.0),    # takeoff roll
    (2.60, 5600.0, 5000.0),    # climb-out
    (3.30, 60000.0, 250000.0),   # gentle sprint while camera climbs fast
    (4.50, 640000.0, 450000.0),  # overview slide begins (high-alt sprint)
    (6.20, 1530000.0, 430000.0),  # overview slide ~220 px/s
    (6.80, 1779000.0, 6000.0),    # sprint done, camera sliding onto plane
    (7.50, 1781400.0, 3000.0),    # decelerated, 5.8km final
    (8.40, 1785000.0, 2400.0),    # final approach
    (9.25, S_TOTAL - 300.0, 700.0),  # touchdown
    (10.00, S_TOTAL, 0.0),         # rollout stop
]


def s_at_t(t):
    return hermite(S_CKPT, t)


# inverse: t at given s (for route 3D altitude profile)
_T_GRID = [i * 0.002 for i in range(int(TOTAL / 0.002) + 1)]
_S_GRID = [s_at_t(t) for t in _T_GRID]


def t_at_s(s):
    lo, hi = 0, len(_S_GRID) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if _S_GRID[mid] <= s:
            lo = mid
        else:
            hi = mid
    s0, s1 = _S_GRID[lo], _S_GRID[hi]
    u = (s - s0) / max(s1 - s0, 1e-9)
    return _T_GRID[lo] + (_T_GRID[hi] - _T_GRID[lo]) * u


# ---- altitude profile synced to s(t): 0 at both runway moments ----
# (t, alt, tangent m = dalt/dt m/s)
A_CKPT = [
    (0.00, 0.0, 0.0),
    (1.10, 0.0, 0.0),       # wheels down through the roll
    (1.70, 40.0, 90.0),     # lift-off
    (2.60, 900.0, 1600.0),
    (4.15, 10668.0, 0.0),   # level off at FL350 (tangent 0 = no overshoot)
    (6.20, 10668.0, 0.0),   # cruise
    (6.80, 3000.0, -4000.0),  # mid descent while camera slides on
    (7.50, 500.0, -600.0),  # 5.8km final
    (8.40, 200.0, -320.0),
    (9.25, 0.0, 0.0),       # touchdown, flared (tangent 0)
    (10.00, 0.0, 0.0),
]


def alt_at_t(t):
    return hermite(A_CKPT, t)


def plane_state(t):
    s = s_at_t(t)
    lat, lon, tan = point_at_s(s)
    return lat, lon, alt_at_t(t), tan


# ---- camera: nadir north-up, Hermite zoom schedule ----
# (t, H, tangent m = d(lnH)/dt) -- LOG space: a 128x zoom interpolated in
# value space has a ~x0.63/frame spike near the end; in log space the
# per-frame scale change is bounded and eases to x1.0 at both ends.
# Up-transition: H leads (2.6-3.7 climb while still over the plane),
# position blend trails (3.3-4.15) -> plane never leaves frame.
# Down-transition: position blend leads (6.2-7.0), H dives after (6.5-7.5).
H_CKPT = [
    (0.00, math.log(13000.0), 0.0),
    (2.60, math.log(32000.0), 0.20),
    (3.30, math.log(900000.0), 3.5),
    (3.70, math.log(3000000.0), 1.6),
    (4.15, math.log(5800000.0), 0.0),
    (6.80, math.log(5800000.0), 0.0),
    (8.00, math.log(45000.0), -0.5),
    (9.25, math.log(15500.0), -0.2),
    (10.00, math.log(13500.0), 0.0),
]


def h_at_t(t):
    return math.exp(hermite(H_CKPT, t))


def blend_pos(t):
    """0 = over the plane, 1 = route midpoint. Quintic (clamps 0..1).

    UP:   H rises first (2.6-3.7, camera holds -> no ground scroll), then
          the camera slides back to the midpoint (3.3-4.5) at 3M+ altitude.
    DOWN: camera slides onto the plane first (6.2-7.0, still high),
          then dives (6.5-7.5) with the plane locked centered.
    """
    if t <= 3.30:
        return 0.0
    if t <= 4.50:
        return q((t - 3.30) / 1.20)
    if t <= 6.20:
        return 1.0
    if t <= 7.00:
        return 1.0 - q((t - 6.20) / 0.80)
    return 0.0


def dest(lat, lon, brg, dist):
    R = 6371000.0
    la, lo, b, d = math.radians(lat), math.radians(lon), math.radians(brg), dist / R
    la2 = math.asin(math.sin(la) * math.cos(d) + math.cos(la) * math.sin(d) * math.cos(b))
    lo2 = lo + math.atan2(math.sin(b) * math.sin(d) * math.cos(la),
                          math.cos(d) - math.sin(la) * math.sin(la2))
    return math.degrees(la2), math.degrees(lo2)


def camera_s(t):
    """Camera ground-track arc length s.

    Up-transition: camera HOLDS at the 2.6s position through the whole
    up-blend (b=1 afterwards mixes it out -> continuous), while the plane
    sprints ahead and H climbs; only then is it at the midpoint.
    """
    b = blend_pos(t)
    if t < 2.60:
        s_follow = s_at_t(t)          # normal follow
    elif t < 4.50:
        s_follow = s_at_t(2.60)       # hold through the up-blend
    else:
        s_follow = s_at_t(t)
    return b * MID_S + (1.0 - b) * s_follow


def camera_state(t):
    s_cam = camera_s(t)
    clat, clon, _ = point_at_s(s_cam)
    h = h_at_t(t)
    tlat, tlon = dest(clat, clon, 0.0, 0.007 * h)  # target NORTH
    return (clat, clon, h), (tlat, tlon, 0.0)


if __name__ == "__main__":
    STEP = 0.1  # denser keyframes -> smoother ES interpolation
    cam = {"lon": [], "lat": [], "alt": []}
    tgt = {"lon": [], "lat": [], "alt": []}
    samples = []
    t = 0.0
    while t <= TOTAL + 1e-9:
        c, g = camera_state(t)
        tt = t / TOTAL
        cam["lon"].append(kf(tt, lon_to_value(c[1])))
        cam["lat"].append(kf(tt, lat_to_value(c[0])))
        cam["alt"].append(kf(tt, alt_to_value(c[2])))
        tgt["lon"].append(kf(tt, lon_to_value(g[1])))
        tgt["lat"].append(kf(tt, lat_to_value(g[0])))
        tgt["alt"].append(kf(tt, alt_to_value(g[2])))
        plat, plon, palt, _ = plane_state(t)
        samples.append({"t": round(t, 3), "lat": plat, "lon": plon, "alt": palt,
                        "cam": c, "tgt": g})
        t = round(t + STEP, 3)

    build_esp("HKG to CEB Flight.esp", "topdown10v5.esp",
              "HKG to CEB Topdown 10s V5", DUR, cam, tgt)

    route = []
    for i in range(len(DENSE)):
        s = CUM[i]
        tt = t_at_s(s)
        route.append([DENSE[i][0], DENSE[i][1], round(alt_at_t(tt), 1),
                      round(tt, 4)])

    frames = []
    for i in range(DUR + 1):
        t = i / FPS
        lat, lon, alt, tan = plane_state(t)
        frames.append({"t": round(t, 4), "lat": lat, "lon": lon, "alt": alt,
                       "s": round(s_at_t(t), 1), "tan": [round(c, 6) for c in tan]})

    meta = {
        "total": TOTAL, "fps": FPS, "frames": DUR, "s_total": S_TOTAL,
        "step": STEP,
        "hkg": [22.3080, 113.9185], "ceb": [10.3075, 123.9790],
        "route": route, "frames": frames, "samples": samples,
        "emoji_nose_deg": -44.18,
    }
    with open("flight_data10_top_v5.json", "w") as f:
        json.dump(meta, f)
    print("wrote topdown10v5.esp + flight_data10_top_v5.json "
          "(%d frames, %d kfs)" % (DUR + 1, len(samples)))

    # pacing report: screen speed = ds/dt / (3.265e-4 * H) while following
    print("\npacing check (screen px/s, camera-on-plane phases):")
    for t in (0.2, 0.8, 1.2, 1.6, 2.0, 2.4, 2.6, 7.6, 8.0, 8.6, 9.0, 9.4, 9.8):
        h = h_at_t(t)
        ds = (s_at_t(t + 0.05) - s_at_t(t - 0.05)) / 0.1
        pxs = ds / (3.265e-4 * h)
        lat, lon, alt, _ = plane_state(t)
        print("  t=%4.1f H=%8.0f  ds/dt=%9.0f m/s  screen=%5.0f px/s  alt=%6.0f"
              % (t, h, ds, pxs, alt))
    print("\nzoom check (H, per-frame scale change):")
    for t in (1.0, 2.0, 3.0, 3.4, 3.8, 5.0, 6.6, 7.0, 7.4, 8.0, 9.0, 9.6):
        h0 = h_at_t(t)
        h1 = h_at_t(t + 1.0 / 30.0)
        print("  t=%4.1f H=%9.0f  scale/frame x%.3f" % (t, h0, h1 / h0))
