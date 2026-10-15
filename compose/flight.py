#!/usr/bin/env python3
"""Flight + chase-camera design for HKG->CEB third-person animation.

Outputs:
  chase.esp        - Earth Studio project (import via file menu)
  flight_data.json - plane track samples + camera keyframes (for compositing)

Design (90s total, 30fps, 2700 frames):
  t=0-3.5  hold on runway at HKG (low, detailed)
  t=3.5-10 takeoff roll
  t=10-26  climb 25m -> 11km; from t=14 camera swoops up (speed ramps too)
  t=26-52  cruise at 11km, HIGH oblique map view (~320km up, 600km behind):
           earth curvature + horizon + route arc visible, smooth ground flow
  t=52-64  dive back down (speed ramps down simultaneously)
  t=64-78  descent 11km -> 250m, chase cam
  t=78-86  approach + flare + touchdown ~86s
  t=86-88  rollout decel
  t=88-90  hold at CEB
Speed profile: piecewise smoothstep on (t, v) segments in km/s *shape* units,
scaled so total great-circle distance = 1711km.  Camera chase offsets
(behind/above/ahead) smoothstep-interpolated from CHASE table; sized so
ground-flow angular speed v/range stays ~0.05-0.3 rad/s (readable) except
brief energetic moments at rotation and swoop start.
Camera: chase cam behind+above the plane, looking ahead of it via ES camera
target with influence 100% (plane is always screen-center, drawn in
compositing at the per-frame POI).
"""
import json
import math

# ---------------- geo math ----------------
R = 6371000.0  # earth radius m

HKG = (22.3080, 113.9185)
CEB = (10.3075, 123.9790)

def ll2ecef(lat, lon, alt):
    la, lo = math.radians(lat), math.radians(lon)
    return (math.cos(la) * math.cos(lo) * (R + alt),
            math.cos(la) * math.sin(lo) * (R + alt),
            math.sin(la) * (R + alt))

def ecef2ll(x, y, z):
    r = math.sqrt(x * x + y * y + z * z)
    lat = math.degrees(math.asin(z / r))
    lon = math.degrees(math.atan2(y, x))
    return lat, lon, r - R

def unit(v):
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)

def sub(a, b):
    return tuple(x - y for x, y in zip(a, b))

def add(a, b):
    return tuple(x + y for x, y in zip(a, b))

def scale(v, s):
    return tuple(c * s for c in v)

def dot(a, b):
    return sum(x * y for x, y in zip(a, b))

P0 = unit(ll2ecef(*HKG, 0.0)[:3])  # surface unit vectors
P1 = unit(ll2ecef(*CEB, 0.0)[:3])
OMEGA = math.acos(max(-1.0, min(1.0, dot(P0, P1))))
TOTAL_DIST = OMEGA * R  # great-circle distance (m)

def gc_point(f):
    """Great circle point at fraction f (0=HKG, 1=CEB): (lat, lon, ecef_unit, tangent_dir)."""
    f = max(0.0, min(1.0, f))
    # slerp: p(f) = P0*sin((1-f)W)/sinW + P1*sin(fW)/sinW
    p = add(scale(P0, math.sin((1 - f) * OMEGA) / math.sin(OMEGA)),
            scale(P1, math.sin(f * OMEGA) / math.sin(OMEGA)))
    p = unit(p)
    # tangent dp/df = P0*(-W*cos((1-f)W)/sinW) + P1*(W*cos(fW)/sinW)
    t = add(scale(P0, -OMEGA * math.cos((1 - f) * OMEGA) / math.sin(OMEGA)),
            scale(P1, OMEGA * math.cos(f * OMEGA) / math.sin(OMEGA)))
    t = unit(t)
    lat = math.degrees(math.asin(p[2]))
    lon = math.degrees(math.atan2(p[1], p[0]))
    return lat, lon, p, t

# ---------------- profiles ----------------
def smooth(x):
    """smoothstep 0..1"""
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)

def seg(t, t0, t1):
    return 0.0 if t <= t0 else (1.0 if t >= t1 else smooth((t - t0) / (t1 - t0)))

