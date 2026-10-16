#!/usr/bin/env python3
"""V31 compositor: 清湖北站 -> 深圳湾口岸 (car_sz, blue) -> [walk] -> 香港机场
T1 出发层 (car_hk, yellow) -> [walk] -> HKG runway (fly) -> CEB (fly) ->
[walk] -> Cebu Pier 1 (drive) -> OceanJet ferry via Tagbilaran -> Siquijor
Pier -> U Story Resort (moto, final vehicle -- parks there through the
pull-back; no extra car at the resort) -> final pull-back overview.
Top-down north-up.  40.4s/1213 frames; all timing constants come from the
data file where possible.

Structure copied from compose10top.py (V5, user-approved).  V6 differences:
  - one continuous itinerary polyline (flight + drive + boat + moto); the
    done/ahead split uses each vertex's arrival time rt vs the frame time
  - emoji sprites switched per frame by frames[i]["kind"] (plane/car/boat/
    moto); per-kind nose angle from data["emoji"]; a missing sprite file
    falls back to emoji_car.png (placeholder until the real one arrives)
  - pier/resort labels with time windows and 0.3s linear fade in/out
    (airport labels unchanged from V5); v30: 清湖北站 origin label REMOVED
    (user: 起点的位置不用标记文字)
  - route vertices whose projection is <1px from the previous kept vertex are
    skipped when drawing (dense OSRM drive / densified ferry polylines)
  - normalize_route_rt(): repairs legacy route rt offsets (see docstring)

V10 vehicle rules (user request):
  - a finished leg's vehicle stays at its exact geographic anchor, projected
    every frame so it scales near-big/far-small with the map view.  No
    decluttering and no leader lines; overlap between vehicles is allowed and
    resolved purely by draw order: waiting ones first, then parked
    oldest-first, current vehicle last, so a newer vehicle covers an older.
  - sprite_scale() is INVERSELY PROPORTIONAL to camera altitude
    (13500m/alt, capped 1.0, floored 0.12) and every kind shares one
    150px base sprite, so all icons are the same size at the same
    altitude (v13 user rule; the v11/v12 power-law compromises read
    as screen decals because they were not proportional).

V30 walk transitions (user: 中间这段用虚线表示步行):
  - route segments whose mid-rt falls in a data["walks"] window are drawn
    DASHED (14px on / 10px off) instead of solid -- white-dashed when done,
    blue-dashed with a dark underlay when ahead; walk vertices are sampled
    every 0.1s so the dashes flip ahead->done as the line grows
  - v31 (user: 别画人了, 用一个动态的线从A连到B表示步行): NO walker sprite --
    the animated dashed line alone represents the walk; walk frames draw no
    current vehicle at all
  - WAITING vehicles (user: 第 n+1 段载具提前在起点等着, 而不是突然出现):
    every non-walk vehicle is drawn at its exact start anchor from t=0
    until its leg begins, so nothing ever pops into existence.

Usage:
  compose20.py qc
  compose20.py [SRC_DIR] [OUT_DIR] [--from T] [--until T] [--only i,...] [--jobs N]

Env: FLIGHT_DATA (default flight_data30.json, falling back to
flight_data28.json until it exists), SRC (default src_frames_v10),
OUT (default comp_frames_v10).  Source frames are f%05d.jpg, 1-indexed
(frame i reads f%05d % (i+1)); output frames are 0-indexed f%05d.jpg % i,
matching V5.  Needs PYTHONPATH=pylibs for PIL.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flight import alt_to_value, value_to_alt

from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
R_EARTH = 6371000.0
W, H = 1920, 1080
FOV_V = 20.0
FY = (H / 2) / math.tan(math.radians(FOV_V / 2))
FX = FY
FPS = 30.0

_DEF_DATA = os.path.join(BASE, "flight_data30.json")
if not os.path.exists(_DEF_DATA):        # older data files still composite
    _DEF_DATA = os.path.join(BASE, "flight_data28.json")
DATA = json.load(open(os.environ.get("FLIGHT_DATA", _DEF_DATA)))
# KEEP_WM=1: leave the burned-in Google Earth logo/attribution in place
# (user 2026-10-15: the inpainted patch reads as a smudge over moving city
# imagery -- keep the logo instead of filling it)
KEEP_WM = bool(os.environ.get("KEEP_WM"))
ROUTE = DATA["route"]
SAMPLES = DATA["samples"]
FRAMES = DATA["frames"]
STEP = DATA.get("step", 0.1)
FPS = float(DATA.get("fps", 30))
TOTAL = float(DATA.get("total", FRAMES[-1]["t"]))
NOSE_DEG = DATA["emoji"]          # {"plane": -44.18, "car": 180.0, ...}
WALKS = DATA.get("walks", [])     # [[t0, t1], ...] rt windows drawn dashed

# CJK label font -- first existing candidate wins (portable across hosts;
# falls back to the classic error if none is present)
_FONT_CANDIDATES = [
    "/mnt/c/Windows/Fonts/msyh.ttc",                      # WSL Windows mount (tested)
    "C:\\Windows\\Fonts\\msyh.ttc",                        # native Windows
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",     # Debian/Ubuntu
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",                 # macOS
]
FONT_PATH = next((p for p in _FONT_CANDIDATES if os.path.exists(p)),
                 _FONT_CANDIDATES[0])
FONT_ZH = ImageFont.truetype(FONT_PATH, 34)
FONT_EN = ImageFont.truetype(FONT_PATH, 20)
SPRITE_BASE = 150     # every sprite's LONGEST side at scale 1.0 -- one base
                     # size for all kinds (user rule v13: same altitude =>
                     # same icon size, so no per-axis normalization)


def _load_sprite(kind):
    path = os.path.join(BASE, "emoji_%s.png" % kind)
    if not os.path.exists(path):            # placeholder until real sprite
        path = os.path.join(BASE, "emoji_car.png")
    img = Image.open(path).convert("RGBA")
    m = max(img.width, img.height)
    w = max(8, int(round(img.width * SPRITE_BASE / m)))
    h = max(8, int(round(img.height * SPRITE_BASE / m)))
    return img.resize((w, h), Image.LANCZOS)


SPRITES = {k: _load_sprite(k) for k in NOSE_DEG}

AHEAD_FILL = (150, 215, 255, 90)
AHEAD_W = 2
DONE_FILL = (255, 255, 255, 225)
DONE_W = 4
GLOW_FILL = (120, 200, 255, 45)
GLOW_W = 10
SKIP_PX = 1.0           # skip drawing segments shorter than this on screen

AIRPORTS = [
    ("香港国际机场 HKG", tuple(DATA["hkg"])),
    ("宿务麦克坦机场 CEB", tuple(DATA["ceb"])),
]
# (zh, en, ll, t0, t1, fade_out) -- timed labels, window edges fade 0.3s
# unless fade_out=False.  v30: 清湖北站 origin label REMOVED (user: 起点的
# 位置不用标记文字); 深圳湾口岸 spans the border approach + the walk crossing;
# the CEB windows shift with the walk3/drive-v2 timeline (+2.9s vs v28).
# U Story label removed earlier (user: "最后的 u story 去掉"); the parked car
# at the resort marks the destination in the final overview.
PIERS = [
    ("深圳湾口岸", "Shenzhen Bay Port",
     tuple(DATA.get("port", (22.510099, 113.935025))), 4.4, 6.8, True),
    ("宿务码头", "Cebu Pier 1", tuple(DATA["pier1"]), 25.4, 30.0, True),
    ("塔比拉兰", "Tagbilaran", tuple(DATA["tagb"]), 31.1, 32.6, True),
    ("锡基霍尔码头", "Siquijor Pier", tuple(DATA["siq"]), 33.0, 35.0, False),
]
FADE = 0.3


def ll2ecef(lat, lon, alt):
    la, lo = math.radians(lat), math.radians(lon)
    r = R_EARTH + alt
    return (math.cos(la) * math.cos(lo) * r,
            math.cos(la) * math.sin(lo) * r,
            math.sin(la) * r)


def normalize_route_rt(route, jump=2.0):
    """Repair legacy +offset rt on the ground segments (no-op on fixed data).

    Schema: flight rt in [0,10], drive [10,14.5], boat [14.5,20], moto
    [20,total].  The legacy generator emitted drive rt = 10 + car_t_at_s
    (i.e. [20,24.5]) and boat rt = 15 + boat_t_at_s (i.e. [29.5,35]) -- the
    segment start times were added on top of an inverse that already returned
    video time.  Repair: walk raw rt; any discontinuity with |delta| > `jump`
    between consecutive vertices shifts everything after it back by delta
    (rt must be non-decreasing per schema, so any such jump is an offset).
    Handles both positive offsets and a correctly-timed segment appended
    after offset ones (raw rt drops back down).  Correctly-normalized data
    has no such jumps, so the function is identity there.
    """
    out, shift, prev = [], 0.0, None
    for p in route:
        if prev is not None and abs(p[3] - prev) > jump:
            shift += p[3] - prev
        prev = p[3]
        out.append((p[0], p[1], p[2], p[3] - shift))
    if shift:
        print("normalize_route_rt: repaired ground-segment rt offsets "
              "(total shift %.1fs at end)" % shift)
    return out


def _is_walk_seg(rt0, rt1):
    """the segment ENDING at this vertex is a walking leg iff its mid-rt
    falls inside a data["walks"] window."""
    mid = 0.5 * (rt0 + rt1)
    return any(w0 - 1e-6 <= mid <= w1 + 1e-6 for w0, w1 in WALKS)


ROUTE_E = []
_prev_rt = None
for p in normalize_route_rt(ROUTE):
    walk = _is_walk_seg(_prev_rt, p[3]) if _prev_rt is not None else False
    ROUTE_E.append((ll2ecef(p[0], p[1], p[2]), p[3], walk))
    _prev_rt = p[3]
AIRPORT_E = [(name, ll2ecef(lat, lon, 0.0)) for name, (lat, lon) in AIRPORTS]
PIER_E = [(zh, en, ll2ecef(lat, lon, 0.0), t0, t1, fo)
          for zh, en, (lat, lon), t0, t1, fo in PIERS]


def find_runs():
    """maximal same-kind frame runs [kind, start_idx, end_idx]."""
    runs = []
    for i, fr in enumerate(FRAMES):
        if not runs or runs[-1][0] != fr["kind"]:
            runs.append([fr["kind"], i, i])
        else:
            runs[-1][2] = i
    return runs


def find_parks():
    """Park each leg's vehicle at its endpoint once the leg completes, so the
    final overview shows the whole journey's vehicles (user request).

    Kind-runs come from FRAMES; walk runs are not vehicles (nothing parks
    mid-journey).  A run whose successor never travels away (<100m between
    the two endpoints) would draw the same physical spot twice and is
    skipped.  The FINAL run never parks -- it stays the current vehicle
    (v31: that is the moto holding at U Story through the pull-back).
    """
    runs = find_runs()
    parks = []
    for k, (kind, s, e) in enumerate(runs[:-1]):
        if kind == "walk":
            continue
        end, nxt_end = FRAMES[e], FRAMES[runs[k + 1][2]]
        if math.dist(ll2ecef(end["lat"], end["lon"], 0),
                     ll2ecef(nxt_end["lat"], nxt_end["lon"], 0)) < 100.0:
            continue
        parks.append({"kind": kind, "t": end["t"], "lat": end["lat"],
                      "lon": end["lon"], "tan": end["tan"]})
    return parks


def find_waiting():
    """Every vehicle waits at its start anchor from t=0 until its leg begins
    (user: 第 n+1 段行程播放的时候，第 n+1 段的载具就在起点等着了，而不是
    突然出现).  Walks are not vehicles; the first run starts at t=0 so it is
    never drawn waiting."""
    out = []
    for kind, s, e in find_runs():
        if kind == "walk":
            continue
        fr = FRAMES[s]
        out.append({"kind": kind, "t": fr["t"], "lat": fr["lat"],
                    "lon": fr["lon"], "tan": fr["tan"]})
    return out


PARKS = find_parks()
WAITING = find_waiting()

# sprite scale vs camera altitude (v13, user rule): size is INVERSELY
# PROPORTIONAL to camera altitude -- scale = 13500m/alt, capped at 1.0.
# The v11 (exp 0.20) / v12 (exp 0.55) power-law compromises still read as
# screen decals because they were not proportional; a true 1/alt icon
# halves when the view width halves, exactly like an object on the
# ground.  The only deviation is a 0.12 floor (18px on the 150px base):
# above ~112km pure 1/alt would shrink the emoji to atoms (5.8Mm cruise
# -> 0.2px), so map-scale views keep a legible uniform pin instead.
SCALE_REF, SCALE_MIN = 13500.0, 0.12


def sprite_scale(alt):
    """size ~ 1/camera altitude (near-big/far-small); floor 0.12 keeps a
    legible 18px pin at cruise/overview scale."""
    return min(1.0, max(SCALE_MIN, SCALE_REF / alt))


# ---- "Google Earth" watermark removal ----
# ES cloud renders bake the wordmark + a data-credits line into the
# bottom-right of EVERY frame (persistent-edge bbox (1526,903)-(1721,962),
# identical in both videos; everything else bright in that corner is moving
# water-glint / cloud imagery).  User: "google earth 文字去掉".  Fill the box
# by bilinearly interpolating its border colours (two PIL resize lerps) and
# feather the paste -- over map imagery the patch reads as smooth map, no
# text, no seam.
WM_BOX = (1514, 890, 1734, 974)     # text bbox + ~12px anti-alias margin


def dewatermark(img):
    x0, y0, x1, y1 = WM_BOX
    w, h = x1 - x0, y1 - y0
    lcol = img.crop((x0, y0, x0 + 2, y1)).resize((1, h), Image.BOX)
    rcol = img.crop((x1 - 2, y0, x1, y1)).resize((1, h), Image.BOX)
    fh = Image.new(img.mode, (2, h))
    fh.paste(lcol, (0, 0))
    fh.paste(rcol, (1, 0))
    fh = fh.resize((w, h), Image.BILINEAR)     # per-row left->right lerp
    trow = img.crop((x0, y0, x1, y0 + 2)).resize((w, 1), Image.BOX)
    brow = img.crop((x0, y1 - 2, x1, y1)).resize((w, 1), Image.BOX)
    fv = Image.new(img.mode, (w, 2))
    fv.paste(trow, (0, 0))
    fv.paste(brow, (0, 1))
    fv = fv.resize((w, h), Image.BILINEAR)     # per-col top->bottom lerp
    fill = Image.blend(fh, fv, 0.5).filter(ImageFilter.GaussianBlur(3))
    mask = Image.new("L", (w, h), 0)           # feathered paste: no seam
    mask.paste(255, (8, 8, w - 8, h - 8))
    mask = mask.filter(ImageFilter.GaussianBlur(4))
    img.paste(fill, (x0, y0), mask)
    return img


# vestigial: the v10 rules dropped label decluttering, but minimal2s_v2.py
# calls LABEL_BOXES.clear(), so the global stays as an always-empty list
# (nothing appends to it any more)
LABEL_BOXES = []


def norm(v):
    n = math.sqrt(sum(c * c for c in v))
    return (v[0] / n, v[1] / n, v[2] / n)


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def look_at(cam, poi):
    f = norm((poi[0] - cam[0], poi[1] - cam[1], poi[2] - cam[2]))
    up0 = norm(cam)
    r = norm(cross(f, up0))
    u = cross(r, f)          # screen-up (V3 fix kept)
    return f, r, u


def visible(cam, pt):
    dx, dy, dz = pt[0] - cam[0], pt[1] - cam[1], pt[2] - cam[2]
    a = dx * dx + dy * dy + dz * dz
    b = 2 * (cam[0] * dx + cam[1] * dy + cam[2] * dz)
    c = (cam[0] ** 2 + cam[1] ** 2 + cam[2] ** 2) - R_EARTH * R_EARTH
    disc = b * b - 4 * a * c
    if disc <= 0:
        return True
    t1 = (-b - math.sqrt(disc)) / (2 * a)
    return t1 > 1.0 - 1e-6


def project(cam, basis, pt):
    f, r, u = basis
    dx, dy, dz = pt[0] - cam[0], pt[1] - cam[1], pt[2] - cam[2]
    zf = dot((dx, dy, dz), f)
    if zf <= 0:
        return None
    zr = dot((dx, dy, dz), r)
    zu = dot((dx, dy, dz), u)
    return (W / 2 + FX * zr / zf, H / 2 - FY * zu / zf, zf)


def interp_state(t):
    k = min(int(t / STEP), len(SAMPLES) - 2)
    u = t / STEP - k
    s0, s1 = SAMPLES[k], SAMPLES[k + 1]

    def lin_attr(key, idx):
        return s0[key][idx] + (s1[key][idx] - s0[key][idx]) * u

    def lin_alt(key):
        v0, v1 = alt_to_value(s0[key][2]), alt_to_value(s1[key][2])
        return value_to_alt(v0 + (v1 - v0) * u)

    if t >= 38.35:
        # seg5 (t>=38.4 global): the esp wrote kfs with v_write(H) every 0.1s
        # and ES interpolates those VALUES -- so interpolate in v_write space
        # and map through ES's measured true curve.  (The plain alt_to_value
        # lerp used for seg1-4 rides the WRONG sparse-tail CAL and distorts
        # the pull-back by ~4% mid-segment.)
        v0, v1 = v_write(s0["cam"][2]), v_write(s1["cam"][2])
        cam = (lin_attr("cam", 0), lin_attr("cam", 1),
               true_alt(v0 + (v1 - v0) * u))
    else:
        cam = (lin_attr("cam", 0), lin_attr("cam", 1), lin_alt("cam"))
    tgt = (lin_attr("tgt", 0), lin_attr("tgt", 1), lin_alt("tgt"))
    return cam, tgt


# ---- seg5 effective-altitude model (measured) ----
# v_write: what build_seg5_v2 wrote into the esp (identity = old dense CAL
# below 356.6km, corrected log-linear anchors above).
# true_alt: ES's measured value->altitude curve.  Anchors verified by panel
# readbacks (44km, 902km) and coastline mask fits (4038.5km on old f00781,
# 4521.9km on v2 f00781, 613.9km on v2 f00749).
_W_KNOTS = [(356557.7, 0.706755), (781000.0, 0.744671),
            (895553.0, 0.751845), (4038531.0, 0.830818),
            (4550000.0, 0.837070)]
_T_KNOTS = [(356557.7, 0.706755), (613936.0, 0.732741),
            (781000.0, 0.744671), (902000.0, 0.751845),
            (1801000.0, 0.787225), (3898000.0, 0.828950),
            (4038531.0, 0.830818), (4521875.0, 0.837070)]


def v_write(h):
    if h <= _W_KNOTS[0][0]:
        return alt_to_value(h)
    if h > _W_KNOTS[-1][0]:      # extrapolate top-segment slope
        (a0, v0), (a1, v1) = _W_KNOTS[-2], _W_KNOTS[-1]
        return v1 + math.log(h / a1) * (v1 - v0) / math.log(a1 / a0)
    for (a0, v0), (a1, v1) in zip(_W_KNOTS, _W_KNOTS[1:]):
        if h <= a1:
            return v0 + math.log(h / a0) * (v1 - v0) / math.log(a1 / a0)


def true_alt(v):
    if v <= _T_KNOTS[0][1]:
        return value_to_alt(v)
    if v > _T_KNOTS[-1][1]:
        (a0, v0), (a1, v1) = _T_KNOTS[-2], _T_KNOTS[-1]
        return a1 * math.exp(math.log(a1 / a0) * (v - v1) / (v1 - v0))
    for (a0, v0), (a1, v1) in zip(_T_KNOTS, _T_KNOTS[1:]):
        if v <= v1:
            return a0 * math.exp(math.log(a1 / a0) * (v - v0) / (v1 - v0))


def draw_polyline(overlay, draw, pts, width, fill):
    seg = []
    for p in pts:
        seg.append((p[0], p[1]))
        if len(seg) >= 2 and (abs(seg[-1][0] - seg[-2][0]) > 300
                              or abs(seg[-1][1] - seg[-2][1]) > 300):
            seg.pop()
            if len(seg) >= 2:
                draw.line(seg, fill=fill, width=width, joint="curve")
            seg = [(p[0], p[1])]
    if len(seg) >= 2:
        draw.line(seg, fill=fill, width=width, joint="curve")


def draw_dashed(draw, pts, width, fill, on=14.0, off=10.0):
    """Dashed polyline (PIL has no dash) -- the walking transitions."""
    dashes = []                       # [(x0, y0, x1, y1), ...] "on" pieces
    acc, drawing = 0.0, True
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]
        x1, y1 = pts[i + 1]
        dist = math.hypot(x1 - x0, y1 - y0)
        if dist < 1e-9:
            continue
        ux, uy = (x1 - x0) / dist, (y1 - y0) / dist
        pos = 0.0
        while pos < dist - 1e-9:
            span = on if drawing else off
            take = min(span - acc, dist - pos)
            if drawing:
                dashes.append((x0 + ux * pos, y0 + uy * pos,
                               x0 + ux * (pos + take), y0 + uy * (pos + take)))
            acc += take
            pos += take
            if acc >= span - 1e-9:
                drawing = not drawing
                acc = 0.0
    for a, b, c, dd in dashes:
        draw.line([a, b, c, dd], fill=fill, width=width)


def emoji_sprite(kind, theta_screen, scale=1.0):
    """Sprite rotated so the nose points along theta_screen (rad, y-down).
    scale shrinks it with camera altitude (sprite_scale: strict perspective).

    (v31: no "walk" kind anymore -- walks are drawn as the animated dashed
    line only, never as a sprite; see vehicle_entries.)"""
    spr = SPRITES[kind]
    if scale < 0.999:
        w = max(8, int(spr.width * scale))
        h = max(8, int(spr.height * scale))
        spr = spr.resize((w, h), Image.LANCZOS)
    rot_deg = NOSE_DEG.get(kind, 180.0) - math.degrees(theta_screen)
    return spr.rotate(rot_deg, resample=Image.BICUBIC, expand=True)


def sprite_for(kind):
    return SPRITES.get(kind) or SPRITES.get("car")


def pier_alpha(t, t0, t1, fade_out):
    if t < t0 or t > t1:
        return 0.0
    a = (t - t0) / FADE
    if fade_out:
        a = min(a, (t1 - t) / FADE)
    return max(0.0, min(1.0, a))


def draw_marker(d, px, py, text_main, text_sub, alpha, sub_dy=0):
    """V5 airport-marker style (dot + leader + stroke text), with optional
    second (smaller) line and an overall opacity 0..1 for window fading.

    text_sub placement: sub_dy > 0 -> below main line (label below the dot);
    sub_dy < 0 -> above it (label above the dot), keeping the line nearest the
    dot anchored exactly where V5 put its single line.
    """
    a = max(0.0, min(1.0, alpha))
    if a <= 0:
        return

    def ca(v):
        return int(round(v * a))

    r = 7
    d.ellipse([px - r, py - r, px + r, py + r], fill=(255, 210, 80, ca(255)),
              outline=(60, 45, 10, ca(255)), width=2)
    if py < 140:                       # near top edge -> label below
        lx, ly = px + 22, py + 26
        d.line([(px + 6, py + 6), (lx, ly - 8)], fill=(255, 255, 255, ca(200)),
               width=2)
    else:
        lx, ly = px + 22, py - 46
        d.line([(px + 6, py - 6), (lx, ly + 12)], fill=(255, 255, 255, ca(200)),
               width=2)
    d.text((lx, ly), text_main, font=FONT_ZH, fill=(255, 255, 255, ca(255)),
           stroke_width=4, stroke_fill=(0, 0, 0, ca(200)))
    if text_sub:
        d.text((lx, ly + sub_dy), text_sub, font=FONT_EN,
               fill=(255, 255, 255, ca(225)),
               stroke_width=3, stroke_fill=(0, 0, 0, ca(180)))


def draw_labels(d, t, cam_e, basis):
    """Airport + pier labels for time t."""
    for name, pe in AIRPORT_E:
        if not visible(cam_e, pe):
            continue
        p = project(cam_e, basis, pe)
        if p is None:
            continue
        px, py = p[0], p[1]
        if not (-150 <= px <= W + 150 and -150 <= py <= H + 150):
            continue
        draw_marker(d, px, py, name, None, 1.0)

    for zh, en, pe, t0, t1, fade_out in PIER_E:
        a = pier_alpha(t, t0, t1, fade_out)
        if a <= 0:
            continue
        if not visible(cam_e, pe):
            continue
        p = project(cam_e, basis, pe)
        if p is None:
            continue
        px, py = p[0], p[1]
        if not (-150 <= px <= W + 150 and -150 <= py <= H + 150):
            continue
        # second line sits further away from the dot than the anchored line
        draw_marker(d, px, py, zh, en, a, sub_dy=40 if py < 140 else -40)


def vehicle_entries(t, frame, cam_e, basis, cam):
    """Waiting + parked leg vehicles + the current one, in draw order
    (waiting first -- they were there before anyone moved; parks oldest
    first; current last -> a newer vehicle covers an older one).

    User rules (v10): every entry is drawn at its exact projected geographic
    anchor -- no decluttering, no displacement -- and all vehicles scale with
    sprite_scale(cam alt) so they follow the map view's near-big/far-small
    perspective.  Overlap between vehicles is allowed.

    v30 (user: 第 n+1 段载具提前在起点等着): vehicles whose leg has not
    started yet are drawn WAITING at their start anchor from t=0, so no
    vehicle ever pops into existence mid-video.

    v31 (user: 别画人了, 动态虚线表示步行): walk frames draw NO current
    vehicle -- the growing dashed line is the walk itself.
    """
    scale = sprite_scale(cam[2])
    d_a = max(2000.0, 0.15 * cam[2])
    entries = []

    def _entry(rec):
        pe = ll2ecef(rec["lat"], rec["lon"], 2.0)
        if not visible(cam_e, pe):
            return None
        p = project(cam_e, basis, pe)
        if p is None or not (-100 <= p[0] <= W + 100
                             and -100 <= p[1] <= H + 100):
            return None
        tan = rec["tan"]
        pl = project(cam_e, basis, (pe[0] + tan[0] * d_a,
                                    pe[1] + tan[1] * d_a,
                                    pe[2] + tan[2] * d_a))
        theta = math.atan2(pl[1] - p[1], pl[0] - p[0]) if pl else 0.0
        return {"kind": rec["kind"], "cur": False,
                "spr": emoji_sprite(rec["kind"], theta, scale),
                "x": p[0], "y": p[1]}

    for wk in WAITING:
        if t >= wk["t"] - 1e-6:      # its leg already started (or starts now)
            continue
        e = _entry(wk)
        if e:
            e["wait"] = True
            entries.append(e)
    for pk in PARKS:
        if t <= pk["t"] + 1e-6:
            continue
        e = _entry(pk)
        if e:
            entries.append(e)
    veh_e = ll2ecef(frame["lat"], frame["lon"], max(frame["alt"], 2.0))
    if frame["kind"] != "walk":            # v31: walks have no vehicle
        p = project(cam_e, basis, veh_e)
        if p is not None and -80 <= p[0] <= W + 80 and -80 <= p[1] <= H + 80:
            tan = frame["tan"]
            pl = project(cam_e, basis, (veh_e[0] + tan[0] * d_a,
                                        veh_e[1] + tan[1] * d_a,
                                        veh_e[2] + tan[2] * d_a))
            theta = math.atan2(pl[1] - p[1], pl[0] - p[0]) if pl else 0.0
            kind = frame["kind"] if frame["kind"] in SPRITES else "car"
            entries.append({"kind": kind, "cur": True,
                            "spr": emoji_sprite(kind, theta, scale),
                            "x": p[0], "y": p[1]})
    for e in entries:
        e["w"], e["h"] = e["spr"].size
    return entries


def _draw_sprite(base, spr, x, y):
    """Sprite with a subtle drop shadow, centered at (x, y)."""
    sh = Image.new("RGBA", spr.size, (0, 0, 0, 0))
    sh.paste((0, 0, 0, 70), (0, 0, spr.size[0], spr.size[1]),
             mask=spr.split()[3])
    base.alpha_composite(sh, (int(x) - spr.width // 2 + 3,
                              int(y) - spr.height // 2 + 4))
    base.alpha_composite(spr, (int(x) - spr.width // 2,
                               int(y) - spr.height // 2))


def process(i, src_path, out_path):
    t = i / FPS
    frame = FRAMES[i]
    cam, tgt = interp_state(t)
    cam_e = ll2ecef(*cam)
    tgt_e = ll2ecef(*tgt)
    basis = look_at(cam_e, tgt_e)

    img = Image.open(src_path).convert("RGB")
    if not KEEP_WM:
        img = dewatermark(img)
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)

    # full 3D itinerary, split at current time; drop vertices <1px apart.
    # Each kept vertex carries the walk flag of the segment ENDING at it,
    # so the polyline splits into solid runs and dashed walk runs.
    ahead, done = [], []
    for pe, rt, walk in ROUTE_E:
        if not visible(cam_e, pe):
            continue
        p = project(cam_e, basis, pe)
        if p is None:
            continue
        lst = done if rt <= t else ahead
        if lst:
            dx = p[0] - lst[-1][0]
            dy = p[1] - lst[-1][1]
            if dx * dx + dy * dy < SKIP_PX * SKIP_PX:
                continue
        lst.append((p[0], p[1], walk))

    def _runs(pts):
        """maximal same-flag runs; each run after the first is stitched to
        the previous run's last point so solid and dashed pieces connect."""
        out = []
        for x, y, w in pts:
            if out and out[-1][1] == w:
                out[-1][0].append((x, y))
            else:
                out.append(([(x, y)], w))
        for k in range(1, len(out)):
            out[k][0].insert(0, out[k - 1][0][-1])
        return out

    if ahead:
        for pts, w in _runs(ahead):
            if w:      # walk ahead: dark dashed underlay + blue dashes
                draw_dashed(d, pts, AHEAD_W + 4, (0, 0, 0, 80))
                draw_dashed(d, pts, AHEAD_W, AHEAD_FILL)
            else:
                draw_polyline(overlay, d, pts, AHEAD_W + 4, (0, 0, 0, 80))
                draw_polyline(overlay, d, pts, AHEAD_W, AHEAD_FILL)
    if done:
        for pts, w in _runs(done):
            if w:      # walk done: dashed glow + white dashes
                draw_dashed(d, pts, GLOW_W, GLOW_FILL)
                draw_dashed(d, pts, DONE_W, DONE_FILL)
            else:
                draw_polyline(overlay, d, pts, GLOW_W, GLOW_FILL)
                draw_polyline(overlay, d, pts, DONE_W, DONE_FILL)

    # airport + pier labels
    draw_labels(d, t, cam_e, basis)

    base = img.convert("RGBA")
    base.alpha_composite(overlay)

    # vehicles (user rule v10): finished vehicles stay parked at their exact
    # geographic anchors -- no decluttering, no leader lines; overlap is
    # allowed and resolved by draw order.  vehicle_entries returns them in
    # park-time order (oldest first) with the current vehicle LAST, so a new
    # vehicle covers an older one wherever they overlap.  Every entry already
    # carries sprite_scale(cam alt), so all vehicles shrink with the map view.
    entries = vehicle_entries(t, frame, cam_e, basis, cam)
    for e in entries:
        _draw_sprite(base, e["spr"], e["x"], e["y"])

    base.convert("RGB").save(out_path, quality=92)


