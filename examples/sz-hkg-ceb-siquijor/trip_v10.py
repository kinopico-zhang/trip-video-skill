#!/usr/bin/env python3
"""V10 (data v30): 40.4s = 13.3s SZ/HK prefix with WALK transitions + journey.

v17 changes (user: 别画人, 动态虚线表示步行; U Story 结尾不出现汽车):
  - walk legs carry NO sprite -- the compositor draws only the growing
    dashed line (walk frames keep kind="walk" purely to separate legs);
    the data emoji table no longer has a "walk" entry
  - the ending tail [38.4, 40.4] is the MOTO holding at its U Story arrival
    anchor (the old "resort car" frames are gone; the moto is the final
    vehicle, drawn as current through the whole pull-back)

v16 changes (user: 口岸两侧/机场出发层到跑道/宿务机场落地 -- 中间虚线表示步行,
过关或机场步行 1-2s; 第 n+1 段载具提前在起点等候; 起点不加文字标签):

  prefix [0, 13.3] (trip30_seg0_szhk_v2.esp, 400 frames):
    0.00- 5.10  car_sz (BLUE) 清湖北站 -> 深圳湾口岸 (v15 schedule, unchanged)
    5.10- 6.30  WALK 1: 深圳湾口岸 SZ 落客 -> HK 上车点 (~230m, dashed)
    6.30-11.30  car_hk (YELLOW) HK 上车点 -> 一号客运大楼出发层 kerb
                (route_HK2_raw.json 31.2km: 深圳湾公路大桥 + 屯门至赤鱲角
                连接路 TMCLK 隧道, 真实出租车路线)
    11.30-12.80 WALK 2: T1 出发层 -> 07R 跑道口 (~4.0km, dashed)
    12.80-13.30 hold at the threshold (H settles 13km)
    t=13.3: camera_state == flight_v5.camera_state(0.0) BIT-EXACT, so the
    frozen flight render (topdown10v5) continues seamlessly.

  flight [13.3, 23.3]: frozen frames reused (+1.8s vs v15).
  walk3 [23.3, 24.8] (trip30_seg1_cebwalk.esp, 46 frames): CEB 落地滑出点
    -> 出发层 pickup ~1.3km; first kf = F5.camera_state(10.0) BIT-EXACT.
  drive v2 [24.8, 28.9] (trip30_seg2_drivev2.esp, 124 frames): old drive
    schedule minus the plane-park settle; last kf = V7.camera_state(14.5)
    (ferry esp first kf) BIT-EXACT.
  boat/moto [28.9, 38.4] + seg5 [38.4, 40.4]: frozen frames reused (+2.9s
    vs v15; seg5 esp itself is reused untouched, so no overview re-solve).

Walk easing = plateau hermite (smootherstep ramps tau=0.3s each side,
constant cruise between): peak speed L/(T-tau) stays under the 864px/s
screen budget (sinease would hit 1.5x that).  Walk route vertices are
sampled every 0.1s so the dashed line flips ahead->done progressively
right behind the walker.

Outputs: trip30_seg0_szhk_v2.esp, trip30_seg1_cebwalk.esp,
trip30_seg2_drivev2.esp, flight_data30.json.
"""
import json
import math

from trip_v6 import (Route, hermite, dest, ll2ecef, unit, sub,
                     DRIVE, S_CAR)
import flight_v5 as F5
import trip_v7 as V7
from flight import (kf, build_esp, lon_to_value, lat_to_value, alt_to_value,
                    find_attr)
from flight10 import WPTS

T2 = 13.3            # prefix duration
FPS = 30
DUR = int(40.4 * FPS)          # 1212 -> 1213 frames
STEP = 0.1

STATION = (22.6748222, 114.0353222)     # 清湖北站 [Tavily/GNSS]
PORT = (22.510099, 113.935025)          # 深圳湾口岸 SZ 落客 [OSRM junction]
PORT_HK = (22.508357, 113.936304)       # HK 上车点 (HK2 route start)
THRESH = WPTS[0]                        # (22.298, 113.903) RWY 07R threshold
DRIVE_START = (DRIVE.pts[0][0], DRIVE.pts[0][1])   # CEB 出发层 pickup
V5_END = F5.camera_state(10.0)[0][:2]   # CEB 落地滑出点 (frozen flight end)

SEAM = F5.camera_state(0.0)             # prefix end == flight start
SEAM_LL = SEAM[0][:2]                   # == THRESH
SEAM_FERRY = V7.camera_state(14.5)      # drive v2 end == ferry esp first kf