# ---- horizontal progress via speed-profile integration ----
# (t0, t1, v0, v1) segments in km/s SHAPE units; smoothstep within, constant
# outside.  All speeds are later scaled so the integral = total distance.
_SPEED_SEGS = [
    (0.0, 3.5, 0.0, 0.0),        # hold at HKG
    (3.5, 5.5, 0.0, 0.75),       # spin-up
    (5.5, 8.0, 0.75, 0.75),      # roll plateau
    (8.0, 10.0, 0.75, 6.0),      # rotate -> climb speed
    (10.0, 14.0, 6.0, 6.0),      # climb plateau
    (14.0, 26.0, 6.0, 38.0),     # accelerate while camera swoops up
    (26.0, 52.0, 38.0, 38.0),    # cruise
    (52.0, 64.0, 38.0, 6.0),     # decelerate while camera dives
    (64.0, 74.0, 6.0, 6.0),      # descent plateau
    (74.0, 78.0, 6.0, 1.7),      # slow to approach speed
    (78.0, 83.5, 1.7, 1.7),      # approach
    (83.5, 86.0, 1.7, 0.35),     # flare + touchdown
    (86.0, 87.5, 0.35, 0.0),     # rollout decel
    (87.5, 90.0, 0.0, 0.0),      # hold at CEB
]

def _speed_shape(t):
    for t0, t1, v0, v1 in _SPEED_SEGS:
        if t0 <= t < t1:
            return v0 if v1 == v0 else v0 + (v1 - v0) * smooth((t - t0) / (t1 - t0))
    return _SPEED_SEGS[-1][3]

_PROG_DT = 0.02
_PROG_CACHE = [0.0]
for i in range(1, int(92.0 / _PROG_DT) + 1):  # cumulative trapezoid, km shape units
    t0, t1 = (i - 1) * _PROG_DT, i * _PROG_DT
    _PROG_CACHE.append(_PROG_CACHE[-1] + (_speed_shape(t0) + _speed_shape(t1)) / 2 * _PROG_DT)
_SPEED_SCALE = TOTAL_DIST / 1000.0 / _PROG_CACHE[int(90.0 / _PROG_DT)]  # shape km -> real km

def prog(t):
    """horizontal progress fraction 0..1 along route"""
    if t <= 0:
        return 0.0
    if t >= 90.0:
        return min(_PROG_CACHE[int(90.0 / _PROG_DT)] * _SPEED_SCALE / (TOTAL_DIST / 1000.0), 1.0)
    x = t / _PROG_DT
    i = int(x)
    p = _PROG_CACHE[i] + (_PROG_CACHE[i + 1] - _PROG_CACHE[i]) * (x - i)
    return min(p * _SPEED_SCALE / (TOTAL_DIST / 1000.0), 1.0)

def altitude(t):
    if t <= 3.5:
        return 15.0
    a = 15.0
    a += 10.0 * seg(t, 3.5, 10.0)      # roll: 15->25
    a += 10975.0 * seg(t, 10.0, 26.0)  # climb: -> 11000
    a -= 10750.0 * seg(t, 64.0, 78.0)  # descent: -> 250
    a -= 235.0 * seg(t, 78.0, 85.0)    # flare: -> 15
    a -= 15.0 * seg(t, 85.0, 86.5)     # settle: -> 0
    return max(0.0, a)

def plane_state(t):
    """plane position (lat, lon, alt) + horizontal track dir at time t"""
    f = prog(t)
    lat, lon, p, tan = gc_point(f)
    return lat, lon, altitude(t), p, tan

# ---------------- chase camera ----------------
def lerp(a, b, u):
    return a + (b - a) * u

CHASE = [  # (t, behind_m, above_m, ahead_m)
    (0.0,    700,     55,    450),   # runway hold: low + detailed
    (3.5,    700,     55,    450),
    (8.0,   1600,    150,    700),   # roll
    (10.0,   2600,    350,   1000),  # rotation
    (14.0,  16000,   6000,   6000),  # climb (pulled back for readability)
    (26.0, 600000, 320000, 180000),  # cruise: high oblique map view
    (52.0, 600000, 320000, 180000),
    (64.0,   40000,  15000,  12000),  # dive complete, chase for descent
    (74.0,   15000,   5000,   6000),
    (78.0,    8000,   2000,   3000),  # approach
    (83.5,    4000,    700,   1600),  # flare
    (86.0,    2500,    300,   1000),  # touchdown
    (88.0,     800,     60,    350),  # rollout -> parked
    (90.0,     800,     60,    350),
]

def chase_params(t):
    if t <= CHASE[0][0]:
        return CHASE[0][1:]
    for i in range(len(CHASE) - 1):
        t0, b0, a0, h0 = CHASE[i]
        t1, b1, a1, h1 = CHASE[i + 1]
        if t <= t1:
            u = smooth((t - t0) / (t1 - t0))
            return lerp(b0, b1, u), lerp(a0, a1, u), lerp(h0, h1, u)
    return CHASE[-1][1:]

