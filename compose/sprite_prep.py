#!/usr/bin/env python3
"""Sprite prep for the user's car.PNG / boat.PNG icons.

Pipeline per icon (output: nose-LEFT, transparent, no white fringe):
  1. flood-fill white background from the border (thresh 45 eats the
     anti-aliased white halo; interior highlights stay - not connected)
  2. largest connected component (kills stray specks / watermarks)
  3. PCA major axis -> rotate so the tip end points LEFT (180-deg nose
     convention, same as the original emoji sprites -> compose20.py needs
     no NOSE_DEG change)
  4. fringe cleanup: alpha erode 1px, drop alpha<100, and recolor the
     remaining semi-transparent edge by bleeding opaque-core colors
     outward (Gaussian) -- kills the white rim completely
"""
import collections
import math

from PIL import Image, ImageDraw, ImageFilter

SEEDS = lambda w, h: [(2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3),
                      (w // 2, 2), (w // 2, h - 3), (2, h // 2), (w - 3, h // 2)]


def strip_bg(im, thresh=45):
    rgb = im.convert('RGB')
    for s in SEEDS(im.width, im.height):
        ImageDraw.floodfill(rgb, s, (255, 0, 255), thresh=thresh)
    out = Image.new('RGBA', im.size, (0, 0, 0, 0))
    px, op = rgb.load(), out.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b = px[x, y]
            if not (r == 255 and g == 0 and b == 255):
                op[x, y] = (r, g, b, 255)
    return out


def largest_component_bbox(im):
    a = im.getchannel('A')
    TW, TH = max(1, im.width // 8), max(1, im.height // 8)
    t = a.resize((TW, TH), Image.BOX)
    tp = t.load()
    seen = [[False] * TW for _ in range(TH)]
    best = (0, (0, 0, TW - 1, TH - 1))
    for sy in range(TH):
        for sx in range(TW):
            if tp[sx, sy] > 40 and not seen[sy][sx]:
                q = collections.deque([(sx, sy)])
                seen[sy][sx] = True
                n, x0, y0, x1, y1 = 0, sx, sy, sx, sy
                while q:
                    x, y = q.popleft(); n += 1
                    x0 = min(x0, x); x1 = max(x1, x)
                    y0 = min(y0, y); y1 = max(y1, y)
                    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < TW and 0 <= ny < TH and not seen[ny][nx] \
                                and tp[nx, ny] > 40:
                            seen[ny][nx] = True
                            q.append((nx, ny))
                if n > best[0]:
                    best = (n, (x0, y0, x1, y1))
    _, (x0, y0, x1, y1) = best
    pad = 12
    return (max(0, x0 * 8 - pad), max(0, y0 * 8 - pad),
            min(im.width, (x1 + 1) * 8 + pad), min(im.height, (y1 + 1) * 8 + pad))


def keep_component(im):
    """crop to the largest component AND zero alpha outside it."""
    X0, Y0, X1, Y1 = largest_component_bbox(im)
    im = im.crop((X0, Y0, X1, Y1))
    tx0, ty0 = X0 // 8, Y0 // 8          # thumb indices still valid post-crop
    tx1, ty1 = (X1 - 1) // 8, (Y1 - 1) // 8
    a = im.getchannel('A').load()
    for y in range(im.height):
        for x in range(im.width):
            gx, gy = (x + X0) // 8, (y + Y0) // 8
            if not (tx0 <= gx <= tx1 and ty0 <= gy <= ty1):
                a[x, y] = 0
    return im.crop(im.getchannel('A').getbbox())


def nose_left_angle(im):
    """image angle (deg, y-down) of the tip end of the PCA major axis."""
    # aspect-preserving shrink: a square resize on an already-cropped sprite
    # would stretch the shape and corrupt the axis
    scale = 96.0 / max(im.width, im.height)
    tw, th = max(1, round(im.width * scale)), max(1, round(im.height * scale))
    a = im.getchannel('A').resize((tw, th))
    px = a.load()
    pts = [(x, y) for y in range(th) for x in range(tw) if px[x, y] > 40]
    n = len(pts)
    mx = sum(p[0] for p in pts) / n
    my = sum(p[1] for p in pts) / n
    sxx = sum((p[0] - mx) ** 2 for p in pts) / n
    syy = sum((p[1] - my) ** 2 for p in pts) / n
    sxy = sum((p[0] - mx) * (p[1] - my) for p in pts) / n
    deg = math.degrees(0.5 * math.atan2(2 * sxy, sxx - syy))
    vx, vy = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    projs = [((x - mx) * vx + (y - my) * vy) for x, y in pts]
    pmax, pmin = pts[projs.index(max(projs))], pts[projs.index(min(projs))]
    tip = pmin if pmin[1] < pmax[1] else pmax      # tip = smaller y end
    sgn = 1.0 if ((tip[0] - mx) * vx + (tip[1] - my) * vy) > 0 else -1.0
    return math.degrees(math.atan2(sgn * vy, sgn * vx))


def defringe(im):
    """erode alpha 1px, drop faint pixels, recolor the edge from the core."""
    a = im.getchannel('A')
    a = a.filter(ImageFilter.MinFilter(3))
    a = a.point(lambda v: 0 if v < 100 else v)
    # core colors bleed outward; use them wherever the pixel isn't opaque
    core_mask = a.point(lambda v: 255 if v >= 240 else 0)
    solid = Image.composite(im, Image.new('RGBA', im.size, (0, 0, 0, 0)), core_mask)
    bleed = solid.filter(ImageFilter.GaussianBlur(6))
    edge_mask = a.point(lambda v: 255 if 0 < v < 240 else 0)
    out = Image.composite(bleed, im, edge_mask)
    out.putalpha(a)
    return out.crop(out.getchannel('A').getbbox())


def prep(src, out):
    im = strip_bg(Image.open(src))
    im = keep_component(im)
    ang = nose_left_angle(im)
    rot = im.rotate(ang - 180.0, resample=Image.BICUBIC, expand=True)
    rot = keep_component(rot)          # bbox crop after rotation
    fin = defringe(rot)
    fin.save(out)
    print("%s -> %s  %s  (nose img-angle %.1f -> rotated left)" % (src, out, fin.size, ang))
    return fin


if __name__ == "__main__":
    car = prep("car.PNG", "emoji_car.png")
    car.save("emoji_moto.png")          # last leg renders as a car (user)
    prep("boat.PNG", "emoji_boat.png")

    for f in ("emoji_car.png", "emoji_boat.png"):
        v = Image.open(f).resize((100, 40), Image.BILINEAR)
        pv = v.load()
        print(f)
        for ry in range(40):
            row = ''
            for rx in range(100):
                r, g, b, al = pv[rx, ry]
                if al < 40:
                    row += '.'
                elif b > r + 40 and b > 120:
                    row += 'B'
                elif max(r, g, b) < 70:
                    row += 'D'
                elif r > 235 and g > 235 and b > 235:
                    row += 'W'          # residual near-white fringe shows here
                elif r > 190 and g > 130 and b < 110:
                    row += 'Y'          # body color (yellow car)
                else:
                    row += 'o'
            print(row)