# ---------------- routes ----------------
def _load_forced(path, start, end):
    """OSRM [[lon,lat],...] with endpoints forced to exact anchors."""
    pts = [(p[1], p[0]) for p in json.load(open(path))]
    if math.dist(ll2ecef(*pts[0], 0), ll2ecef(*start, 0)) > 25.0:
        pts.insert(0, start)
    else:
        pts[0] = start
    if math.dist(ll2ecef(*pts[-1], 0), ll2ecef(*end, 0)) > 25.0:
        pts.append(end)
    else:
        pts[-1] = end
    return Route(pts)


SZ = _load_forced("route_SZ_raw.json", STATION, PORT)
# HK2 end = the T1 kerb the OSRM route already ends on (the snap IS the
# kerb on 暂航路 Cheong Hong Road); force it to the exact raw endpoint
_kerb_raw = json.load(open("route_HK2_raw.json"))
KERB = (_kerb_raw[-1][1], _kerb_raw[-1][0])
HK2 = _load_forced("route_HK2_raw.json", PORT_HK, KERB)
S_SZ, S_HK2 = SZ.s_total, HK2.s_total

# ---------------- camera altitude (t, ln H, d lnH/dt) ----------------
PREFIX_H = [
    (0.00, math.log(16000.0), 0.00),
    (0.45, math.log(15500.0), -0.10),
    (1.25, math.log(26000.0), 0.65),
    (2.20, math.log(33000.0), 0.22),
    (3.10, math.log(35500.0), 0.06),
    (3.80, math.log(33000.0), -0.28),
    (4.15, math.log(26000.0), -0.72),
    (4.70, math.log(16500.0), -1.00),
    (5.10, math.log(15000.0), 0.00),      # SZ port arrival
    (6.30, math.log(14500.0), -0.035),    # walk 1 (gentle 15.0->14.5km)
    (6.80, math.log(16800.0), 0.42),      # HK launch
    (7.70, math.log(31000.0), 0.92),
    (8.80, math.log(42000.0), 0.24),
    (9.70, math.log(44000.0), 0.04),
    (10.40, math.log(39000.0), -0.45),
    (10.85, math.log(28000.0), -1.30),
    (11.15, math.log(20000.0), -0.75),
    (11.30, math.log(19000.0), -0.15),    # T1 kerb arrival
    (12.00, math.log(15500.0), -0.50),    # walk 2 dive
    (12.80, math.log(13000.0), 0.00),     # threshold reached
    (13.30, math.log(13000.0), 0.00),     # SEAM == flight H(0)
]
h_at_t = lambda t: math.exp(hermite(PREFIX_H, t))


# ---- car schedules: launch -> envelope COEF*H -> hand-set decel ----
def _env(t0, t1, s0, v_first, coef, dt=0.08):
    out = []
    tt, s = t0, s0
    while tt < t1 - 1e-9:
        tt2 = min(tt + dt, t1)
        v1 = coef * h_at_t(tt)
        v2 = coef * h_at_t(tt2)
        if tt == t0:
            v1 = v_first
        s += 0.5 * (v1 + v2) * (tt2 - tt)
        out.append((round(tt2, 3), round(s, 1), round(v2, 1)))
        tt = tt2
    return out, s, coef * h_at_t(t1)


def _int_h(t0, t1, h=0.02):
    tot, tt = 0.0, t0
    while tt < t1 - 1e-9:
        tot += 0.5 * (h_at_t(tt) + h_at_t(min(tt + h, t1))) * min(h, t1 - tt)
        tt = round(tt + h, 4)
    return tot


# SZ: identical to v15 (H schedule unchanged on [0, 5.10])
SZ_LAUNCH_S, SZ_G1, SZ_REM = 170.0, 1100.0, 520.0
COEF_SZ = (S_SZ - SZ_LAUNCH_S - SZ_G1 - SZ_REM) / _int_h(0.90, 4.45)
CAR_SZ_CKPT = [(0.00, 0.0, 0.0), (0.90, SZ_LAUNCH_S, 400.0)]
_env_sz, _s_sz, _v_sz = _env(0.90, 4.45, SZ_LAUNCH_S, 400.0, COEF_SZ)
CAR_SZ_CKPT += _env_sz
CAR_SZ_CKPT += [(4.75, round(_s_sz + SZ_G1, 1), 2400.0),
                (5.10, S_SZ, 0.0)]

