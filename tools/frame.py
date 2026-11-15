"""
Trim the empty studio background off a propforge render.

    python tools/frame.py docs/hero.png --margin 0.03

Needs Pillow (build-time only, propforge itself has no dependencies).
"""

import argparse
import sys

from PIL import Image, ImageChops

ap = argparse.ArgumentParser()
ap.add_argument("image")
ap.add_argument("--margin", type=float, default=0.03)
ap.add_argument("--threshold", type=int, default=6)
args = ap.parse_args()

img = Image.open(args.image).convert("RGB")
w, h = img.size

# background reference = median of the four corners
corners = [img.getpixel(p) for p in ((2, 2), (w - 3, 2), (2, h - 3), (w - 3, h - 3))]
bg = tuple(sorted(c[i] for c in corners)[len(corners) // 2] for i in range(3))
flat = Image.new("RGB", img.size, bg)
diff = ImageChops.difference(img, flat).convert("L")
mask = diff.point(lambda v: 255 if v > args.threshold else 0)
box = mask.getbbox()
if box is None:
    print("nothing to crop")
    sys.exit(0)

x0, y0, x1, y1 = box
pad = int(max(x1 - x0, y1 - y0) * args.margin)
box = (max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad))
trimmed = img.crop(box)
trimmed.save(args.image)
print("cropped %dx%d -> %dx%d (%s)" % (w, h, trimmed.width, trimmed.height, args.image))
