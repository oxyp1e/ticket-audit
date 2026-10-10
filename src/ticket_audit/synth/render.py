"""Renders ticket fields as images: a hand-filled haul ticket, a thermal scale ticket, and a phone-photo effect.

Fonts are OFL-licensed and ship in assets/fonts, so rendering is identical on any machine.
"""
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ticket_audit.synth.world import CARRIER

FONTS = Path(__file__).resolve().parents[3] / "assets" / "fonts"
INK_PRINT = (25, 25, 30)
INK_RED = (190, 30, 35)
INK_PEN = (20, 40, 120)
INK_THERMAL = (40, 40, 45)

_cache: dict[tuple, ImageFont.FreeTypeFont] = {}


def _font(name: str, size: int, var: str | None = None) -> ImageFont.FreeTypeFont:
    key = (name, size, var)
    if key not in _cache:
        f = ImageFont.truetype(str(FONTS / name), size)
        if var:
            f.set_variation_by_name(var)
        _cache[key] = f
    return _cache[key]


def _label(size):
    return _font("RobotoCondensed-VF.ttf", size, "Regular")


def _label_b(size):
    return _font("RobotoCondensed-VF.ttf", size, "Bold")


def _hand(size):
    return _font("Caveat.ttf", size, "Regular")


def _hand_text(d: ImageDraw.ImageDraw, xy, text: str, rng: random.Random, size: int = 46) -> None:
    """Handwriting: slight baseline jitter and per-word size variation."""
    x, y = xy
    for word in text.split(" "):
        f = _hand(size + rng.randint(-3, 3))
        d.text((x, y + rng.randint(-3, 3)), word, font=f, fill=INK_PEN)
        x += d.textlength(word + " ", font=f)


