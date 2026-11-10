"""Adwaita (GNOME HIG, light) design-system model.

Everything here is data + pure functions: colours, colour science, and the
scoring rules used by measure.py. No I/O.
"""

# --------------------------------------------------------------------------
# Adwaita light palette (GNOME 47 / libadwaita 1.6)
# Source: Adwaita _colors-public.scss (named ramp + semantic tokens).
# Semantic tokens are resolved against their usual backdrop so they can be
# compared with rendered colours:
#   window_fg_color   rgba(0,0,0,.8) over #fafafa -> #323232
#   border_color      rgba(0,0,0,.15) over #ffffff -> #d9d9d9
#   card_shade_color  rgba(0,0,0,.07) over #ffffff -> #ededed
# --------------------------------------------------------------------------

PALETTE = {
    # semantic, light
    "window_bg_color": "#fafafa",
    "window_fg_color": "#323232",
    "view_bg_color": "#ffffff",
    "view_fg_color": "#333333",
    "headerbar_bg_color": "#ffffff",
    "headerbar_backdrop_color": "#fafafa",
    "headerbar_border_color": "#d9d9d9",
    "card_bg_color": "#ffffff",
    "card_fg_color": "#333333",
    "card_shade_color": "#ededed",
    "dialog_bg_color": "#fafafa",
    "popover_bg_color": "#ffffff",
    "sidebar_bg_color": "#ebebeb",
    "border_color": "#d9d9d9",
    "border_subtle": "#e6e6e6",
    "shade_color": "#ededed",
    "accent_bg_color": "#3584e4",
    "accent_fg_color": "#ffffff",
    "accent_color": "#1c71d8",
    "destructive_bg_color": "#e01b24",
    "destructive_fg_color": "#ffffff",
    "destructive_color": "#c01c28",
    "success_bg_color": "#2ec27e",
    "success_fg_color": "#ffffff",
    "success_color": "#26a269",
    "warning_bg_color": "#e5a50a",
    "warning_fg_color": "#333333",
    "warning_color": "#cd9309",
    "error_bg_color": "#e01b24",
    "error_fg_color": "#ffffff",
    "error_color": "#c01c28",
    # neutral ramp pieces that legitimately show up in widgets
    "dark_1": "#77767b",
    "dark_2": "#5e5c64",
    "dark_3": "#3d3846",
    "dark_4": "#241f31",
    "light_2": "#f6f5f4",
    "light_3": "#deddda",
    "light_4": "#c0bfbc",
    "light_5": "#9a9996",
    # state colours from the ramp (hover/active/visited of the semantic ones)
    "blue_2": "#62a0ea",
    "blue_4": "#1c71d8",
    "blue_5": "#1a5fb4",
    "green_3": "#33d17a",
    "red_2": "#ed333b",
    "red_5": "#a51d2d",
    "yellow_5": "#e5a50a",
    "orange_4": "#e66100",
    "purple_3": "#9141ac",
}

# Colours that carry a specific semantic role in the HIG.
WINDOW_BG = {"window_bg_color", "dialog_bg_color", "headerbar_backdrop_color"}
SURFACE_BG = {"view_bg_color", "card_bg_color", "headerbar_bg_color", "popover_bg_color"}
TEXT_PRIMARY = {"window_fg_color", "view_fg_color", "card_fg_color"}
TEXT_DIM = {"dark_1", "dark_2", "light_5", "dark_3"}
BORDER = {"border_color", "headerbar_border_color", "border_subtle", "light_3", "light_4",
           "shade_color", "card_shade_color"}
ACCENT_BG = {"accent_bg_color", "blue_2", "blue_4", "blue_5"}
ACCENT_FG = {"accent_color", "blue_4", "blue_5"}
DESTRUCTIVE = {"destructive_bg_color", "destructive_color", "error_bg_color", "error_color", "red_2", "red_5"}

# Adwaita type scale (px). 14.67 = 11pt at 96dpi, GTK's default body size.
TYPE_SCALE = [11, 13, 14.6667, 15, 17, 20, 24, 32]
TYPE_TOLERANCE = 0.7
FONT_OK = ("adwaita sans", "cantarell", "adwaita sans regular")