# HK2: launch [6.30, 6.80] -> envelope [6.80, 10.40] -> decel -> kerb 11.30
HK_LAUNCH_S, HK_G1, HK_REM = 180.0, 1900.0, 1330.0
COEF_HK = (S_HK2 - HK_LAUNCH_S - HK_G1 - HK_REM) / _int_h(6.80, 10.40)
CAR_HK2_CKPT = [(6.30, 0.0, 0.0), (6.80, HK_LAUNCH_S, 420.0)]
_env_hk, _s_hk, _v_hk = _env(6.80, 10.40, HK_LAUNCH_S, 420.0, COEF_HK)
CAR_HK2_CKPT += _env_hk
CAR_HK2_CKPT += [(10.70, round(_s_hk + HK_G1, 1), 3100.0),
                 (11.30, S_HK2, 0.0)]                 # parked at the kerb

sz_s = lambda t: hermite(CAR_SZ_CKPT, t)
hk2_s = lambda t: hermite(CAR_HK2_CKPT, t)


def _inv(ckpt, s, t0, t1):
    for _ in range(60):
        tm = (t0 + t1) / 2.0
        if hermite(ckpt, tm) < s:
            t0 = tm
        else:
            t1 = tm
    return (t0 + t1) / 2.0


sz_t_at_s = lambda s: _inv(CAR_SZ_CKPT, s, 0.00, 5.10)
hk2_t_at_s = lambda s: _inv(CAR_HK2_CKPT, s, 6.30, 11.30)


# ---------------- walks (plateau hermite) ----------------
def _walk_ckpt(t0, t1, length, tau=0.3):
    """(t, s, v) with smootherstep ramps tau each side, cruise between:
    ramp distance = vc*tau/2, total = vc*(T-tau)  =>  vc = L/(T-tau)."""
    vc = length / (t1 - t0 - tau)
    dr = vc * tau * 0.5
    return [(t0, 0.0, 0.0), (t0 + tau, dr, vc),
            (t1 - tau, length - dr, vc), (t1, length, 0.0)]


def _chord(lat0, lon0, lat1, lon1):
    ea, eb = ll2ecef(lat0, lon0, 0), ll2ecef(lat1, lon1, 0)
    L = math.dist(ea, eb)
    tan = unit(sub(eb, ea))
    return ea, eb, L, tan


def _walk_state(ckpt, ea, eb, L, t):
    """(lat, lon, unit tangent) at walk arc length s=hermite(ckpt, t);
    positions are a straight ECEF chord (walks are 0.2-4.0km)."""
    u = min(1.0, max(0.0, hermite(ckpt, t) / L))
    p = tuple(ea[k] + (eb[k] - ea[k]) * u for k in range(3))
    r = math.sqrt(sum(c * c for c in p))
    return (math.degrees(math.asin(p[2] / r)),
            math.degrees(math.atan2(p[1], p[0])), None)


_W1 = _chord(PORT[0], PORT[1], PORT_HK[0], PORT_HK[1])
_W2 = _chord(KERB[0], KERB[1], SEAM_LL[0], SEAM_LL[1])
_W3 = _chord(V5_END[0], V5_END[1], DRIVE_START[0], DRIVE_START[1])
WALK1_CKPT = _walk_ckpt(5.10, 6.30, _W1[2])
WALK2_CKPT = _walk_ckpt(11.30, 12.80, _W2[2])
WALK3_T = 1.5
WALK3_CKPT = _walk_ckpt(0.0, WALK3_T, _W3[2])
WALKS = [[5.1, 6.3], [11.3, 12.8], [23.3, 24.8]]     # rt windows (dashed)


def prefix_vehicle(t):
    """(lat, lon, alt, tan, kind) -- current vehicle during the prefix."""
    if t < 5.10:
        lat, lon, tan = SZ.at(sz_s(t))
        return lat, lon, 0.0, tan, "car_sz"
    if t < 6.30:
        lat, lon, _ = _walk_state(WALK1_CKPT, _W1[0], _W1[1], _W1[2], t)
        return lat, lon, 0.0, _W1[3], "walk"
    if t < 11.30:
        lat, lon, tan = HK2.at(hk2_s(t))
        return lat, lon, 0.0, tan, "car_hk"
    lat, lon, _ = _walk_state(WALK2_CKPT, _W2[0], _W2[1], _W2[2],
                              min(t, 12.80))
    return lat, lon, 0.0, _W2[3], "walk"