def _messy_number(im: Image.Image, xy, text: str, rng: random.Random) -> None:
    """A number written over a different number, then smeared by a thumb: only the ink moves."""
    digits = [i for i, c in enumerate(text) if c.isdigit()]
    under = list(text)
    for i in rng.sample(digits, 2):
        under[i] = str((int(text[i]) + rng.randint(2, 7)) % 10)
    ink = Image.new("L", (260, 90), 0)
    d = ImageDraw.Draw(ink)
    d.text((14, 10), "".join(under), font=_hand(50), fill=200)
    d.text((10, 6), text, font=_hand(48), fill=255)
    # Thumb smear: faded copies dragged sideways and slightly down, strongest near the stroke.
    smear = ink.copy()
    for step in range(1, 9):
        shifted = Image.new("L", ink.size, 0)
        shifted.paste(ink, (step * 3, step // 3))
        smear = Image.fromarray(np.maximum(np.asarray(smear), (np.asarray(shifted) * (0.55 - step * 0.05)).astype("uint8")))
    smear = smear.filter(ImageFilter.GaussianBlur(1.6))
    x, y = int(xy[0]) - 10, int(xy[1]) - 6
    im.paste(Image.new("RGB", ink.size, INK_PEN), (x, y), smear)


def _signature(im: Image.Image, box, name: str, rng: random.Random) -> None:
    """The signer's name in a fast, slanted, compressed hand, plus an underline flourish."""
    x0, y0, x1, y1 = box
    parts = name.replace(".", "").split()
    text = f"{parts[0][0]} {parts[-1]}"
    f = _font("Caveat.ttf", int((y1 - y0) * 0.95), "Bold")
    tmp = Image.new("L", (int(x1 - x0) * 2, int(y1 - y0) * 2), 0)
    td = ImageDraw.Draw(tmp)
    td.text((20, 0), text, font=f, fill=255)
    tw = int(td.textlength(text, font=f)) + 40
    td.line([(30, tmp.height * 0.62), (tw * rng.uniform(0.8, 1.0), tmp.height * 0.55)], fill=255, width=4)
    shear = rng.uniform(0.25, 0.4)
    tmp = tmp.transform(tmp.size, Image.AFFINE, (1, shear, -shear * tmp.height * 0.3, 0, 1, 0), Image.BICUBIC)
    w = min(tmp.width, tw + 40)
    tmp = tmp.crop((0, 0, w, tmp.height)).resize((int(w * 0.72), tmp.height // 2 + 10))
    tmp = tmp.rotate(rng.uniform(-6, 3), expand=True, resample=Image.BICUBIC)
    im.paste(Image.new("RGB", tmp.size, INK_PEN), (int(x0), int(y0) - 10), tmp)


HAUL_ROWS = [
    [("DATE", "date", 0.45), ("DISPATCH / LOAD No.", "dispatch_no", 0.55)],
    [("UNIT No.", "unit", 0.25), ("TRAILER No.", "trailer", 0.3), ("DRIVER", "driver", 0.45)],
    [("CUSTOMER (BILL TO)", "customer", 1.0)],
    [("PO No.", "po", 0.45), ("AFE / COST CODE", "afe", 0.55)],
    [("ORIGIN (PIT / TERMINAL)", "origin", 0.6), ("SCALE TICKET No.", "scale_ticket_no", 0.4)],
    [("DESTINATION LEASE / WELL", "lease", 0.6), ("LSD", "lsd", 0.4)],
    [("PRODUCT", "product", 0.6), ("NET WEIGHT (t)", "net_t", 0.4)],
    [("ARRIVE SITE", "arrive", 0.33), ("DEPART SITE", "depart", 0.33), ("STANDBY (h)", "standby_h", 0.34)],
]


def haul_ticket(f: dict[str, str], illegible: list[str], rng: random.Random) -> Image.Image:
    W, H = 1100, 1500
    im = Image.new("RGB", (W, H), (250, 249, 244))
    d = ImageDraw.Draw(im)
    d.text((50, 40), CARRIER.upper(), font=_label_b(46), fill=INK_PRINT)
    d.text((50, 96), "FRAC SAND HAUL TICKET", font=_label_b(30), fill=INK_PRINT)
    d.text((50, 134), "SYNTHETIC DOCUMENT - FOR TESTING ONLY", font=_label(20), fill=INK_RED)
    d.text((W - 330, 50), "No.", font=_label_b(30), fill=INK_RED)
    d.text((W - 270, 44), f["ticket_no"], font=_font("CourierPrime-Bold.ttf", 40), fill=INK_RED)

    x0, x1, y, rh = 50, W - 50, 190, 110
    for row in HAUL_ROWS:
        x = x0
        for label, key, frac in row:
            w = (x1 - x0) * frac
            d.rectangle([x, y, x + w, y + rh], outline=INK_PRINT, width=2)
            d.text((x + 10, y + 6), label, font=_label(20), fill=INK_PRINT)
            if f[key] and key in illegible:
                _messy_number(im, (x + 18, y + 38), f[key], rng)
            elif f[key]:
                _hand_text(d, (x + 18, y + 40), f[key], rng)
            x += w
        y += rh

    d.rectangle([x0, y, x1, y + 130], outline=INK_PRINT, width=2)
    d.text((x0 + 10, y + 6), "REMARKS", font=_label(20), fill=INK_PRINT)
    y += 150
    d.text((x0, y), "RECEIVED IN GOOD ORDER", font=_label_b(22), fill=INK_PRINT)
    y += 40
    half = (x1 - x0) / 2
    d.rectangle([x0, y, x0 + half, y + rh], outline=INK_PRINT, width=2)
    d.text((x0 + 10, y + 6), "RECEIVER - PRINT NAME", font=_label(20), fill=INK_PRINT)
    if f["receiver_name"]:
        _hand_text(d, (x0 + 18, y + 40), f["receiver_name"], rng)
    d.rectangle([x0 + half, y, x1, y + rh], outline=INK_PRINT, width=2)
    d.text((x0 + half + 10, y + 6), "RECEIVER - SIGNATURE", font=_label(20), fill=INK_PRINT)
    if f["receiver_signature"]:
        _signature(im, (x0 + half + 20, y + 30, x1 - 20, y + rh - 5), f["receiver_signature"], rng)
    d.text((x0, H - 50), "WHITE - OFFICE     YELLOW - CUSTOMER     PINK - DRIVER", font=_label(18), fill=INK_PRINT)
    return im


def scale_ticket(f: dict[str, str], rng: random.Random) -> Image.Image:
    """Thermal receipt printed by the pit scale."""
    W, H = 620, 1180
    im = Image.new("RGB", (W, H), (246, 246, 243))
    d = ImageDraw.Draw(im)
    reg, bold = _font("CourierPrime-Regular.ttf", 28), _font("CourierPrime-Bold.ttf", 30)
    rule = ("-" * 30, reg, False)
    net_t = int(f["net_kg"].replace(",", "")) / 1000
    lines = [
        (f["pit"].upper(), bold, True),
        (f["scale_house"], reg, True),
        ("SYNTHETIC - TEST ONLY", reg, True),
        rule,
        (f"TICKET #   {f['scale_ticket_no']}", bold, False),
        (f"DATE       {f['date']}", reg, False),
        (f"TIME IN    {f['time_in']}", reg, False),
        (f"TIME OUT   {f['time_out']}", reg, False),
        rule,
        (f"CARRIER    {f['carrier']}", reg, False),
        (f"UNIT       {f['unit']}", reg, False),
        (f"TRAILER    {f['trailer']}", reg, False),
        (f"PRODUCT    {f['product']}", reg, False),
        rule,
        (f"GROSS   {f['gross_kg']:>10} kg", bold, False),
        (f"TARE    {f['tare_kg']:>10} kg", bold, False),
        (f"NET     {f['net_kg']:>10} kg", bold, False),
        (f"NET     {net_t:>10.2f} t", reg, False),
        rule,
        (f"WEIGHMASTER  {f['weighmaster']}", reg, False),
        ("", reg, False),
        ("DRIVER SIGNATURE", reg, False),
    ]
    y = 50
    for text, fnt, center in lines:
        x = (W - d.textlength(text, font=fnt)) / 2 if center else 40
        d.text((x, y), text, font=fnt, fill=INK_THERMAL)
        y += 44
    _signature(im, (40, y, W - 120, y + 70), f["driver_signature"], rng)
    return im


def phone_photo(doc: Image.Image, rng: random.Random, bg_tone=(70, 62, 55)) -> Image.Image:
    """Place the document on a surface, warp the perspective, add light falloff, blur and noise."""
    nrng = np.random.default_rng(rng.randint(0, 2**32 - 1))
    w, h = doc.size
    cw, ch = int(w * 1.35), int(h * 1.25)
    canvas = Image.fromarray(np.clip(nrng.normal(0, 9, (ch, cw, 3)) + np.array(bg_tone), 0, 255).astype("uint8"))
    ox, oy = (cw - w) // 2, (ch - h) // 2
    canvas.paste(doc, (ox, oy))

    # Perspective: move each corner a little, as if shot hand-held at a slight angle.
    src = [(ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h)]
    dst = [(x + rng.uniform(-0.05, 0.05) * w, y + rng.uniform(-0.05, 0.05) * w) for x, y in src]
    A, B = [], []
    for (xs, ys), (xd, yd) in zip(src, dst):
        A += [[xd, yd, 1, 0, 0, 0, -xs * xd, -xs * yd], [0, 0, 0, xd, yd, 1, -ys * xd, -ys * yd]]
        B += [xs, ys]
    coeffs = np.linalg.solve(np.array(A), np.array(B))
    im = canvas.transform(canvas.size, Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    im = im.rotate(rng.uniform(-4, 4), resample=Image.BICUBIC, fillcolor=bg_tone)

    # Uneven light: a diagonal gradient plus a soft shadow band (a hand or the phone).
    arr = np.asarray(im).astype(float)
    yy, xx = np.mgrid[0:arr.shape[0], 0:arr.shape[1]]
    light = 0.78 + 0.25 * (xx / arr.shape[1]) * (1 - 0.4 * yy / arr.shape[0])
    band = np.exp(-(((xx - arr.shape[1] * rng.uniform(0.2, 0.8)) / (arr.shape[1] * 0.12)) ** 2))
    edge = 1 / (1 + np.exp(-(yy - arr.shape[0] * rng.uniform(0.4, 0.7)) / (arr.shape[0] * 0.04)))
    light *= 1 - 0.28 * band * edge
    arr = arr * light[..., None] + nrng.normal(0, 4, arr.shape)
    im = Image.fromarray(np.clip(arr, 0, 255).astype("uint8")).filter(ImageFilter.GaussianBlur(rng.uniform(0.8, 1.4)))
    return im.resize((int(im.width * 0.7), int(im.height * 0.7)), Image.LANCZOS)


def render_document(kind: str, fields: dict[str, str], illegible: list[str], seed: str, path: Path) -> None:
    rng = random.Random(seed)
    if kind == "haul":
        img = phone_photo(haul_ticket(fields, illegible, rng), rng)
    else:
        img = phone_photo(scale_ticket(fields, rng), rng, bg_tone=(45, 48, 52))
    img.save(path, quality=rng.randint(62, 75))


def render_job(args: tuple) -> None:
    """Picklable entry point for worker processes."""
    render_document(*args)