def camera_state(t):
    lat, lon, alt, p, tan = plane_state(t)
    behind, above, ahead = chase_params(t)
    palt = max(alt, 1.0)
    pe = ll2ecef(lat, lon, palt)
    up = unit(pe)
    cam = add(sub(pe, scale(tan, behind)), scale(up, above))
    tgt = add(pe, scale(tan, ahead))
    clat, clon, calt = ecef2ll(*cam)
    tlat, tlon, talt = ecef2ll(*tgt)
    return (clat, clon, max(calt, 1.0)), (tlat, tlon, max(talt, 1.0))

# ---------------- esp generation ----------------
ALT_MIN, ALT_MAX = -500.0, 65117481.0

# calibrated (alt_m, value) pairs - UI readback + tracking self-calibration x2
CAL = [
    (-488.0, 0.355549),
    (-425.0, 0.406477),
    (-190.0, 0.441879),
    (-179.0, 0.443042),
    (-146.0, 0.445951),
    (-93.0, 0.450106),
    (1.0, 0.456097),
    (21.0, 0.457385),
    (32.0, 0.458029),
    (36.0, 0.458416),
    (48.2, 0.458864828162),
    (55.0, 0.459240120515),
    (56.6, 0.459330082347),
    (61.0, 0.45957112429),
    (61.3, 0.459584127096),
    (62.9, 0.45967047305),
    (70.1, 0.460064588114),
    (71.9, 0.460160760378),
    (73.6, 0.460252153676),
    (83.1, 0.46075240852),
    (89.0, 0.461064499808),
    (91.4, 0.461186266438),
    (96.2, 0.461439566884),
    (98.8, 0.461572765497),
    (106.7, 0.461976338825),
    (112.2, 0.462255207347),
    (126.2, 0.462948274245),
    (128.9, 0.463080841141),
    (139.4, 0.463594525403),
    (144.3, 0.46383125332),
    (145.0, 0.463863384433),
    (158.9, 0.464523384612),
    (161.4, 0.464642903296),
    (170.0, 0.465041050145),
    (175.0, 0.465270068212),
    (184.2, 0.465694180576),
    (209.5, 0.466820142052),
    (261.1, 0.469010107741),
    (264.1, 0.469133620574),
    (275.6, 0.469600148925),
    (305.6, 0.470791221323),
    (330.4, 0.471743832665),
    (344.8, 0.472284931121),
    (354.3, 0.472638189944),
    (376.8, 0.473455137689),
    (408.3, 0.474573358135),
    (460.1, 0.476330906363),
    (579.3, 0.480061267897),
    (587.8, 0.480310415077),
    (650.5, 0.482110890035),
    (670.8, 0.482672967152),
    (688.5, 0.48315470522),
    (746.5, 0.48469280829),
    (795.6, 0.485941023512),
    (861.8, 0.487559068942),
    (886.2, 0.48813764206),
    (899.5, 0.488446631052),
    (1056.8, 0.491929266077),
    (1236.4, 0.495522740627),
    (1387.1, 0.498278798764),
    (1423.3, 0.498911054072),
    (1442.5, 0.499242279892),
    (1616.3, 0.502102032135),
    (1623.4, 0.50221370822),
    (1825.6, 0.505268530865),
    (2001.7, 0.507733285398),
    (2140.9, 0.509569061825),
    (2232.5, 0.510728714031),
    (2265.6, 0.511138767332),
    (2429.5, 0.513104823463),
    (2442.1, 0.513252069679),
    (2532.2, 0.514284592073),
    (2787.6, 0.517065322456),
    (2884.6, 0.51806869543),
    (3556.9, 0.524363644058),
    (3681.7, 0.525424482663),
    (3813.8, 0.526514491786),
    (4053.3, 0.528414933309),
    (4360.3, 0.530718060412),
    (4971.6, 0.534926617074),
    (5185.7, 0.536297090773),
    (5219.6, 0.536509837529),
    (5346.2, 0.537293682552),
    (6070.2, 0.541491529185),
    (6174.2, 0.542059142829),
    (6592.8, 0.544261659925),
    (6636.7, 0.544485645584),
    (6819.4, 0.545403911565),
    (7149.8, 0.547011640748),
    (7401.8, 0.548195094906),
    (7760.8, 0.549821015779),
    (7851.7, 0.550222280586),
    (7947.2, 0.550639581623),
    (7958.6, 0.550689163032),
    (8685.4, 0.553723850087),
    (9068.7, 0.555235139907),
    (9350.8, 0.556311588227),
    (9553.4, 0.55706695664),
    (9760.2, 0.557823723073),
    (10169.6, 0.559280532638),
    (10545.4, 0.560572963859),
    (10615.6, 0.560809599715),
    (11032.4, 0.56218751359),
    (11595.8, 0.563977998434),
    (11617.0, 0.56404401246),
    (11640.6, 0.564117206096),
    (11797.6, 0.564600666415),
    (11834.9, 0.564714650524),
    (11936.2, 0.565022404864),
    (12817.6, 0.56760770349),
    (14064.6, 0.571004931926),
    (14820.3, 0.57293368968),
    (15345.7, 0.574223274343),
    (16635.3, 0.577226193598),
    (17912.6, 0.579999490319),
    (19157.7, 0.582535050824),
    (20351.0, 0.584828252826),
    (21473.4, 0.586876127276),
    (22490.9, 0.588649762133),
    (22506.3, 0.588676029219),
    (23431.0, 0.590224630829),
    (24229.2, 0.591517095078),
    (24882.6, 0.592546317464),
    (25372.6, 0.593302136693),
    (25680.6, 0.593770412953),
    (25787.6, 0.59393185193),
    (27250.8, 0.596080614501),
    (31420.7, 0.601669604918),
    (32174.8, 0.602606941366),
    (37922.8, 0.609152266249),
    (43438.1, 0.614623736025),
    (46369.5, 0.617275885145),
    (55923.2, 0.624957486055),
    (56398.0, 0.625306685999),
    (67684.7, 0.632896092874),
    (69332.6, 0.633904453607),
    (79945.9, 0.639911926988),
    (84371.5, 0.642200617146),
    (97250.0, 0.648277681874),
    (104180.4, 0.651244852004),
    (116157.0, 0.655964992685),
    (125218.8, 0.659244674237),
    (136212.0, 0.662939229796),
    (147155.8, 0.666351381198),
    (157109.3, 0.669255676606),
    (169655.1, 0.672681674727),
    (178535.1, 0.67496691332),
    (192376.0, 0.678326037251),
    (200169.2, 0.68011963557),
    (214974.0, 0.683354814263),
    (221685.9, 0.684753664925),
    (237100.6, 0.687822590487),
    (242755.0, 0.688901915302),
    (258404.3, 0.691771322203),
    (263042.7, 0.692590719657),
    (278531.0, 0.695232556746),
    (282211.8, 0.695840229963),
    (297124.6, 0.698228965373),
    (299923.2, 0.69866475063),
    (313828.0, 0.700775337088),
    (315836.2, 0.701072932803),
    (328283.9, 0.70287912124),
    (329610.2, 0.703067783232),
    (340136.3, 0.7045405575),
    (340905.0, 0.704646444582),
    (349031.4, 0.70575238562),
    (349383.0, 0.705799691114),
    (354619.8, 0.706499075299),
    (354710.1, 0.706511054864),
    (356557.7, 0.706755447347),
    (400000.0, 0.712186),
    (657000.0, 0.729412),
    (3137000.0, 0.806422),
    (10151000.0, 0.883463),
]