RADIUS_OK = [0, 3, 6, 9, 12, 18, 999]
RADIUS_TOLERANCE = 0.6
SPACING_GRID = 3  # paddings / gaps should sit on Adwaita's 3px rhythm
SPACING_ALLOW = [1, 2]  # 1-2px hairlines are fine too

TOL_PERFECT = 2.0  # deltaE within this is "the same colour"
TOL_FAR = 26.0  # deltaE at/after which a colour scores zero


# --------------------------------------------------------------------------
# colour parsing + colour science
# --------------------------------------------------------------------------

def parse_color(value):
    """('rgb(53, 132, 228)' | 'rgba(0,0,0,0.15)' | '#3584e4') -> (r,g,b,a)."""
    if not value:
        return None
    value = value.strip()
    if value.startswith("#"):
        h = value[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), 1.0)
    if value.startswith("rgb"):
        body = value[value.index("(") + 1: value.rindex(")")]
        parts = [p.strip() for p in body.replace("/", ",").split(",") if p.strip()]
        if len(parts) < 3:
            return None
        vals = []
        for part in parts[:4]:
            if part.endswith("%"):
                vals.append(float(part[:-1]) * 2.55)
            else:
                vals.append(float(part))
        while len(vals) < 4:
            vals.append(1.0)
        return (vals[0], vals[1], vals[2], vals[3])
    return None


def composite(fg, bg):
    """Alpha-composite fg over bg (both (r,g,b,a))."""
    if fg is None:
        return bg
    if bg is None:
        bg = (255.0, 255.0, 255.0, 1.0)
    a = fg[3]
    if a >= 0.999:
        return (fg[0], fg[1], fg[2], 1.0)
    out = tuple(fg[i] * a + bg[i] * (1 - a) for i in range(3))
    return (out[0], out[1], out[2], 1.0)


def to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb[:3])


def _srgb_to_linear(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb_to_lab(rgb):
    r, g, b = (_srgb_to_linear(rgb[0]), _srgb_to_linear(rgb[1]), _srgb_to_linear(rgb[2]))
    x = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047
    y = (r * 0.2126 + g * 0.7152 + b * 0.0722) / 1.0
    z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else (7.787 * t) + (16 / 116)

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


_PALETTE_LAB = {name: rgb_to_lab(parse_color(hexv)) for name, hexv in PALETTE.items()}


def nearest_token(rgb):
    """Return (token_name, deltaE) for the closest Adwaita colour."""
    lab = rgb_to_lab(rgb)
    best_name, best_d = None, 1e9
    for name, plab in _PALETTE_LAB.items():
        d = sum((lab[i] - plab[i]) ** 2 for i in range(3)) ** 0.5
        if d < best_d:
            best_name, best_d = name, d
    return best_name, best_d


def nearest_in(rgb, names):
    lab = rgb_to_lab(rgb)
    best_name, best_d = None, 1e9
    for name in names:
        plab = _PALETTE_LAB[name]
        d = sum((lab[i] - plab[i]) ** 2 for i in range(3)) ** 0.5
        if d < best_d:
            best_name, best_d = name, d
    return best_name, best_d


def palette_penalty(delta_e):
    """0 (perfect) .. 1 (alien colour)."""
    if delta_e <= TOL_PERFECT:
        return 0.0
    if delta_e >= TOL_FAR:
        return 1.0
    return (delta_e - TOL_PERFECT) / (TOL_FAR - TOL_PERFECT)


def relative_luminance(rgb):
    r, g, b = (_srgb_to_linear(rgb[0]), _srgb_to_linear(rgb[1]), _srgb_to_linear(rgb[2]))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg, bg):
    l1, l2 = relative_luminance(fg), relative_luminance(bg)
    if l1 < l2:
        l1, l2 = l2, l1
    return (l1 + 0.05) / (l2 + 0.05)


# --------------------------------------------------------------------------
# scoring
# --------------------------------------------------------------------------

WEIGHTS = {
    "accent": 18.0,
    "palette": 18.0,
    "type": 14.0,
    "geometry": 14.0,
    "surfaces": 14.0,
    "contrast": 9.0,
    "pixels": 5.0,
    "sync": 8.0,
}

MAX_DEPTH_TEXT = 3


def _frac(hits, total):
    return (hits / total) if total else 0.0


