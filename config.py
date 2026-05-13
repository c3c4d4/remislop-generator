import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    base_dir: Path = Path(__file__).resolve().parent
    output_dir: Path = Path(os.getenv("OUTPUT_DIRECTORY", Path(__file__).resolve().parent / "downloaded_images"))
    cache_dir: Path = Path(os.getenv("CACHE_DIRECTORY", Path(__file__).resolve().parent / ".cache" / "media"))
    database_path: Path = Path(os.getenv("DATABASE_PATH", Path(__file__).resolve().parent / "instance" / "jobs.sqlite3"))
    max_images: int = int(os.getenv("MAX_IMAGES", "80"))
    min_images: int = int(os.getenv("MIN_IMAGES", "8"))
    max_duration_seconds: int = int(os.getenv("MAX_DURATION_SECONDS", "3600"))
    default_frame_rate: int = int(os.getenv("DEFAULT_FRAME_RATE", "10"))
    cleanup_after_seconds: int = int(os.getenv("CLEANUP_AFTER_SECONDS", "86400"))
    gallery_timeout_seconds: int = int(os.getenv("GALLERY_TIMEOUT_SECONDS", "180"))
    youtube_timeout_seconds: int = int(os.getenv("YOUTUBE_TIMEOUT_SECONDS", "300"))
    ffmpeg_timeout_seconds: int = int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "300"))
    local_background_jobs: bool = _bool_env("LOCAL_BACKGROUND_JOBS", True)
    watermark_source_path: Path = Path(os.getenv("WATERMARK_SOURCE_PATH", Path(__file__).resolve().parent / "assets" / "watermarks" / "black.png"))
    watermark_size: int = int(os.getenv("WATERMARK_SIZE", "196"))
    watermark_margin: int = int(os.getenv("WATERMARK_MARGIN", "48"))
    max_output_mb: float = float(os.getenv("MAX_OUTPUT_MB", "9.5"))
    min_video_bitrate_kbps: int = int(os.getenv("MIN_VIDEO_BITRATE_KBPS", "45"))
    max_audio_bitrate_kbps: int = int(os.getenv("MAX_AUDIO_BITRATE_KBPS", "64"))


config = AppConfig()