def _fail(msg):
    print("  FAIL %s" % msg)
    return 1


def _ok(msg):
    print("  ok   %s" % msg)
    return 0


def qc():
    """Projection / interpolation / schedule self-test.  Returns #failures."""
    bad = 0
    print("qc: route rt normalization")
    raw_max = ROUTE[-1][3]
    fixed_max = ROUTE_E[-1][1]
    # route must be fully revealed before the video ends (>=24s data has a
    # pull-back tail after the last route vertex)
    bad += _ok("raw rt max %.3f -> normalized %.3f (total %.1f, ends %s)"
               % (raw_max, fixed_max, TOTAL,
                  "at video end" if abs(fixed_max - TOTAL) < 0.01
                  else "%.1fs early (pull-back tail)" % (TOTAL - fixed_max))) \
        if fixed_max <= TOTAL + 0.01 else \
        _fail("normalized rt max %.3f > total %.1f" % (fixed_max, TOTAL))
    segs = [("[0,5.1] car_sz", 0.0, 5.1), ("[5.1,6.3] walk1", 5.1, 6.3),
            ("[6.3,11.3] car_hk", 6.3, 11.3), ("[11.3,12.8] walk2", 11.3, 12.8),
            ("[13.3,23.3] flight", 13.3, 23.3), ("[23.3,24.8] walk3", 23.3, 24.8),
            ("[24.8,28.9] drive", 24.8, 28.9), ("[28.9,34.4] boat", 28.9, 34.4),
            ("[34.4,38.4] moto", 34.4, 38.4)]
    fixed_rts = [p[1] for p in ROUTE_E]
    for name, lo, hi in segs:
        in_seg = [r for r in fixed_rts if lo - 1e-6 <= r <= hi + 1e-6]
        covered = len(in_seg) > 0 and abs(min(in_seg) - lo) < 0.35 \
            and abs(max(in_seg) - hi) < 0.35
        bad += _ok("%s: %d verts, rt %.3f..%.3f" % (name, len(in_seg),
                                                    min(in_seg), max(in_seg))) \
            if covered else _fail("%s coverage wrong" % name)

    print("qc: dashed walk windows (route verts flagged as walk segments)")
    for w0, w1 in WALKS:
        n = sum(1 for _, rt, w in ROUTE_E
                if w and w0 - 1e-6 <= rt <= w1 + 1e-6)
        bad += _ok("walk [%.1f,%.1f]: %d dashed verts" % (w0, w1, n)) \
            if n >= 10 else \
            _fail("walk [%.1f,%.1f]: only %d dashed verts" % (w0, w1, n))

    print("qc: camera state interpolation roundtrip (sample times)")
    for k in (0, 1, 20, 60, 133, 134, 150, 200, 233, 234, 248, 249, 289,
              290, 340, 383, 384, 400, 404):
        if k >= len(SAMPLES):
            continue
        s = SAMPLES[k]
        cam, tgt = interp_state(s["t"])
        # t>=38.4 samples carry the INTENDED alt; interp_state maps through
        # v_write -> true_alt, so expect exactly that at sample times
        e_cam_alt = true_alt(v_write(s["cam"][2])) if s["t"] >= 38.35 \
            else s["cam"][2]
        d = max(abs(cam[0] - s["cam"][0]), abs(cam[1] - s["cam"][1]),
                abs(tgt[0] - s["tgt"][0]), abs(tgt[1] - s["tgt"][1]),
                abs(alt_to_value(cam[2]) - alt_to_value(e_cam_alt)),
                abs(alt_to_value(tgt[2]) - alt_to_value(s["tgt"][2])))
        bad += _ok("t=%5.1f roundtrip err %.2e" % (s["t"], d)) if d < 1e-6 \
            else _fail("t=%5.1f roundtrip err %.2e" % (s["t"], d))

    print("qc: basis orthonormality + cardinal directions per phase")
    for i in (0, 60, 100, 153, 200, 300, 400, 550, 700, 745, 800, 868,
              960, 1035, 1153, 1200, 1212):
        if i >= len(FRAMES):
            continue
        t = i / FPS
        cam, tgt = interp_state(t)
        cam_e = ll2ecef(*cam)
        f, r, u = look_at(cam_e, ll2ecef(*tgt))
        orth = max(abs(dot(f, r)), abs(dot(f, u)), abs(dot(r, u)))
        nrm = max(abs(math.sqrt(dot(f, f)) - 1), abs(math.sqrt(dot(r, r)) - 1),
                  abs(math.sqrt(dot(u, u)) - 1))
        frame = FRAMES[i]
        pe = ll2ecef(frame["lat"], frame["lon"], max(frame["alt"], 2.0))
        p0 = project(cam_e, (f, r, u), pe)
        p_n = project(cam_e, (f, r, u),
                      ll2ecef(frame["lat"] + 0.05, frame["lon"], 0))
        p_e = project(cam_e, (f, r, u),
                      ll2ecef(frame["lat"], frame["lon"] + 0.05, 0))
        msgs = []
        if orth > 1e-9 or nrm > 1e-9:
            bad += 1
            msgs.append("FAIL orth=%.1e nrm=%.1e" % (orth, nrm))
        else:
            msgs.append("orth ok")
        if p0 is None or p_n is None or p_e is None:
            bad += 1
            msgs.append("FAIL cardinal project None")
        else:
            if p_n[1] < p0[1] and p_e[0] > p0[0]:
                msgs.append("N up / E right ok")
            else:
                bad += 1
                msgs.append("FAIL N/E direction")
        print("  f%3d t=%5.2f %-5s %s" % (i, t, frame["kind"], ", ".join(msgs)))

    print("qc: emoji screen heading vs route tangent true bearing")
    picks = {90, 160, 240, 310, 460, 540, 600, 700, 800, 900, 1000, 1080,
             1180}
    firsts = {}
    for i, fr in enumerate(FRAMES):
        if fr["kind"] == "walk":             # v31: walks draw no emoji
            continue
        firsts.setdefault(fr["kind"], []).append(i)
    for k, idxs in firsts.items():          # first / thirds / last of each kind
        picks.update((idxs[0], idxs[len(idxs) // 3],
                      idxs[2 * len(idxs) // 3], idxs[-1]))
    for i in sorted(picks):
        if i >= len(FRAMES):
            continue
        t = i / FPS
        frame = FRAMES[i]
        if frame["kind"] == "walk":          # v31: no sprite on walk frames
            continue
        cam, tgt = interp_state(t)
        cam_e = ll2ecef(*cam)
        basis = look_at(cam_e, ll2ecef(*tgt))
        veh_e = ll2ecef(frame["lat"], frame["lon"], max(frame["alt"], 2.0))
        p = project(cam_e, basis, veh_e)
        tan = frame["tan"]
        la, lo = math.radians(frame["lat"]), math.radians(frame["lon"])
        east = (-math.sin(lo), math.cos(lo), 0.0)
        north = (-math.sin(la) * math.cos(lo), -math.sin(la) * math.sin(lo),
                 math.cos(la))
        brg_true = math.degrees(math.atan2(dot(tan, east), dot(tan, north))) % 360
        if p is None:
            print("  f%3d t=%5.2f %-5s emoji behind camera (off-screen)"
                  % (i, t, frame["kind"]))
            continue
        d_a = max(2000.0, 0.15 * cam[2])
        pl = project(cam_e, basis, (veh_e[0] + tan[0] * d_a,
                                    veh_e[1] + tan[1] * d_a,
                                    veh_e[2] + tan[2] * d_a))
        theta = math.atan2(pl[1] - p[1], pl[0] - p[0]) if pl else 0.0
        hdg = math.degrees(theta) % 360          # screen angle, y-down, CW
        compass = (hdg + 90) % 360
        derr = (compass - brg_true + 180) % 360 - 180
        stat = "ok" if abs(derr) < 2.0 else "FAIL"
        bad += 0 if stat == "ok" else 1
        print("  f%3d t=%5.2f %-5s screen=%7.2f compass=%6.1f true=%6.1f "
              "err=%+5.2f %s @(%.0f,%.0f)"
              % (i, t, frame["kind"], hdg, compass, brg_true, derr, stat,
                 p[0], p[1]))

    print("qc: pier label windows + fade")
    for zh, en, pe, t0, t1, fo in PIER_E:
        if t0 >= TOTAL:
            print("  %-9s window starts after video end (t0=%.1f, total=%.1f)"
                  " -- skipped" % (zh, t0, TOTAL))
            continue
        cases = [(t0 - 0.05, 0.0), (t0, 0.0), (t0 + FADE, 1.0),
                 ((t0 + t1) / 2, 1.0), (t1 - FADE, 1.0),
                 (t1, 0.0 if fo else 1.0), (t1 + 0.05, 0.0)]
        for t, want in cases:
            a = pier_alpha(t, t0, t1, fo)
            good = abs(a - want) < 1e-9
            bad += 0 if good else 1
            print("  %-7s t=%5.2f alpha=%.3f want=%.3f %s"
                  % (zh, min(t, 99.0), a, want, "ok" if good else "FAIL"))

    print("qc: parked vehicles")
    for pk in PARKS:
        print("  %-6s parks at t=%4.1f  (%.5f, %.5f)"
              % (pk["kind"], pk["t"], pk["lat"], pk["lon"]))
    bad += _ok("5 parks (car_sz/car_hk/plane/car/boat)") if len(PARKS) == 5 \
        else _fail("expected 5 parks, got %d" % len(PARKS))

    print("qc: waiting vehicles (drawn at their start anchor from t=0)")
    for wk in WAITING:
        print("  %-6s waits until t=%4.1f  (%.5f, %.5f)"
              % (wk["kind"], wk["t"], wk["lat"], wk["lon"]))
    bad += _ok("6 waiting entries (car_sz starts at t=0, never drawn)") \
        if len(WAITING) == 6 and WAITING[0]["kind"] == "car_sz" \
        and WAITING[0]["t"] == 0.0 else \
        _fail("expected 6 waiting entries starting with car_sz@0, got %d"
              % len(WAITING))
    bad += _ok("no walk in waiting/parks") \
        if all(w["kind"] != "walk" for w in WAITING + PARKS) else \
        _fail("walk leaked into waiting/parks")

    # the user's actual requirement: one frame before each leg starts, its
    # vehicle is already drawn WAITING at its exact start anchor (never a
    # pop-in).  Distant vehicles are horizon/bounds-filtered as always, but
    # each leg's start is (by itinerary construction) at its predecessor's
    # end, so the waiting vehicle is always near the camera here.
    print("qc: waiting vehicle present at its start anchor one frame"
          " before its leg starts")
    for wk in WAITING[1:]:
        t = wk["t"] - 1.0 / FPS
        i = min(int(round(t * FPS)), len(FRAMES) - 1)
        frame = FRAMES[i]
        cam, tgt = interp_state(i / FPS)
        cam_e = ll2ecef(*cam)
        basis = look_at(cam_e, ll2ecef(*tgt))
        entries = vehicle_entries(i / FPS, frame, cam_e, basis, cam)
        q = project(cam_e, basis, ll2ecef(wk["lat"], wk["lon"], 2.0))
        if q is None:
            bad += _fail("%-6s start anchor behind camera at t=%.2f"
                         % (wk["kind"], t))
            continue
        hit = any(e.get("wait") and math.hypot(e["x"] - q[0], e["y"] - q[1]) <= 1.5
                  for e in entries)
        bad += _ok("%-6s waiting at its start anchor at t=%.2f"
                   % (wk["kind"], t)) if hit else \
            _fail("%-6s NOT waiting at its start anchor at t=%.2f"
                  % (wk["kind"], t))

    # informational census (visibility/bounds filter distant vehicles)
    print("qc: vehicle census (waiting + parked + current) at key times")
    for tt in (6.0, 12.0, 15.0, 30.0, 40.4):
        i = min(int(tt * FPS), len(FRAMES) - 1)
        frame = FRAMES[i]
        cam, tgt = interp_state(i / FPS)
        cam_e = ll2ecef(*cam)
        basis = look_at(cam_e, ll2ecef(*tgt))
        entries = vehicle_entries(i / FPS, frame, cam_e, basis, cam)
        n_wait = sum(1 for e in entries if e.get("wait"))
        n_park = sum(1 for e in entries if not e.get("wait") and not e["cur"])
        n_cur = sum(1 for e in entries if e["cur"])
        print("  t=%4.1f: %d drawn (%d wait + %d park + %d cur)"
              % (tt, len(entries), n_wait, n_park, n_cur))

    # final overview frame (user rule v10): all vehicles present and every
    # one drawn at its exact geographic anchor.  Overlap between vehicles is
    # ALLOWED now (newer drawn over older), so the old pairwise-overlap and
    # label-box FAILs are gone; what must hold is anchoredness.
    i = len(FRAMES) - 1
    t = i / FPS
    frame = FRAMES[i]
    cam, tgt = interp_state(t)
    cam_e = ll2ecef(*cam)
    basis = look_at(cam_e, ll2ecef(*tgt))
    entries = vehicle_entries(t, frame, cam_e, basis, cam)
    print("  final frame t=%.2f: %d vehicles" % (t, len(entries)))
    for e in entries:
        print("    %-6s %s sprite %dx%d at (%.1f,%.1f)"
              % (e["kind"], "cur" if e["cur"] else "park",
                 e["w"], e["h"], e["x"], e["y"]))
    bad += _ok("6 vehicles in final overview") if len(entries) == 6 else \
        _fail("expected 6 vehicles in final frame, got %d" % len(entries))
    park_kinds = sorted(e["kind"] for e in entries if not e["cur"])
    bad += _ok("parked kinds boat/car/car_hk/car_sz/plane") if park_kinds == \
        ["boat", "car", "car_hk", "car_sz", "plane"] else \
        _fail("parked kinds %s != ['boat', 'car', 'car_hk', 'car_sz', "
              "'plane']" % park_kinds)
    bad += _ok("current vehicle is the resort moto (v31: no car at U Story)") \
        if entries and entries[-1]["cur"] and entries[-1]["kind"] == "moto" \
        else _fail("current vehicle missing or not the moto at the resort")
    # each drawn position must equal its geographic anchor's projection
    # (<=1.5px); parked geo from PARKS, current from the frame state
    by_kind = {p["kind"]: p for p in PARKS}
    for e in entries:
        if e["cur"]:
            geo = ll2ecef(frame["lat"], frame["lon"], max(frame["alt"], 2.0))
        else:
            pk = by_kind[e["kind"]]
            geo = ll2ecef(pk["lat"], pk["lon"], 2.0)
        q = project(cam_e, basis, geo)
        if q is None:
            bad += _fail("final %s anchor projects behind camera" % e["kind"])
            continue
        err = math.hypot(q[0] - e["x"], q[1] - e["y"])
        bad += _ok("%-5s drawn on its anchor (err %.2fpx)" % (e["kind"], err)) \
            if err <= 1.5 else \
            _fail("%-5s drawn %.2fpx off its anchor" % (e["kind"], err))

    print("qc: emoji bounds across all frames (anchor within +/-80px clip)")
    oob = []
    n_veh = 0
    for i in range(len(FRAMES)):
        t = i / FPS
        frame = FRAMES[i]
        if frame["kind"] == "walk":         # v31: walks draw no emoji
            continue
        n_veh += 1
        cam, tgt = interp_state(t)
        cam_e = ll2ecef(*cam)
        basis = look_at(cam_e, ll2ecef(*tgt))
        p = project(cam_e, basis,
                    ll2ecef(frame["lat"], frame["lon"],
                            max(frame["alt"], 2.0)))
        if p is None:
            continue
        if not (-80 <= p[0] <= W + 80 and -80 <= p[1] <= H + 80):
            # emoji is clipped out; count only if it should be near-viewable
            oob.append((i, t, frame["kind"], p[0], p[1]))
    if oob:
        print("  %d frame(s) with emoji anchor outside clip margins:" % len(oob))
        for i, t, k, x, y in oob[:10]:
            print("    f%03d t=%.2f %s (%.0f,%.0f)" % (i, t, k, x, y))
    else:
        bad += _ok("all %d vehicle emoji anchors in bounds (%d walk frames "
                   "spriteless)" % (n_veh, len(FRAMES) - n_veh))
    print("qc: %s" % ("ALL PASS" if bad == 0 else "%d FAILURES" % bad))
    return bad


def parse_args(argv):
    src = os.environ.get("SRC", "src_frames_v10")
    out = os.environ.get("OUT", "comp_frames_v10")
    only = until = start = None
    jobs = min(8, os.cpu_count() or 1)
    pos = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--until":
            until = float(argv[i + 1]); i += 2
        elif a == "--from":
            start = float(argv[i + 1]); i += 2
        elif a == "--only":
            only = [int(x) for x in argv[i + 1].split(",")]; i += 2
        elif a == "--jobs":
            jobs = int(argv[i + 1]); i += 2
        else:
            pos.append(a); i += 1
    if len(pos) > 0:
        src = pos[0]
    if len(pos) > 1:
        out = pos[1]
    return src, out, only, start, until, jobs


def _work(i, src_dir, out_dir):
    s = os.path.join(src_dir, "f%05d.jpg" % (i + 1))   # ffmpeg 1-indexed
    if not os.path.exists(s):
        return ("missing", i)
    process(i, s, os.path.join(out_dir, "f%05d.jpg" % i))
    return (None, i)


def main():
    src_dir, out_dir, only, start, until, jobs = parse_args(sys.argv[1:])
    os.makedirs(out_dir, exist_ok=True)
    if only is not None:
        todo = only
    else:
        todo = list(range(len(FRAMES)))
        if start is not None:
            todo = [i for i in todo if i / FPS >= start - 1e-9]
        if until is not None:
            todo = [i for i in todo if i / FPS <= until + 1e-9]
    print("compose20: %d frames %s -> %s (jobs=%d)"
          % (len(todo), src_dir, out_dir, jobs))

    t0 = __import__("time").time()
    if jobs <= 1:
        for n, i in enumerate(todo):
            err, _ = _work(i, src_dir, out_dir)
            if err:
                print(err, i)
            if n % 60 == 0:
                print("  %d/%d (%.1fs)" % (n, len(todo),
                                           __import__("time").time() - t0),
                      flush=True)
    else:
        import functools
        from concurrent.futures import ProcessPoolExecutor
        wf = functools.partial(_work, src_dir=src_dir, out_dir=out_dir)
        with ProcessPoolExecutor(max_workers=jobs) as ex:
            for n, (err, _) in enumerate(ex.map(wf, todo, chunksize=4)):
                if err:
                    print(err)
                if n % 60 == 0:
                    print("  %d/%d (%.1fs)" % (n, len(todo),
                                               __import__("time").time() - t0),
                          flush=True)
    print("done: %d frames in %.1fs"
          % (len(todo), __import__("time").time() - t0))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "qc":
        sys.exit(1 if qc() else 0)
    main()