def prefix_camera_state(t):
    if t >= T2 - 1e-9:                 # seam: flight start, bit-exact
        return SEAM
    clat, clon = prefix_vehicle(t)[:2]
    h = h_at_t(t)
    tlat, tlon = dest(clat, clon, 0.0, 0.007 * h)     # target NORTH
    return (clat, clon, h), (tlat, tlon, 0.0)


# ---------------- walk 3 (CEB) + drive v2 (local timelines) ----------------
WALK3_H = [(0.00, math.log(13500.0), -0.01),
           (1.50, math.log(13000.0), -0.05)]


def _nadir(lat, lon, h):
    tlat, tlon = dest(lat, lon, 0.0, 0.007 * h)
    return (lat, lon, h), (tlat, tlon, 0.0)


# walk3 end state = drive v2 first kf, verbatim
WALK3_END = _nadir(DRIVE_START[0], DRIVE_START[1], 13000.0)


def walk3_state(t):
    if t <= 1e-9:                      # seam: frozen flight end, bit-exact
        return F5.camera_state(10.0)
    if t >= WALK3_T - 1e-9:
        return WALK3_END
    lat, lon, _ = _walk_state(WALK3_CKPT, _W3[0], _W3[1], _W3[2], t)
    return _nadir(lat, lon, math.exp(hermite(WALK3_H, t)))


def walk3_vehicle(t):
    lat, lon, _ = _walk_state(WALK3_CKPT, _W3[0], _W3[1], _W3[2],
                              min(t, WALK3_T))
    return lat, lon, 0.0, _W3[3], "walk"


DRIVE2_T = 4.10
# old V6 CAR_CKPT minus the plane-park settle, tangents nudged so every
# interval mean lies inside the anchor tangent range (no-bulge precondition)
CAR2_CKPT = [
    (0.00, 0.0, 0.0),
    (0.35, 300.0, 950.0),
    (0.85, 2000.0, 3500.0),
    (1.75, 6400.0, 5000.0),
    (2.55, 10100.0, 3800.0),
    (3.15, 12700.0, 4400.0),
    (3.60, 13600.0, 900.0),
    (3.83, S_CAR - 40.0, 300.0),
    (4.10, S_CAR, 0.0),                # parked at Pier 1
]
DRIVE_H2 = [
    (0.00, math.log(13000.0), -0.05),
    (0.65, math.log(23000.0), 0.95),
    (1.75, math.log(30000.0), 0.05),
    (2.95, math.log(24000.0), -0.40),
    (3.60, math.log(12000.0), -1.40),
    (3.95, math.log(6100.0), -2.40),
    (4.10, math.log(5800.0), 0.00),    # == ferry esp first H
]
car2_s = lambda t: hermite(CAR2_CKPT, t)
car2_t_at_s = lambda s: _inv(CAR2_CKPT, s, 0.0, DRIVE2_T)


def drive2_state(t):
    if t <= 1e-9:                      # seam: walk3 end, bit-exact
        return WALK3_END
    if t >= DRIVE2_T - 1e-9:           # seam: ferry esp first kf, bit-exact
        return SEAM_FERRY
    lat, lon, _ = DRIVE.at(car2_s(t))
    return _nadir(lat, lon, math.exp(hermite(DRIVE_H2, t)))


def drive2_vehicle(t):
    lat, lon, tan = DRIVE.at(car2_s(t))
    return lat, lon, 0.0, tan, "car"


def _seam_diff(esp_prev, prev_last, esp_new, new_first):
    """max |kf value diff| across the 6 boundary attrs."""
    a = json.load(open(esp_prev))
    b = json.load(open(esp_new))
    grp = lambda p: p["scenes"][0]["attributes"][0]
    worst = 0.0
    for path, attrs in ((("cameraPositionGroup", "position"),
                         ("longitude", "latitude", "altitude")),
                        (("cameraTargetEffect", "poi"),
                         ("longitudePOI", "latitudePOI", "altitudePOI"))):
        ha = find_attr(find_attr(grp(a), path[0]), path[1])
        hb = find_attr(find_attr(grp(b), path[0]), path[1])
        for at in attrs:
            ka = find_attr(ha, at)["keyframes"][prev_last]
            kb = find_attr(hb, at)["keyframes"][new_first]
            worst = max(worst, abs(ka["value"] - kb["value"]))
    return worst