def alt_to_value(alt):
    """piecewise log-linear inverse mapping (calibrated)"""
    if alt <= CAL[0][0]:
        return CAL[0][1]
    for i in range(len(CAL) - 1):
        a0, v0 = CAL[i]
        a1, v1 = CAL[i + 1]
        if alt <= a1:
            if a0 <= 0 or a1 <= 0 or alt <= 0:
                return v0 + (v1 - v0) * (alt - a0) / (a1 - a0)
            la0, la1 = math.log(a0), math.log(a1)
            la = math.log(alt)
            u = (la - la0) / (la1 - la0)
            return v0 + (v1 - v0) * u
    return CAL[-1][1]

def value_to_alt(v):
    """inverse of alt_to_value (piecewise, matching CAL segments)"""
    if v <= CAL[0][1]:
        return CAL[0][0]
    for i in range(len(CAL) - 1):
        a0, v0 = CAL[i]
        a1, v1 = CAL[i + 1]
        if v <= v1:
            if a0 <= 0 or a1 <= 0:
                return a0 + (a1 - a0) * (v - v0) / (v1 - v0)
            la0, la1 = math.log(a0), math.log(a1)
            return math.exp(la0 + (la1 - la0) * (v - v0) / (v1 - v0))
    return CAL[-1][0]

def lon_to_value(lon):
    return (lon + 180.0) / 360.0

