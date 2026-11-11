"""Benchmark for the Adwaita light redesign of the remislop-generator UI.

    python3 .auto/measure.py [--shots DIR] [--keep-going]

Renders the fixture pages, screenshots them with headless Chromium, collects
computed styles, scores them against the Adwaita (GNOME HIG) model and prints
`METRIC name=value` lines plus a DETAIL blob for diagnosis.
"""
import argparse
import html as htmlmod
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
BUILD = Path("/tmp/remislop-adw")
SHOTS = BUILD / "shots"

sys.path.insert(0, str(HERE))
import adwspec  # noqa: E402
import render as render_mod  # noqa: E402

CHROME = shutil.which("chromium") or shutil.which("chromium-browser") or "chromium"
VIEWPORT = (1280, 900)

# prefers-color-scheme emulation: 0 = dark, 1 = light
SCHEME_FLAGS = {
    "dark": ["--blink-settings=preferredColorScheme=0"],
    "light": ["--blink-settings=preferredColorScheme=1"],
}

CHROME_FLAGS = [
    "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
    "--force-device-scale-factor=1", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-background-networking", "--disable-sync",
    "--font-render-hinting=none", "--disable-lcd-text",
    f"--user-data-dir={BUILD}/chrome-profile",
    f"--window-size={VIEWPORT[0]},{VIEWPORT[1]}",
]


def run(cmd):
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd[:3])}...\n{proc.stderr[-2000:]}")
    return proc.stdout


def dump_page(path, scheme="dark"):
    out = run([CHROME, *CHROME_FLAGS, *SCHEME_FLAGS[scheme], "--dump-dom", path.as_uri()])
    m = re.search(r'data-adw="(.*?)"><head', out, re.S)
    if not m:
        raise RuntimeError(f"no metrics collected from {path.name}")
    return json.loads(htmlmod.unescape(m.group(1)))


def screenshot(path, png, scheme="dark"):
    run([CHROME, *CHROME_FLAGS, *SCHEME_FLAGS[scheme], f"--screenshot={png}", path.as_uri()])


def pixel_stats(png):
    raw = subprocess.run(
        ["magick", str(png), "-resize", "320x", "-depth", "8", "rgb:-"],
        capture_output=True, check=True,
    ).stdout
    n = len(raw) // 3
    if not n:
        return {"colors": 0, "std": 0.0, "accent_share": 0.0}
    colors, lum, accent = set(), [], 0
    for i in range(n):
        r, g, b = raw[3 * i], raw[3 * i + 1], raw[3 * i + 2]
        colors.add((r >> 2, g >> 2, b >> 2))
        lum.append(0.2126 * r + 0.7152 * g + 0.0722 * b)
        if b > 110 and b - r > 35 and b - g > 15:
            accent += 1
    return {
        "colors": len(colors),
        "std": round(statistics.pstdev(lum), 2),
        "accent_share": round(accent / n, 5),
    }


ROOT_BLOCK = re.compile(r":root\s*\{(.*?)\}", re.S)
CUSTOM_PROP = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;}]+)")


def template_tokens():
    """{"index.html": {"--window-bg": "#fafafa", ...}, ...}"""
    tokens = {}
    for path in sorted((REPO / "templates").glob("*.html")):
        found = {}
        for block in ROOT_BLOCK.findall(path.read_text()):
            for name, value in CUSTOM_PROP.findall(block):
                found[name.strip()] = " ".join(value.split()).lower()
        tokens[path.name] = found
    return tokens


def sync_score(tokens):
    files = list(tokens)
    maps = [tokens[f] for f in files]
    with_tokens = [m for m in maps if len(m) >= 4]
    if len(with_tokens) < len(files):
        return len(with_tokens) / len(files) * 0.34
    names = set().union(*maps)
    identical = sum(
        1 for name in names if len({m.get(name) for m in maps}) == 1 and maps[0].get(name)
    )
    return 0.5 + 0.5 * (identical / len(names) if names else 0.0)


def measure(shots_dir=None, scheme="dark"):
    started = time.time()
    adwspec.set_scheme(scheme)
    render_mod.render_all()
    SHOTS.mkdir(parents=True, exist_ok=True)
    if shots_dir:
        shots_dir = Path(shots_dir)
        shots_dir.mkdir(parents=True, exist_ok=True)

    pages, details = [], {}
    for spec in render_mod.PAGES:
        name = spec["name"]
        path = BUILD / f"{name}.html"
        png = SHOTS / f"{name}.png"
        data = dump_page(path, scheme)
        screenshot(path, png, scheme)
        pixel = pixel_stats(png)
        metrics, notes = adwspec.score_page(data, pixel)
        pages.append(metrics)
        details[name] = {
            "score": round(sum(metrics[k] * adwspec.WEIGHTS[k] for k in
                               ("palette", "accent", "type", "geometry",
                                "surfaces", "contrast", "pixels")), 2),
            "elements": len(data["elements"]),
            "pixel": pixel,
            "views": {"palette": round(metrics["palette"], 3),
                      "accent": round(metrics["accent"], 3),
                      "type": round(metrics["type"], 3),
                      "geometry": round(metrics["geometry"], 3),
                      "surfaces": round(metrics["surfaces"], 3),
                      "contrast": round(metrics["contrast"], 3),
                      "pixels": round(metrics["pixels"], 3)},
            "fam_fit": round(metrics["fam_fit"], 2),
            "size_fit": round(metrics["size_fit"], 2),
            "radius_fit": round(metrics["radius_fit"], 2),
            "space_fit": round(metrics["space_fit"], 2),
            "roles": metrics["roles_found"],
            "dE_mean": round(metrics["dE_mean"], 1),
            "contrast_min": metrics["contrast_min"],
            "worst_colors": metrics["worst_colors"],
            "notes": notes,
        }
        if shots_dir:
            shutil.copy2(png, shots_dir / png.name)

    tokens = template_tokens()
    sync = sync_score(tokens)
    total, avg = adwspec.combine(pages, sync)

    print(f"SCHEME {adwspec.ACTIVE_SCHEME}")
    print(f"METRIC adwaita={total:.2f}")
    for key in ("accent", "palette", "type", "geometry", "surfaces", "contrast", "pixels"):
        print(f"METRIC {key}={avg[key] * 100:.1f}")
    print(f"METRIC sync={sync * 100:.1f}")
    for i, spec in enumerate(render_mod.PAGES):
        print(f"METRIC adwaita_{spec['name']}={details[spec['name']]['score']:.1f}")
    print(f"METRIC dE_mean={statistics.mean(d['dE_mean'] for d in details.values()):.1f}")
    print(f"METRIC tokens={sum(len(m) for m in tokens.values())}")
    print(f"METRIC measure_seconds={time.time() - started:.1f}")
    print("DETAIL " + json.dumps({"tokens": tokens, "pages": details}, separators=(",", ":")))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots")
    ap.add_argument("--scheme", default=os.environ.get("ADW_SCHEME", "dark"),
                    choices=["light", "dark"])
    args = ap.parse_args()
    try:
        measure(args.shots, args.scheme)
    except Exception as exc:  # noqa: BLE001
        print(f"MEASURE_FAILED {exc}")
        sys.exit(1)
