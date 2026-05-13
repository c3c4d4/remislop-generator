import re
from urllib.parse import urlparse


TIME_PATTERN = re.compile(r"^(?:(\d+):)?([0-5]?\d):([0-5]?\d)$")


def parse_time(time_str):
    if time_str is None:
        return None

    value = str(time_str).strip()
    if value.isdigit():
        return int(value)

    match = TIME_PATTERN.match(value)
    if not match:
        return None

    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes) * 60 + int(seconds)


def _has_http_url(value):
    parsed = urlparse((value or "").strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def split_source_urls(value):
    raw = (value or "").replace(",", "\n").splitlines()
    return [item.strip() for item in raw if item.strip()]


def validate_request(form, max_duration_seconds, has_upload=False):
    board_url = (form.get("board_urls") or form.get("board_url") or "").strip()
    youtube_url = (form.get("youtube_url") or form.get("audio_url") or "").strip()
    start_time = (form.get("start_time") or "").strip()
    end_time = (form.get("end_time") or "").strip()
    video_length = (form.get("video_length") or "").strip()

    errors = []
    source_urls = split_source_urls(board_url)
    if not has_upload and not source_urls:
        errors.append("Enter at least one image source URL or upload images.")
    for source_url in source_urls:
        if not _has_http_url(source_url):
            errors.append(f"Invalid image source URL: {source_url}")
            break
    if not _has_http_url(youtube_url):
        errors.append("Enter a valid YouTube or SoundCloud URL.")

    start_seconds = parse_time(start_time)
    length_seconds = parse_time(video_length) if video_length else None
    end_seconds = parse_time(end_time) if end_time else None

    if start_seconds is None:
        errors.append("Use seconds, MM:SS, or HH:MM:SS for start time.")
    elif length_seconds is not None:
        if length_seconds <= 0:
            errors.append("Video length must be greater than zero.")
        else:
            end_seconds = start_seconds + length_seconds
            end_time = str(end_seconds)
    elif end_seconds is None:
        errors.append("Enter a video length or end time.")
    elif end_seconds <= start_seconds:
        errors.append("End time must be greater than start time.")

    if start_seconds is not None and end_seconds is not None and end_seconds > start_seconds:
        duration_seconds = end_seconds - start_seconds
        if duration_seconds > max_duration_seconds:
            errors.append(f"Video length must be {max_duration_seconds} seconds or shorter.")
    else:
        duration_seconds = None

    frame_rate_raw = (form.get("frame_rate") or "").strip()
    if frame_rate_raw:
        try:
            frame_rate = int(frame_rate_raw)
        except ValueError:
            frame_rate = None
    else:
        frame_rate = None

    if frame_rate is not None and not 1 <= frame_rate <= 30:
        errors.append("Frame rate must be between 1 and 30.")

    return {
        "errors": errors,
        "data": {
            "board_url": board_url,
            "board_urls": source_urls,
            "youtube_url": youtube_url,
            "start_time": start_time,
            "end_time": end_time,
            "video_length": video_length,
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "duration_seconds": duration_seconds,
            "frame_rate": frame_rate,
        },
    }