def _build_esp(name, out, dur, T, state_fn):
    cam = {"lon": [], "lat": [], "alt": []}
    tgt = {"lon": [], "lat": [], "alt": []}
    samples = []
    t = 0.0
    while t <= T + 1e-9:
        c, g = state_fn(round(t, 4))
        tt = t / T
        cam["lon"].append(kf(tt, lon_to_value(c[1])))
        cam["lat"].append(kf(tt, lat_to_value(c[0])))
        cam["alt"].append(kf(tt, alt_to_value(c[2])))
        tgt["lon"].append(kf(tt, lon_to_value(g[1])))
        tgt["lat"].append(kf(tt, lat_to_value(g[0])))
        tgt["alt"].append(kf(tt, alt_to_value(g[2])))
        samples.append({"t": round(t, 3), "cam": c, "tgt": g})
        t = round(t + STEP, 3)
    build_esp("HKG to CEB Flight.esp", out, name, dur, cam, tgt)
    return samples


def _walk_route(ckpt, ea, eb, L, t0, t1, shift, skip_first=True):
    """route vertices every 0.1s along a walk (rt = video time)."""
    out = []
    t = t0 + (STEP if skip_first else 0.0)
    while t <= t1 + 1e-9:
        lat, lon, _ = _walk_state(ckpt, ea, eb, L, round(t, 4))
        out.append([lat, lon, 0.0, round(t + shift, 4)])
        t = round(t + STEP, 3)
    return out


