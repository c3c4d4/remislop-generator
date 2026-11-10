"""Render the three Flask templates with realistic fixture data.

Output goes to /tmp/remislop-adw/<page>.html (never into the repo), with a
collection script appended so `chromium --dump-dom` reports computed styles.

    python3 .auto/render.py            # render all fixture pages
"""
import hashlib
import subprocess
import sys
from pathlib import Path

import jinja2

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TEMPLATES = REPO / "templates"
BUILD = Path("/tmp/remislop-adw")
ASSETS = BUILD / "assets"
THUMBS = ASSETS / "thumbs"

STEPS = [
    ("queued", "Queued"),
    ("downloading_images", "Downloading images"),
    ("review", "Review images"),
    ("downloading_audio", "Extracting audio"),
    ("rendering", "Rendering frames"),
    ("muxing", "Adding audio"),
    ("complete", "Ready"),
]

JOBS = [
    {
        "id": "7addd7829edc",
        "name": "crunchy-dizzy-upload",
        "status": "complete",
        "created_at": "2026-11-04T19:19:49+00:00",
        "board_url": "upload://local",
    },
    {
        "id": "3fa9c1e07b22",
        "name": "velvet-numb-board",
        "status": "review",
        "created_at": "2026-11-10T12:04:11+00:00",
        "board_url": "https://www.pinterest.com/softpoofie/a3sth3tics/animecore/\r\n"
                     "https://www.are.na/indie-web/collections",
    },
    {
        "id": "9f8e7d6c5b4a",
        "name": "chrome-soft-fog",
        "status": "failed",
        "created_at": "2026-11-10T09:41:02+00:00",
        "board_url": "https://br.pinterest.com/softpoofie/room-inspo/",
    },
]

THUMB_COUNT = 14


def checksum(i):
    return hashlib.sha1(f"fixture-{i}".encode()).hexdigest()[:16]


def step_payload(active_step):
    active = next((i for i, (sid, _) in enumerate(STEPS) if sid == active_step), 0)
    return [
        {
            "id": sid,
            "label": label,
            "state": "done" if i < active else "active" if i == active else "waiting",
        }
        for i, (sid, label) in enumerate(STEPS)
    ]


def build_assets():
    if THUMBS.exists() and len(list(THUMBS.glob("*.jpg"))) == THUMB_COUNT and (ASSETS / "clip.mp4").exists():
        return
    THUMBS.mkdir(parents=True, exist_ok=True)
    palettes = ["#3d3846", "#3f6a8f", "#8f5a3f", "#4a7a52", "#7a4a6a", "#6a6a3f",
                "#2f4f4f", "#7a3f3f", "#54456a", "#3f7a6a", "#8f7a3f", "#4a4a6a",
                "#6a3f4a", "#3f5a7a"]
    for i in range(THUMB_COUNT):
        base = palettes[i % len(palettes)]
        out = THUMBS / f"{checksum(i)}.jpg"
        subprocess.run(
            ["magick", "-size", "360x360", f"gradient:{base}-#f0eee9",
             "-quality", "82", str(out)],
            check=True, capture_output=True,
        )
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2",
         "-pix_fmt", "yuv420p", str(ASSETS / "clip.mp4")],
        check=True, capture_output=True,
    )


def make_url_for():
    def url_for(endpoint, **kw):
        if endpoint == "thumb":
            return (THUMBS / f"{kw['checksum']}.jpg").as_uri()
        if endpoint == "index":
            return (BUILD / "index.html").as_uri()
        if endpoint == "status":
            return (BUILD / "status_done.html").as_uri()
        return "#"

    return url_for


GALLERY_JOB = {
    "id": "3fa9c1e07b22",
    "name": "velvet-numb-board",
    "status": "review",
    "progress": 25,
    "board_url": "https://www.pinterest.com/softpoofie/a3sth3tics/animecore/",
    "created_at": "2026-11-10T12:04:11+00:00",
}

GALLERY_IMAGES = [
    {"checksum": checksum(i), "filename": f"pin-{1000 + i * 37}.jpg"} for i in range(THUMB_COUNT)
]

STATUS_DONE = {
    "id": "7addd7829edc",
    "name": "crunchy-dizzy-upload",
    "status": "complete",
    "progress": 100,
    "board_url": "upload://local",
    "error": "",
    "saved": 0,
    "video_url": (ASSETS / "clip.mp4").as_uri(),
    "download_url": "#download",
    "open_url": "#open",
    "save_url": "#save",
}

STATUS_RUNNING = dict(
    STATUS_DONE,
    status="running",
    progress=45,
    video_url=None,
    download_url=None,
    open_url=None,
    save_url=None,
)

STATUS_FAILED = dict(
    STATUS_DONE,
    status="failed",
    progress=25,
    video_url=None,
    download_url=None,
    open_url=None,
    save_url=None,
    error="Only 3 selectable images remain after blocklist filtering.",
)

FILLED_VALUES = {
    "board_urls": "https://www.pinterest.com/softpoofie/a3sth3tics/animecore/",
    "youtube_url": "https://www.youtube.com/watch?v=XYrQC-jWMFM",
    "start_time": "0:30",
    "video_length": "2:30",
    "end_time": "3:00",
}

TRIM_SETUP = """
document.getElementById('trim').hidden = false;
document.getElementById('youtube-title').textContent = 'Aphex Twin — Windowlicker';
document.getElementById('youtube-duration').textContent = '6:07';
const rs = document.getElementById('range-start'), re = document.getElementById('range-end');
rs.max = 367; re.max = 367; rs.value = 30; re.value = 180;
updateRangeFromInputs('end');
"""

PAGES = [
    {"name": "index", "template": "index.html",
     "ctx": {"errors": [], "values": {}, "jobs": JOBS}, "setup": ""},
    {"name": "index_trim", "template": "index.html",
     "ctx": {"errors": [], "values": FILLED_VALUES, "jobs": JOBS}, "setup": TRIM_SETUP},
    {"name": "index_errors", "template": "index.html",
     "ctx": {"errors": ["Audio source is required.",
                        "Start time must be earlier than end time."],
             "values": FILLED_VALUES, "jobs": JOBS}, "setup": TRIM_SETUP},
    {"name": "gallery", "template": "gallery.html",
     "ctx": {"job": GALLERY_JOB, "images": GALLERY_IMAGES}, "setup": ""},
    {"name": "status_running", "template": "status.html",
     "ctx": {"job": STATUS_RUNNING, "steps": step_payload("rendering")}, "setup": ""},
    {"name": "status_done", "template": "status.html",
     "ctx": {"job": STATUS_DONE, "steps": step_payload("complete")}, "setup": ""},
    {"name": "status_failed", "template": "status.html",
     "ctx": {"job": STATUS_FAILED, "steps": step_payload("review")}, "setup": ""},
]


def render_all():
    BUILD.mkdir(parents=True, exist_ok=True)
    build_assets()
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True
    )
    env.globals["url_for"] = make_url_for()
    collect = (HERE / "collect.js").read_text()
    written = []
    for page in PAGES:
        html = env.get_template(page["template"]).render(**page["ctx"])
        inject = (
            "<script>try{%s}catch(e){console.error(e)}</script>"
            "<script>%s</script>" % (page["setup"], collect)
        )
        if "</body>" in html:
            html = html.replace("</body>", inject + "</body>")
        else:
            html += inject
        path = BUILD / f"{page['name']}.html"
        path.write_text(html)
        written.append(str(path))
    return written


if __name__ == "__main__":
    for path in render_all():
        print(path)
    sys.exit(0)