def score_page(page, pixel):
    """Score one rendered page dict -> (score, metrics, notes)."""
    notes = []
    els = page["elements"]
    root_bg = parse_color(page["canvas_bg"]) or (255, 255, 255, 1)

    # --- effective background of every element (composite down the tree) ---
    eff = {}
    for el in sorted(els, key=lambda e: e["depth"]):
        own = parse_color(el["bg"])
        if own and own[3] > 0.01:
            eff[el["idx"]] = composite(own, eff.get(el["parent"], root_bg))
        else:
            eff[el["idx"]] = eff.get(el["parent"], root_bg)

    usages = []  # (kind, rgb, weight, label)
    for el in els:
        base = eff.get(el["parent"], root_bg)
        own_bg = parse_color(el["bg"])
        if own_bg and own_bg[3] > 0.02:
            area = max(el["w"] * el["h"], 1.0)
            weight = 0.35 + min(area / 220000.0, 1.0)  # big surfaces matter more
            usages.append(("bg", composite(own_bg, base), weight, el["sel"]))
        bw = el.get("bw") or 0
        if bw > 0:
            bc = parse_color(el["bc"])
            if bc and bc[3] > 0.02:
                usages.append(("border", composite(bc, eff[el["idx"]]), 0.45, el["sel"]))
        if el.get("own_text"):
            tc = parse_color(el["c"])
            if tc:
                usages.append(("text", composite(tc, eff[el["idx"]]), 0.5, el["sel"]))

    # --- 1. palette distance ------------------------------------------------
    total_w = sum(u[2] for u in usages) or 1.0
    pen = 0.0
    worst = []
    for kind, rgb, weight, sel in usages:
        name, d = nearest_token(rgb)
        p = palette_penalty(d)
        pen += p * weight
        if p > 0.05:
            worst.append((round(d, 1), to_hex(rgb), kind, sel))
    d_e_mean = sum(
        nearest_token(u[1])[1] * u[2] for u in usages
    ) / total_w
    palette_score = 1.0 - (pen / total_w)
    worst.sort(reverse=True)

    # --- 2. accent + semantic roles ----------------------------------------
    roles = {}
    for kind, rgb, weight, sel in usages:
        name, d = nearest_token(rgb)
        if kind == "bg" and d <= TOL_PERFECT and name in ACCENT_BG:
            roles.setdefault("accent_surface", to_hex(rgb))
        if kind == "text" and d <= TOL_PERFECT and (name in ACCENT_FG):
            roles.setdefault("accent_text", to_hex(rgb))
        if kind == "bg" and d <= TOL_PERFECT and name in DESTRUCTIVE:
            roles.setdefault("destructive", to_hex(rgb))
        if kind == "text" and d <= TOL_PERFECT and name in DESTRUCTIVE:
            roles.setdefault("destructive_text", to_hex(rgb))
        if kind == "text" and d <= TOL_PERFECT and name in TEXT_DIM:
            roles.setdefault("dim_text", to_hex(rgb))
        if kind == "bg" and d <= TOL_PERFECT and name in SURFACE_BG:
            roles.setdefault("surface", to_hex(rgb))
        if kind == "bg" and d <= TOL_PERFECT and name in WINDOW_BG:
            roles.setdefault("window_bg", to_hex(rgb))
        if kind in ("border", "bg") and d <= TOL_PERFECT and name in BORDER:
            roles.setdefault("border", to_hex(rgb))

    accent_score = 0.0
    accent_score += 0.55 if "accent_surface" in roles else 0.0
    accent_score += 0.15 if "accent_text" in roles else 0.0
    accent_score += 0.15 if "dim_text" in roles else 0.0
    accent_score += 0.15 if (
        "destructive" in roles or "destructive_text" in roles
    ) else 0.0

    # --- 3. typography -----------------------------------------------------
    fams = [el["ff"].lower() for el in els if el.get("own_text")]
    fam_ok = _frac(sum(1 for f in fams if any(n in f for n in FONT_OK)), len(fams))
    if any("serif" in f and "sans" not in f for f in fams):
        fam_ok *= 0.5
        notes.append("serif text detected")
    sizes = [el["fs"] for el in els if el.get("font_size_applies")]
    size_ok = _frac(
        sum(1 for s in sizes if any(abs(s - t) <= TYPE_TOLERANCE for t in TYPE_SCALE)),
        len(sizes),
    )
    type_score = 0.45 * fam_ok + 0.55 * size_ok

    # --- 4. geometry: radius + spacing rhythm ------------------------------
    radii = [el["br"] for el in els if el["br"] > 0.01 and (el["bg"] or el.get("bw"))]
    radius_ok = _frac(
        sum(1 for r in radii if any(abs(r - t) <= RADIUS_TOLERANCE for t in RADIUS_OK)),
        len(radii),
    )
    spaces = []
    for el in els:
        for key in ("pt", "pr", "pb", "pl"):
            v = el.get(key) or 0
            if v > 0.5:
                spaces.append(v)
        for key in ("gap",):
            v = el.get(key) or 0
            if v > 0.5:
                spaces.append(v)
    space_ok = _frac(
        sum(
            1 for s in spaces
            if s in SPACING_ALLOW or abs(s % SPACING_GRID) <= 0.6
        ),
        len(spaces),
    )
    geometry_score = 0.5 * radius_ok + 0.5 * space_ok

    # --- 5. surfaces -------------------------------------------------------
    window_ok = nearest_token(root_bg)[1] <= TOL_PERFECT and nearest_token(root_bg)[0] in WINDOW_BG
    surf_score = 0.0
    surf_score += 0.35 if window_ok else 0.0
    surf_score += 0.30 if "surface" in roles else 0.0
    surf_score += 0.20 if "border" in roles else 0.0
    if any(1.0 <= (el.get("bw") or 0) <= 1.6 for el in els):
        surf_score += 0.15
    else:
        notes.append("no 1px hairline border")

    # --- 6. text contrast --------------------------------------------------
    contrasts = []
    for el in els:
        if not el.get("own_text"):
            continue
        tc = parse_color(el["c"])
        if not tc:
            continue
        fg = composite(tc, eff[el["idx"]])
        bg = eff[el["idx"]]
        big = el["fs"] >= 20 or (el["fs"] >= 18.5 and el.get("fw", 400) >= 700)
        need = 3.0 if big else 4.5
        contrasts.append((contrast_ratio(fg, bg) / need, el["sel"], el["fs"]))
    if contrasts:
        ratios = [c[0] for c in contrasts]
        failing = [c for c in contrasts if c[0] < 1.0]
        contrast_score = _frac(len(contrasts) - len(failing), len(contrasts))
        worst_ratio = min(
            contrast_ratio(
                composite(parse_color(el["c"]), eff[el["idx"]]), eff[el["idx"]]
            )
            for el in els if el.get("own_text")
        )
        if failing:
            notes.append(f"{len(failing)} low-contrast text run(s), worst {worst_ratio:.2f}:1")
    else:
        contrast_score = 0.0
        worst_ratio = 0.0
        notes.append("no text found")

    # --- 7. pixels ---------------------------------------------------------
    px_score = 1.0
    if pixel:
        if pixel.get("colors", 0) < 6:
            px_score *= 0.5
            notes.append("screenshot nearly flat")
        if pixel.get("accent_share", 0.0) < 0.0005:
            px_score *= 0.7
            notes.append("no accent pixels rendered")
        if pixel.get("std", 0) < 2:
            px_score *= 0.5
            notes.append("screenshot low variance")

    metrics = {
        "palette": palette_score,
        "accent": accent_score,
        "type": type_score,
        "geometry": geometry_score,
        "surfaces": surf_score,
        "contrast": contrast_score,
        "pixels": px_score,
        "dE_mean": d_e_mean,
        "fam_fit": fam_ok,
        "size_fit": size_ok,
        "radius_fit": radius_ok,
        "space_fit": space_ok,
        "roles": len(roles),
        "roles_found": sorted(roles),
        "contrast_min": round(worst_ratio, 2),
        "worst_colors": worst[:5],
    }
    return metrics, notes


def combine(pages, sync_score):
    """Weighted total of per-page metrics + cross-page token sync."""
    keys = ["palette", "accent", "type", "geometry", "surfaces", "contrast", "pixels"]
    avg = {
        k: sum(p[k] for p in pages) / len(pages) if pages else 0.0 for k in keys
    }
    avg["sync"] = sync_score
    total = sum(avg[k] * WEIGHTS[k] for k in WEIGHTS)
    return total, avg