if __name__ == "__main__":
    ok = True

    # ---- 1. the three new esps ----
    samples_prefix = _build_esp("Trip30 Seg0 SZHK v2", "trip30_seg0_szhk_v2.esp",
                                int(round(T2 * FPS)), T2, prefix_camera_state)
    print("seg0v2: t=[0,%.1f] dur=%d kfs=%d"
          % (T2, int(round(T2 * FPS)), len(samples_prefix)))
    samples_w3 = _build_esp("Trip30 Seg1 CEB Walk", "trip30_seg1_cebwalk.esp",
                            int(round(WALK3_T * FPS)), WALK3_T, walk3_state)
    print("walk3:   t=[0,%.1f] dur=%d kfs=%d"
          % (WALK3_T, int(round(WALK3_T * FPS)), len(samples_w3)))
    samples_d2 = _build_esp("Trip30 Seg2 Drive v2", "trip30_seg2_drivev2.esp",
                            int(round(DRIVE2_T * FPS)), DRIVE2_T, drive2_state)
    print("drive2:  t=[0,%.2f] dur=%d kfs=%d"
          % (DRIVE2_T, int(round(DRIVE2_T * FPS)), len(samples_d2)))

    print("\nbit-exact seams (max kf value diff, must be 0):")
    for a, ia, b, ib, what in (
            ("topdown10v5.esp", 0, "trip30_seg0_szhk_v2.esp", -1,
             "prefix_last vs flight_first"),
            ("topdown10v5.esp", -1, "trip30_seg1_cebwalk.esp", 0,
             "walk3_first vs flight_last"),
            ("trip30_seg1_cebwalk.esp", -1, "trip30_seg2_drivev2.esp", 0,
             "drive2_first vs walk3_last"),
            ("trip24_seg3_ferry.esp", 0, "trip30_seg2_drivev2.esp", -1,
             "drive2_last vs ferry_first")):
        d = _seam_diff(a, ia, b, ib)
        print("  %-28s %.3g" % (what, d))
        assert d < 1e-12, "SEAM MISMATCH: " + what
        ok &= d < 1e-12
    assert prefix_camera_state(T2) == SEAM
    assert drive2_state(DRIVE2_T) == SEAM_FERRY
    assert walk3_state(0.0) == F5.camera_state(10.0)

    # ---- 2. flight_data30.json ----
    prev = json.load(open("flight_data28.json"))

    # route: SZ + walk1 + HK2 + walk2 + flight(+1.8) + walk3 + drive2
    #        + boat/moto(+2.9).  Old drive rt (21.5,26] is REPLACED by
    #        walk3 + drive2.  First vertex of each appended piece that
    #        duplicates the previous piece's endpoint is skipped.
    route = []
    for i, (lat, lon) in enumerate(SZ.pts):
        route.append([lat, lon, 0.0, round(sz_t_at_s(SZ.cum[i]), 4)])
    route += _walk_route(WALK1_CKPT, _W1[0], _W1[1], _W1[2], 5.10, 6.30, 0.0)
    for i, (lat, lon) in enumerate(HK2.pts):
        if i == 0:
            continue
        route.append([lat, lon, 0.0, round(hk2_t_at_s(HK2.cum[i]), 4)])
    route += _walk_route(WALK2_CKPT, _W2[0], _W2[1], _W2[2], 11.30, 12.80, 0.0)
    route += [[p[0], p[1], p[2], round(p[3] + 1.8, 4)] for p in prev["route"]
              if 11.5 - 1e-6 <= p[3] <= 21.5 + 1e-6]
    route += _walk_route(WALK3_CKPT, _W3[0], _W3[1], _W3[2],
                         0.0, WALK3_T, 23.3)
    for i, (lat, lon) in enumerate(DRIVE.pts):
        if i == 0:
            continue
        route.append([lat, lon, 0.0, round(24.8 + car2_t_at_s(DRIVE.cum[i]), 4)])
    route += [[p[0], p[1], p[2], round(p[3] + 2.9, 4)] for p in prev["route"]
              if 26.0 + 1e-6 < p[3] <= 35.5 + 1e-6]

    # samples: prefix + flight(+1.8) + walk3 + drive2 + boat/moto/seg5(+2.9)
    samples = [dict(s) for s in samples_prefix]
    samples += [{"t": round(s["t"] + 1.8, 3), "cam": s["cam"], "tgt": s["tgt"]}
                for s in prev["samples"] if 11.6 - 1e-6 <= s["t"] <= 21.5 + 1e-6]
    samples += [{"t": round(s["t"] + 23.3, 3), "cam": s["cam"], "tgt": s["tgt"]}
                for s in samples_w3[1:]]          # local 0 == flight end
    samples += [{"t": round(s["t"] + 24.8, 3), "cam": s["cam"], "tgt": s["tgt"]}
                for s in samples_d2[1:]]          # local 0 == walk3 end
    samples += [{"t": round(s["t"] + 2.9, 3), "cam": s["cam"], "tgt": s["tgt"]}
                for s in prev["samples"]
                if 26.1 - 1e-6 <= s["t"] <= 37.5 + 1e-6]

    # frames: prefix 400 + flight 300 + walk3 45 + drive2 123 + old 345
    # (old 345 = boat/moto 285 + moto-hold tail 60, see the v17 remap below)
    frames = []
    for i in range(int(round(T2 * FPS)) + 1):
        t = i / FPS
        lat, lon, alt, tan, kind = prefix_vehicle(t)
        frames.append({"t": round(t, 4), "lat": lat, "lon": lon, "alt": alt,
                       "tan": [round(c, 6) for c in tan], "kind": kind})
    frames += [{"t": round(f["t"] + 1.8, 4), "lat": f["lat"], "lon": f["lon"],
                "alt": f["alt"], "tan": f["tan"], "kind": f["kind"]}
               for f in prev["frames"] if 11.5 + 1e-6 < f["t"] <= 21.5 + 1e-6]
    for i in range(1, int(round(WALK3_T * FPS)) + 1):
        t = i / FPS
        lat, lon, alt, tan, kind = walk3_vehicle(t)
        frames.append({"t": round(t + 23.3, 4), "lat": lat, "lon": lon,
                       "alt": alt, "tan": [round(c, 6) for c in tan],
                       "kind": kind})
    for i in range(1, int(round(DRIVE2_T * FPS)) + 1):
        t = i / FPS
        lat, lon, alt, tan, kind = drive2_vehicle(t)
        frames.append({"t": round(t + 24.8, 4), "lat": lat, "lon": lon,
                       "alt": alt, "tan": [round(c, 6) for c in tan],
                       "kind": kind})
    frames += [{"t": round(f["t"] + 2.9, 4), "lat": f["lat"], "lon": f["lon"],
                "alt": f["alt"], "tan": f["tan"], "kind": f["kind"]}
               for f in prev["frames"] if 26.0 + 1e-6 < f["t"] <= 37.5 + 1e-6]

    # v17 (user: U Story 结尾不出现汽车): the moto is the FINAL leg -- the old
    # tail's "resort car" frames become the moto holding at its arrival
    # anchor through the zoom-out, so the journey ends with the vehicle that
    # actually brought us there.
    moto_last = next(f for f in reversed(frames) if f["kind"] == "moto")
    frames = [f if not (f["kind"] == "car" and f["t"] > moto_last["t"] + 1e-6)
              else {"t": f["t"], "lat": moto_last["lat"],
                    "lon": moto_last["lon"], "alt": moto_last["alt"],
                    "tan": moto_last["tan"], "kind": "moto"}
              for f in frames]

    meta = dict(prev)
    meta.update({
        "total": 40.4, "fps": FPS, "step": STEP,
        "station": list(STATION), "port": list(PORT),
        "port_hk": list(PORT_HK), "kerb": list(KERB),
        "thresh": list(SEAM_LL), "drive_start": list(DRIVE_START),
        "s_car_sz": S_SZ, "s_car_hk": S_HK2,
        "walks": WALKS,
        "route": route, "samples": samples, "frames": frames,
        "emoji": {"plane": -44.18, "car_sz": 180.0, "car_hk": 180.0,
                  "car": 180.0, "boat": 180.0, "moto": 180.0},
    })
    with open("flight_data30.json", "w") as f:
        json.dump(meta, f)
    print("\nflight_data30.json: %d samples %d frames %d route pts"
          % (len(samples), len(frames), len(route)))
    assert len(frames) == DUR + 1, "frame count %d != %d" % (len(frames), DUR + 1)
    assert abs(frames[-1]["t"] - 40.4) < 1e-6
    # frame timeline must be strictly increasing 1/30 steps
    for i in range(1, len(frames)):
        dt = frames[i]["t"] - frames[i - 1]["t"]
        assert 0.03 < dt < 0.0345, "frame gap %.4f at %d" % (dt, i)
    ok &= True

    # ---- 3. reports ----
    print("\nwalks: w1 %.0fm  w2 %.0fm  w3 %.0fm"
          % (_W1[2], _W2[2], _W3[2]))
    print("COEF_SZ=%.5f (%.0f px/s)  COEF_HK=%.5f (%.0f px/s)"
          % (COEF_SZ, COEF_SZ * 3062.9, COEF_HK, COEF_HK * 3062.9))
    print("S_SZ=%.0f m (%d pts) | S_HK2=%.0f m (%d pts) | S_CAR=%.0f m"
          % (S_SZ, len(SZ.pts), S_HK2, len(HK2.pts), S_CAR))

    print("\ninterval-mean audit (Hermite no-bulge precondition):")
    for name, ck in (("car_sz", CAR_SZ_CKPT), ("car_hk2", CAR_HK2_CKPT),
                     ("walk1", WALK1_CKPT), ("walk2", WALK2_CKPT),
                     ("walk3", WALK3_CKPT), ("car2", CAR2_CKPT)):
        nbad = 0
        for (ta, sa, va), (tb, sb, vb) in zip(ck, ck[1:]):
            mean = (sb - sa) / (tb - ta)
            tol = 0.1 / (tb - ta) + 0.06
            if not (min(va, vb) - tol <= mean <= max(va, vb) + tol):
                nbad += 1
                print("  %s VIOLATION %.2f->%.2f mean %.1f tangents %.1f..%.1f"
                      % (name, ta, tb, mean, va, vb))
        print("  %-7s %2d intervals, %s" % (name, len(ck) - 1,
                                            "OK" if nbad == 0 else "%d bad" % nbad))
        ok &= nbad == 0
    for name, ck in (("lnH_prefix", PREFIX_H), ("lnH_drive2", DRIVE_H2),
                     ("lnH_walk3", WALK3_H)):
        nbad = 0
        for (ta, ha, va), (tb, hb, vb) in zip(ck, ck[1:]):
            mean = (hb - ha) / (tb - ta)
            if not (min(va, vb) - 1e-6 <= mean <= max(va, vb) + 1e-6):
                nbad += 1
                print("  %s VIOLATION %.2f->%.2f mean %+.3f tangents %+.2f..%+.2f"
                      % (name, ta, tb, mean, va, vb))
        print("  %-9s %2d intervals, %s" % (name, len(ck) - 1,
                                            "OK" if nbad == 0 else "%d bad" % nbad))
        ok &= nbad == 0

    print("\ngrid monotonicity (0.01s):")
    for name, ck in (("car_sz", CAR_SZ_CKPT), ("car_hk2", CAR_HK2_CKPT),
                     ("walk1", WALK1_CKPT), ("walk2", WALK2_CKPT),
                     ("walk3", WALK3_CKPT), ("car2", CAR2_CKPT)):
        bad, prevv = 0, hermite(ck, ck[0][0])
        tt = ck[0][0]
        while tt <= ck[-1][0] + 1e-9:
            v = hermite(ck, round(tt, 4))
            if v < prevv - 1e-6 or v < -1e-6:
                bad += 1
            prevv = v
            tt = round(tt + 0.01, 4)
        print("  %-7s %s" % (name, "OK" if bad == 0 else "%d violations" % bad))
        ok &= bad == 0

    print("\nkey positions (prefix):")
    for t in (0.0, 1.5, 4.5, 5.1, 5.6, 6.3, 7.0, 8.5, 10.0, 11.0, 11.3,
              12.0, 12.8, 13.3):
        lat, lon, alt, tan, kind = prefix_vehicle(t)
        t2 = min(t + 0.05, T2)
        lat2, lon2, _, _, _ = prefix_vehicle(t2)
        v = math.dist(ll2ecef(lat, lon, 0), ll2ecef(lat2, lon2, 0)) \
            / max(t2 - t, 1e-9)
        print("  t=%5.2f %-6s (%7.4f,%8.4f) v=%7.0f H=%9.0f px/s=%5.0f"
              % (t, kind, lat, lon, v, h_at_t(t), v * 3062.9 / h_at_t(t)))

    print("\nmax screen speed + zoom per phase (30fps):")
    phases = (("sz", 0.0, 5.1, prefix_vehicle, h_at_t),
              ("walk1", 5.1, 6.3, prefix_vehicle, h_at_t),
              ("hk2", 6.3, 11.3, prefix_vehicle, h_at_t),
              ("walk2", 11.3, 12.8, prefix_vehicle, h_at_t),
              ("walk3", 0.0, 1.5, walk3_vehicle,
               lambda t: math.exp(hermite(WALK3_H, t))),
              ("drive2", 0.0, 4.1, drive2_vehicle,
               lambda t: math.exp(hermite(DRIVE_H2, t))))
    for name, t0, t1, veh, hh in phases:
        mx, mt, zm_worst, zm_t = 0, 0, 1.0, 0
        i = math.ceil(t0 * FPS)
        while i / FPS < t1 - 1e-9:
            t = i / FPS
            la1, lo1, _, _, _ = veh(t)
            la2, lo2, _, _, _ = veh(t + 1 / FPS)
            v = math.dist(ll2ecef(la1, lo1, 0), ll2ecef(la2, lo2, 0)) * FPS
            px = v * 3062.9 / hh(t + 1 / 60)
            if px > mx:
                mx, mt = px, t
            r = hh(t + 1 / FPS) / hh(t)
            if abs(math.log(r)) > abs(math.log(zm_worst)):
                zm_worst, zm_t = r, t
            i += 1
        print("  %-6s max %5.0f px/s at t=%.2f | zoom worst x%.3f at t=%.2f"
              % (name, mx, mt, zm_worst, zm_t))
        ok &= mx <= 864 and 0.87 <= zm_worst <= 1.13

    print("\npanel-verification tables (for siq_scrub checks):")
    print("  seg0v2 (Trip30 Seg0 SZHK v2):")
    for f in (1, 91, 154, 190, 251, 310, 341, 361, 385, 400):
        t = round((f - 1) / 30.0, 4)
        c, g = prefix_camera_state(t)
        print("    f%-3d t=%6.3f  lon %.5f  lat %.5f  alt %.0f m"
              % (f, t, c[1], c[0], c[2]))
    print("  walk3 (Trip30 Seg1 CEB Walk):")
    for f in (1, 16, 31, 46):
        t = round((f - 1) / 30.0, 4)
        c, g = walk3_state(t)
        print("    f%-3d t=%6.3f  lon %.5f  lat %.5f  alt %.0f m"
              % (f, t, c[1], c[0], c[2]))
    print("  drive2 (Trip30 Seg2 Drive v2):")
    for f in (1, 16, 31, 62, 93, 124):
        t = round((f - 1) / 30.0, 4)
        c, g = drive2_state(t)
        print("    f%-3d t=%6.3f  lon %.5f  lat %.5f  alt %.0f m"
              % (f, t, c[1], c[0], c[2]))

    print("\nwalk windows vs route rt coverage:")
    rts = [p[3] for p in route]
    for w0, w1 in WALKS:
        n = len([r for r in rts if w0 - 1e-6 <= r <= w1 + 1e-6])
        print("  [%.1f, %.1f] %d route verts" % (w0, w1, n))
        ok &= n >= 10

    print("\nRESULT: %s" % ("ALL GREEN" if ok else "FAILED"))
