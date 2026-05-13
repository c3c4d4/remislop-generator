import random


ADJECTIVES = [
    "acid",
    "bashful",
    "blurry",
    "cosmic",
    "crunchy",
    "dizzy",
    "feral",
    "glossy",
    "haunted",
    "itchy",
    "loopy",
    "melty",
    "noisy",
    "pixelated",
    "rubbery",
    "sleepy",
    "sparkly",
    "squiggly",
    "sticky",
    "wobbly",
]

SUBJECTS = [
    "antenna",
    "boombox",
    "cursor",
    "daydream",
    "elevator",
    "firewall",
    "jukebox",
    "keyboard",
    "loading-screen",
    "modem",
    "moonwalk",
    "playlist",
    "screensaver",
    "signal",
    "slideshow",
    "thumbnail",
    "tunnel",
    "upload",
    "vortex",
    "wallpaper",
]


def generate_job_name(seed=None):
    rng = random.Random(seed)
    first, second = rng.sample(ADJECTIVES, 2)
    subject = rng.choice(SUBJECTS)
    return f"{first}-{second}-{subject}"