def lat_to_value(lat):
    return (lat + 90.0) / 180.0

def find_attr(node, atype):
    for a in node.get("attributes", []):
        if a.get("type") == atype:
            return a
        found = find_attr(a, atype)
        if found:
            return found
    return None

def kf(time, value):
    return {"time": round(time, 10), "value": value}

def build_esp(base_path, out_path, name, duration, cam_kfs, tgt_kfs):
    with open(base_path, encoding="utf-8") as f:
        proj = json.load(f)
    proj["settings"]["name"] = name
    proj["settings"]["duration"] = duration
    scene = proj["scenes"][0]
    scene["duration"] = duration
    proj["playbackManager"]["range"]["end"] = duration

    cam_group = scene["attributes"][0]
    pos_group = find_attr(cam_group, "cameraPositionGroup")
    position = find_attr(pos_group, "position")
    for atype, kfs in (("longitude", cam_kfs["lon"]), ("latitude", cam_kfs["lat"]),
                       ("altitude", cam_kfs["alt"])):
        a = find_attr(position, atype)
        a["keyframes"] = kfs
        a["value"]["relative"] = kfs[0]["value"]

    # camera target: enable with 100% influence, POI keyframes
    tgt = find_attr(cam_group, "cameraTargetEffect")
    poi = find_attr(tgt, "poi")
    for atype, kfs in (("longitudePOI", tgt_kfs["lon"]), ("latitudePOI", tgt_kfs["lat"]),
                       ("altitudePOI", tgt_kfs["alt"])):
        a = find_attr(poi, atype)
        a["keyframes"] = kfs
        if "value" in a and "relative" in a["value"]:
            a["value"]["relative"] = kfs[0]["value"]
    infl = find_attr(tgt, "influence")
    infl["keyframes"] = [kf(0.0, 1.0)]
    infl["value"]["relative"] = 1.0
    en = find_attr(tgt, "enabled")
    en["keyframes"] = [kf(0.0, 1.0)]
    en["keyframes"][0]["transitionIn"] = {"type": "step"}
    en["keyframes"][0]["transitionOut"] = {"type": "step"}

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(proj, f, ensure_ascii=False)

if __name__ == "__main__":
    TOTAL = 90.0
    FPS = 30
    DUR = int(TOTAL * FPS)  # 2700
    STEP = 0.5              # keyframe every 0.5s (smooth swoops)

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
        plat, plon, palt, _, _ = plane_state(t)
        samples.append({"t": round(t, 3), "lat": plat, "lon": plon, "alt": palt,
                        "cam": c, "tgt": g})
        t = round(t + STEP, 3)

    build_esp("HKG to CEB Flight.esp", "chase.esp", "HKG to CEB Chase", DUR, cam, tgt)

    # route samples for compositing (dense)
    route = []
    for i in range(401):
        lat, lon, _, _ = gc_point(i / 400.0)
        route.append([lat, lon])

    # per-frame data for compositing: ES interpolates keyframes LINEARLY
    # (verified via tracking export), so per-frame POI = chord interp of the
    # STEP samples: lon/lat linear in degrees, altitude linear in value space.
    # The plane is drawn AT the POI -> always screen-center (influence 100%).
    frames = []
    for i in range(DUR + 1):
        t = i / FPS
        k = min(int(t / STEP), len(samples) - 2)
        u = t / STEP - k
        s0, s1 = samples[k], samples[k + 1]
        g0, g1 = s0["tgt"], s1["tgt"]
        lat = g0[0] + (g1[0] - g0[0]) * u
        lon = g0[1] + (g1[1] - g0[1]) * u
        va0, va1 = alt_to_value(g0[2]), alt_to_value(g1[2])
        alt = value_to_alt(va0 + (va1 - va0) * u)
        frames.append({"t": round(t, 4), "lat": lat, "lon": lon, "alt": alt})

    meta = {
        "total": TOTAL, "fps": FPS, "frames": DUR,
        "hkg": HKG, "ceb": CEB, "distance_m": TOTAL_DIST,
        "plane_samples": samples, "route": route, "frames": frames,
    }
    with open("flight_data.json", "w") as f:
        json.dump(meta, f)

    print(f"route distance: {TOTAL_DIST/1000:.1f} km")
    print(f"speed scale: {_SPEED_SCALE:.4f} (cruise {_SPEED_SEGS[6][2]*_SPEED_SCALE:.1f} km/s)")
    print(f"wrote chase.esp ({DUR} frames, {len(samples)} keyframes) + "
          f"flight_data.json ({len(frames)} frames)")
