"""
Generates the app icon: a monitor with circular input-swap arrows (the KVM
"switch between computers" idea), rendered in the app's green on a dark rounded
square. Produces a multi-size .ico plus PNGs used by the window and tray.

Run:  python assets/make_icon.py
"""

from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

# Palette (matches the app's dark theme + green accent).
BG1 = (10, 15, 10)       # near-black rounded tile
BG2 = (18, 26, 18)
GREEN = (2, 200, 0)      # bright accent green
GREEN_DK = (2, 120, 2)
INK = (230, 255, 230)


def _rounded_mask(size, radius):
    m = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return m


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render(size: int) -> Image.Image:
    """Render the icon at the given square size with a supersampled pass."""
    ss = 4
    S = size * ss
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # rounded background tile with a soft vertical gradient
    radius = int(S * 0.22)
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    for y in range(S):
        td.line([(0, y), (S, y)], fill=(*_lerp(BG2, BG1, y / S), 255))
    tile.putalpha(_rounded_mask(S, radius))
    img.alpha_composite(tile)

    # subtle inner accent ring for depth
    d.rounded_rectangle([int(S*0.06), int(S*0.06), int(S*0.94), int(S*0.94)],
                        radius=int(S*0.17), outline=(*GREEN_DK, 90), width=max(2, S // 64))

    # --- monitor ---
    mx0, my0, mx1, my1 = int(S*0.20), int(S*0.22), int(S*0.80), int(S*0.62)
    bezel = max(3, S // 32)
    # screen bezel
    d.rounded_rectangle([mx0, my0, mx1, my1], radius=int(S*0.05),
                        outline=(*GREEN, 255), width=bezel)
    # screen fill
    d.rounded_rectangle([mx0 + bezel, my0 + bezel, mx1 - bezel, my1 - bezel],
                        radius=int(S*0.03), fill=(6, 20, 6, 255))
    # stand neck + base
    ncx = (mx0 + mx1) // 2
    d.rectangle([ncx - int(S*0.03), my1, ncx + int(S*0.03), my1 + int(S*0.10)], fill=(*GREEN, 255))
    d.rounded_rectangle([ncx - int(S*0.14), my1 + int(S*0.10), ncx + int(S*0.14), my1 + int(S*0.15)],
                        radius=int(S*0.02), fill=(*GREEN, 255))

    # --- swap arrows on the screen: two symmetric curved arrows forming a cycle ---
    cx, cy = (mx0 + mx1) // 2, (my0 + my1) // 2
    r = int((my1 - my0) * 0.26)
    aw = max(3, S // 44)
    gap = 34  # degrees of arc left open for each arrowhead

    def draw_cycle_arm(start, end, head_deg):
        # arc body
        d.arc([cx - r, cy - r, cx + r, cy + r], start=start, end=end,
              fill=(*INK, 255), width=aw)
        # arrowhead: triangle centered on the circle at head_deg, pointing along
        # the tangent (direction of travel)
        a = math.radians(head_deg)
        tx, ty = cx + r * math.cos(a), cy + r * math.sin(a)
        tang = a + math.pi / 2          # counter-clockwise tangent
        hl = int(S * 0.075)             # head length
        hw = int(S * 0.058)             # head half-width
        tip = (tx + hl * math.cos(tang), ty + hl * math.sin(tang))
        base_l = (tx + hw * math.cos(a), ty + hw * math.sin(a))
        base_r = (tx - hw * math.cos(a), ty - hw * math.sin(a))
        d.polygon([tip, base_l, base_r], fill=(*GREEN, 255))

    # top arm sweeps left->right (arrowhead on the right), bottom arm mirrors it
    draw_cycle_arm(180 + gap, 360 - gap, 360 - gap)
    draw_cycle_arm(gap, 180 - gap, 180 - gap)

    # downscale for antialiasing
    return img.resize((size, size), Image.LANCZOS)


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = {s: render(s) for s in sizes}

    ico_path = os.path.join(HERE, "icon.ico")
    imgs[256].save(ico_path, format="ICO",
                   sizes=[(s, s) for s in sizes])
    print("wrote", ico_path)

    for s in (256, 64, 32):
        p = os.path.join(HERE, f"icon_{s}.png")
        imgs[s].save(p)
        print("wrote", p)


if __name__ == "__main__":
    main()
