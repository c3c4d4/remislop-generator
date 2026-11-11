import hashlib
import os
import random
import requests
import shutil
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
from urllib.parse import urlparse, urlunparse

from PIL import Image, ImageEnhance

from celery_config import celery_app, logger
from config import config
from jobs import blocked_checksums, get_job, job_dir, output_path_for, update_job
from validation import parse_time, split_source_urls


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")
DEFAULT_POST_SETTINGS = {
    "brightness": 1.0,
    "contrast": 1.0,
    "saturation": 1.0,
    "sharpness": 1.0,
    "pixelate": 0,
}


def media_key(*parts):
    digest = hashlib.sha256()
    for part in parts:
        digest.update(str(part).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()[:24]


def file_checksum(path):
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail_job(job_id, message):
    logger.error("[%s] %s", job_id, message)
    update_job(job_id, status="failed", error=message)
    raise RuntimeError(message)


def run_command(job_id, command, timeout, failure_label):
    logger.info("[%s] running: %s", job_id, " ".join(command))
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        fail_job(job_id, f"{failure_label} timed out after {timeout} seconds.")
    except Exception as exc:
        fail_job(job_id, f"{failure_label} failed to start: {exc}")

    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "").strip()
        fail_job(job_id, f"{failure_label} failed: {stderr[-1200:]}")

    return result


def run_soft_command(job_id, command, timeout, failure_label):
    logger.info("[%s] running: %s", job_id, " ".join(command))
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        fail_job(job_id, f"{failure_label} timed out after {timeout} seconds.")
    except Exception as exc:
        fail_job(job_id, f"{failure_label} failed to start: {exc}")


def ensure_dir(path):
    Path(path).mkdir(parents=True, exist_ok=True)


def yt_dlp_base_command():
    return [sys.executable, "-m", "yt_dlp", "--remote-components", "ejs:github"]


def find_images(directory):
    return sorted(
        path
        for path in Path(directory).rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


def clamp_float(value, minimum, maximum, default):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def clamp_int(value, minimum, maximum, default):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def normalize_post_settings(values=None):
    values = values or {}
    return {
        "brightness": clamp_float(values.get("brightness"), 0.6, 1.4, DEFAULT_POST_SETTINGS["brightness"]),
        "contrast": clamp_float(values.get("contrast"), 0.6, 1.6, DEFAULT_POST_SETTINGS["contrast"]),
        "saturation": clamp_float(values.get("saturation"), 0.0, 1.8, DEFAULT_POST_SETTINGS["saturation"]),
        "sharpness": clamp_float(values.get("sharpness"), 0.0, 2.0, DEFAULT_POST_SETTINGS["sharpness"]),
        "pixelate": clamp_int(values.get("pixelate"), 0, 12, DEFAULT_POST_SETTINGS["pixelate"]),
    }


def post_settings_from_form(form):
    return normalize_post_settings(
        {
            "brightness": form.get("post_brightness"),
            "contrast": form.get("post_contrast"),
            "saturation": form.get("post_saturation"),
            "sharpness": form.get("post_sharpness"),
            "pixelate": form.get("post_pixelate"),
        }
    )


def apply_post_effects(frame, settings):
    settings = normalize_post_settings(settings)

    if settings["brightness"] != 1.0:
        frame = ImageEnhance.Brightness(frame).enhance(settings["brightness"])
    if settings["contrast"] != 1.0:
        frame = ImageEnhance.Contrast(frame).enhance(settings["contrast"])
    if settings["saturation"] != 1.0:
        frame = ImageEnhance.Color(frame).enhance(settings["saturation"])
    if settings["sharpness"] != 1.0:
        frame = ImageEnhance.Sharpness(frame).enhance(settings["sharpness"])
    if settings["pixelate"] > 1:
        width, height = frame.size
        factor = settings["pixelate"]
        small_size = (max(1, width // factor), max(1, height // factor))
        frame = frame.resize(small_size, Image.Resampling.NEAREST).resize((width, height), Image.Resampling.NEAREST)

    return frame


def normalize_source_url(url):
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith(".pinterest.com") and host != "www.pinterest.com":
        parsed = parsed._replace(netloc="www.pinterest.com")
    return urlunparse(parsed)


def sample_images(paths, max_images):
    if len(paths) <= max_images:
        return paths
    if max_images <= 1:
        return paths[:1]
    step = (len(paths) - 1) / (max_images - 1)
    return [paths[round(idx * step)] for idx in range(max_images)]


def shuffled_images(paths, seed=None):
    images = list(paths)
    rng = random.Random(seed)
    rng.shuffle(images)
    return images


def copy_tree_contents(source, target):
    ensure_dir(target)
    for item in Path(source).iterdir():
        destination = Path(target) / item.name
        if item.is_dir():
            copy_tree_contents(item, destination)
        else:
            shutil.copy2(item, destination)


def download_arena_images(job_id, source_url, temp_dir):
    parsed = urlparse(source_url)
    path_parts = [p for p in parsed.path.split("/") if p]
    if not path_parts:
        return [(source_url, "Invalid are.na URL format")]

    channel_slug = path_parts[-2] if path_parts[-1] == "contents" else path_parts[-1]
    api_url = f"https://api.are.na/v2/channels/{channel_slug}/contents"
    per_page = 100
    page = 1
    
    downloaded_count = 0
    failures = []
    
    session = requests.Session()
    session.headers.update({"User-Agent": "Remislop-Generator/1.0"})
    
    while downloaded_count < config.max_images:
        try:
            resp = session.get(api_url, params={"per": per_page, "page": page, "direction": "desc"}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            return [(source_url, f"Are.na API error: {exc}")]
            
        contents = data.get("contents", [])
        if not contents:
            break
            
        for item in contents:
            if downloaded_count >= config.max_images:
                break
            if item.get("class") == "Image" and "image" in item and "original" in item["image"]:
                img_url = item["image"]["original"]["url"]
                base_url = img_url.lower().split("?")[0]
                ext = ".jpg"
                if base_url.endswith(".png"):
                    ext = ".png"
                elif base_url.endswith(".webp"):
                    ext = ".webp"
                elif base_url.endswith(".jpeg"):
                    ext = ".jpeg"
                    
                filename = f"arena_{item['id']}{ext}"
                filepath = Path(temp_dir) / filename
                
                try:
                    img_resp = session.get(img_url, timeout=15)
                    img_resp.raise_for_status()
                    with open(filepath, "wb") as f:
                        f.write(img_resp.content)
                    downloaded_count += 1
                except Exception as exc:
                    logger.warning("[%s] Failed to download are.na image block %s: %s", job_id, item.get("id"), exc)
                    failures.append((img_url, str(exc)))
                    
        if len(contents) < per_page:
            break
        page += 1
        
    return failures if downloaded_count == 0 else []


def download_source_images(job_id, source_url, target_dir):
    source_url = normalize_source_url(source_url)
    source_cache_dir = config.cache_dir / "images" / media_key(source_url, config.max_images)

    if source_cache_dir.exists() and find_images(source_cache_dir):
        copy_tree_contents(source_cache_dir, target_dir)
        return []

    temp_dir = target_dir / "_incoming" / media_key(source_url)
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    ensure_dir(temp_dir)

    parsed = urlparse(source_url)
    host = parsed.netloc.lower()

    if host in ("are.na", "www.are.na", "api.are.na"):
        failures = download_arena_images(job_id, source_url, temp_dir)
        result_has_error = bool(failures)
        result_error_text = failures[-1][1] if failures else ""
    else:
        command = [
            sys.executable,
            "-m",
            "gallery_dl",
            "--range",
            f"1-{config.max_images}",
            "--dest",
            str(temp_dir),
            source_url,
        ]
        result = run_soft_command(job_id, command, config.gallery_timeout_seconds, "Image download")
        result_has_error = result and result.returncode != 0
        result_error_text = (result.stderr or result.stdout or "").strip() if result else ""

    copy_tree_contents(temp_dir, target_dir)

    downloaded = find_images(temp_dir)
    if downloaded:
        if source_cache_dir.exists():
            shutil.rmtree(source_cache_dir)
        copy_tree_contents(temp_dir, source_cache_dir)

    shutil.rmtree(temp_dir, ignore_errors=True)
    if result_has_error:
        return [(source_url, result_error_text)]
    return []


def download_images(job_id, board_url, images_dir):
    update_job(job_id, status="running", step="downloading_images", progress=10)
    if board_url.startswith("upload://"):
        images = find_images(images_dir)
        if not images:
            fail_job(job_id, "No uploaded images were found.")
        return sample_images(images, config.max_images)

    source_urls = [normalize_source_url(url) for url in split_source_urls(board_url)]

    if images_dir.exists():
        shutil.rmtree(images_dir)
    ensure_dir(images_dir)

    failures = []
    for source_url in source_urls:
        failures.extend(download_source_images(job_id, source_url, images_dir))

    images = find_images(images_dir)
    if failures and len(images) < config.min_images:
        fail_job(
            job_id,
            f"Image download failed after {len(images)} usable images. "
            f"Need at least {config.min_images}. {failures[-1][1][-1000:]}",
        )
    if len(images) < config.min_images:
        fail_job(job_id, f"Only {len(images)} images were downloaded. Need at least {config.min_images}.")
    if failures:
        logger.warning(
            "[%s] image download had partial failures, continuing with %s images: %s",
            job_id,
            len(images),
            failures[-1][1][-800:],
        )

    return images


def image_entries(images):
    blocked = blocked_checksums()
    entries = []
    seen = set()
    for path in images:
        checksum = file_checksum(path)
        if checksum in seen or checksum in blocked:
            continue
        seen.add(checksum)
        entries.append(
            {
                "checksum": checksum,
                "path": str(path),
                "filename": Path(path).name,
            }
        )
    return entries


def thumbnail_path_for(job_id, checksum):
    return job_dir(job_id) / "thumbs" / f"{checksum}.jpg"


def ensure_thumbnail(job_id, image_path, checksum, size=(360, 360)):
    thumb_path = thumbnail_path_for(job_id, checksum)
    if thumb_path.exists():
        return thumb_path
    ensure_dir(thumb_path.parent)
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        img.thumbnail(size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGB", size, (12, 12, 12))
        left = (size[0] - img.width) // 2
        top = (size[1] - img.height) // 2
        canvas.paste(img, (left, top))
        canvas.save(thumb_path, format="JPEG", quality=82, optimize=True)
    return thumb_path


def selected_image_paths(job):
    details = job.get("details") or {}
    selected = details.get("selected_images") or details.get("images") or []
    return [Path(item["path"]) for item in selected if Path(item["path"]).exists()]


def prepare_gallery(job_id):
    job = get_job(job_id)
    if not job:
        raise RuntimeError(f"Job not found: {job_id}")
    root = job_dir(job_id)
    images_dir = root / "images"
    try:
        ensure_dir(root)
        images = download_images(job_id, job["board_url"], images_dir)
        entries = image_entries(images)
        if len(entries) < config.min_images:
            fail_job(job_id, f"Only {len(entries)} selectable images remain after blocklist filtering.")
        update_job(
            job_id,
            status="review",
            step="review",
            progress=25,
            error="",
            details={"images": entries, "image_count": len(entries)},
        )
        return entries
    except Exception as exc:
        if get_job(job_id) and get_job(job_id)["status"] != "failed":
            update_job(job_id, status="failed", error=str(exc))
        raise


def download_audio(job_id, youtube_url, start_time, end_time, audio_path):
    update_job(job_id, status="running", step="downloading_audio", progress=35)
    start_seconds = parse_time(start_time)
    end_seconds = parse_time(end_time)
    if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
        fail_job(job_id, "Invalid audio time range.")

    duration = end_seconds - start_seconds
    cache_path = config.cache_dir / "audio" / f"{media_key(youtube_url, start_seconds, end_seconds)}.mp3"
    ensure_dir(cache_path.parent)
    ensure_dir(Path(audio_path).parent)

    if cache_path.exists():
        shutil.copy2(cache_path, audio_path)
        if validate_audio_file(job_id, audio_path, duration, fail=False):
            return audio_path
        cache_path.unlink(missing_ok=True)
        Path(audio_path).unlink(missing_ok=True)

    temp_dir = Path(audio_path).parent / "_audio_source"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    ensure_dir(temp_dir)

    command = yt_dlp_base_command() + [
        "--no-playlist",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--output",
        str(temp_dir / "source.%(ext)s"),
        youtube_url,
    ]
    try:
        run_command(job_id, command, config.youtube_timeout_seconds, "Audio download")

        candidates = sorted(temp_dir.glob("source*.mp3"))
        if not candidates:
            fail_job(job_id, "Audio extraction completed without producing an MP3 file.")

        source_duration = probe_audio_duration(candidates[0])
        if source_duration is not None and start_seconds >= source_duration:
            fail_job(
                job_id,
                "Selected start time is past the downloadable audio length "
                f"({format_duration(start_seconds)} selected, {format_duration(source_duration)} available).",
            )

        Path(audio_path).unlink(missing_ok=True)
        trim_command = [
            "ffmpeg",
            "-y",
            "-ss",
            str(start_seconds),
            "-i",
            str(candidates[0]),
            "-t",
            str(duration),
            "-vn",
            "-ac",
            "2",
            "-ar",
            "44100",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(audio_path),
        ]
        run_command(job_id, trim_command, config.ffmpeg_timeout_seconds, "Audio trim")
        validate_audio_file(job_id, audio_path, duration)

        shutil.copy2(audio_path, cache_path)
        return audio_path
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def probe_audio_duration(audio_path):
    if not Path(audio_path).exists() or Path(audio_path).stat().st_size < 1024:
        return None

    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return None

    try:
        duration = float((result.stdout or "").strip())
    except ValueError:
        return None
    return duration if duration > 0 else None


def format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def validate_audio_file(job_id, audio_path, expected_duration=None, fail=True):
    duration = probe_audio_duration(audio_path)
    if duration is not None:
        if expected_duration is None or duration >= min(1.0, expected_duration * 0.5):
            return True

    message = (
        "Audio extraction produced an invalid or empty MP3. "
        "Check that the selected start/end range exists in the audio source."
    )
    if fail:
        fail_job(job_id, message)
    logger.warning("[%s] %s", job_id, message)
    return False


def prepare_layer(args):
    image_path, layer_path, canvas_size = args
    with Image.open(image_path) as img:
        layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
        img = img.convert("RGBA")
        img.thumbnail(canvas_size, Image.Resampling.LANCZOS)
        left = (canvas_size[0] - img.width) // 2
        top = (canvas_size[1] - img.height) // 2
        layer.paste(img, (left, top), img)
        layer.save(layer_path, format="PNG", optimize=True)
    return layer_path


def collection_canvas_size(image_paths, target_height=1080, min_width=1080, max_canvas_width=1920):
    calculated_width = 0
    for path in image_paths:
        try:
            with Image.open(path) as img:
                width, height = img.size
                if height > 0:
                    scaled_width = round(width * (target_height / height))
                    calculated_width = max(calculated_width, scaled_width)
        except Exception:
            continue

    if calculated_width <= 0:
        return 1920, target_height

    canvas_width = min(max(calculated_width, min_width), max_canvas_width)

    if canvas_width % 2:
        canvas_width += 1
    return canvas_width, target_height


def collection_background_theme(image_paths, sample_size=(96, 96), max_samples=48):
    sampled = sample_images(list(image_paths), max_samples)
    dark_pixels = 0
    light_pixels = 0
    for path in sampled:
        try:
            with Image.open(path) as img:
                img = img.convert("L")
                img.thumbnail(sample_size, Image.Resampling.LANCZOS)
                histogram = img.histogram()
                dark_pixels += sum(histogram[:128])
                light_pixels += sum(histogram[128:])
        except Exception:
            continue
    return "dark" if dark_pixels >= light_pixels else "light"


def decode_audio_to_wav(job_id, audio_path, wav_path):
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-ac",
        "1",
        "-ar",
        "8000",
        "-f",
        "wav",
        str(wav_path),
    ]
    run_command(job_id, command, config.ffmpeg_timeout_seconds, "Audio analysis")


def estimate_bpm_from_wav(wav_path):
    with wave.open(str(wav_path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        sample_count = wav_file.getnframes()
        samples = wav_file.readframes(sample_count)

    if sample_rate <= 0 or len(samples) < 4:
        return 120

    values = [
        int.from_bytes(samples[idx:idx + 2], byteorder="little", signed=True) / 32768
        for idx in range(0, len(samples) - 1, 2)
    ]
    window_size = max(1, int(sample_rate * 0.05))
    energies = []
    for start in range(0, len(values), window_size):
        chunk = values[start:start + window_size]
        if chunk:
            energies.append(sum(abs(sample) for sample in chunk) / len(chunk))

    if len(energies) < 8:
        return 120

    mean_energy = sum(energies) / len(energies)
    flux = [max(0.0, current - previous) for previous, current in zip(energies, energies[1:])]
    if not flux or max(flux) <= 0:
        return 120

    best_bpm = 120
    best_score = -1
    for bpm in range(70, 181):
        period = max(1, round((60 / bpm) / 0.05))
        score = 0
        for idx in range(period, len(flux)):
            score += flux[idx] * flux[idx - period]
        if score > best_score:
            best_score = score
            best_bpm = bpm

    return best_bpm


def estimate_bpm(job_id, audio_path, analysis_dir):
    ensure_dir(analysis_dir)
    wav_path = Path(analysis_dir) / "bpm.wav"
    try:
        decode_audio_to_wav(job_id, audio_path, wav_path)
        return estimate_bpm_from_wav(wav_path)
    except Exception as exc:
        logger.warning("[%s] BPM estimation failed, using 120 BPM: %s", job_id, exc)
        return 120


def fps_from_bpm(bpm):
    return max(6, min(18, round(max(1, bpm) / 12)))


def bitrate_plan(duration_seconds, max_output_mb=None):
    max_output_mb = config.max_output_mb if max_output_mb is None else max_output_mb
    duration_seconds = max(1, float(duration_seconds))
    target_kbps = int((max_output_mb * 1024 * 1024 * 8) / duration_seconds / 1000)
    container_overhead_kbps = 8
    usable_kbps = max(1, target_kbps - container_overhead_kbps)
    audio_kbps = min(config.max_audio_bitrate_kbps, max(24, usable_kbps // 4))
    video_kbps = max(config.min_video_bitrate_kbps, usable_kbps - audio_kbps)

    if video_kbps + audio_kbps + container_overhead_kbps > target_kbps:
        audio_kbps = max(16, usable_kbps - video_kbps)

    if video_kbps + audio_kbps + container_overhead_kbps > target_kbps:
        video_kbps = max(12, usable_kbps - audio_kbps)

    return {
        "target_kbps": target_kbps,
        "video_kbps": max(12, video_kbps),
        "audio_kbps": max(16, audio_kbps),
    }


def link_or_copy(source, destination):
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def render_frames(job_id, images, frames_dir, duration, frame_rate, audio_path, bpm):
    existing_details = dict((get_job(job_id) or {}).get("details") or {})
    existing_details["image_count"] = len(images)
    update_job(job_id, status="running", step="rendering", progress=60, details=existing_details)
    if frames_dir.exists():
        shutil.rmtree(frames_dir)
    ensure_dir(frames_dir)

    sampled = shuffled_images(sample_images(images, config.max_images), seed=job_id)
    canvas_size = collection_canvas_size(sampled)
    asset_dir = frames_dir / "assets"
    sequence_dir = frames_dir / "sequence"
    ensure_dir(asset_dir)
    ensure_dir(sequence_dir)

    asset_jobs = [
        (image_path, asset_dir / f"{idx:05d}.png", canvas_size)
        for idx, image_path in enumerate(sampled)
    ]
    with ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        prepared_layers = list(pool.map(prepare_layer, asset_jobs))

    total_frames = max(1, round(duration * frame_rate))
    background_theme = collection_background_theme(sampled)
    background_color = (8, 8, 8, 255) if background_theme == "dark" else (248, 248, 244, 255)
    post_settings = normalize_post_settings(existing_details.get("post_settings"))
    existing_details.update(
        {
            "sequence_frames": total_frames,
            "duration_seconds": duration,
            "bpm": bpm,
            "frame_rate": frame_rate,
            "canvas_size": canvas_size,
            "post_settings": post_settings,
        }
    )
    update_job(job_id, status="running", step="rendering", progress=60, details=existing_details)

    base = Image.new("RGBA", canvas_size, background_color)
    progress_interval = max(1, total_frames // 20)
    for frame_number in range(total_frames):
        layer_path = prepared_layers[frame_number % len(prepared_layers)]
        with Image.open(layer_path) as layer:
            base.alpha_composite(layer)
        frame = apply_post_effects(base.copy(), post_settings)
        destination = sequence_dir / f"{frame_number:05d}.jpg"
        frame.convert("RGB").save(destination, format="JPEG", quality=88, optimize=True)
        if frame_number and frame_number % progress_interval == 0:
            progress = 60 + round((frame_number / total_frames) * 20)
            update_job(job_id, status="running", step="rendering", progress=progress)

    details = dict((get_job(job_id) or {}).get("details") or {})
    details.update(
        {
            "image_count": len(images),
            "sequence_frames": total_frames,
            "duration_seconds": duration,
            "background_theme": background_theme,
            "bpm": bpm,
            "frame_rate": frame_rate,
            "canvas_size": canvas_size,
            "post_settings": post_settings,
        }
    )
    update_job(job_id, details=details)

    return sequence_dir / "%05d.jpg"


def mux_video(job_id, frame_pattern, audio_path, output_path, frame_rate, duration):
    update_job(job_id, status="running", step="muxing", progress=82)
    temp_video_path = Path(output_path).with_name("video_only.mp4")
    plan = bitrate_plan(duration)
    passlog = str(Path(output_path).with_suffix(".ffmpeg-pass"))

    first_pass_command = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(frame_rate),
        "-i",
        str(frame_pattern),
        "-c:v",
        "libx264",
        "-b:v",
        f"{plan['video_kbps']}k",
        "-maxrate",
        f"{plan['video_kbps']}k",
        "-bufsize",
        f"{plan['video_kbps'] * 2}k",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-pass",
        "1",
        "-passlogfile",
        passlog,
        "-an",
        "-f",
        "mp4",
        "NUL" if os.name == "nt" else "/dev/null",
    ]
    run_command(job_id, first_pass_command, config.ffmpeg_timeout_seconds, "Video render first pass")

    second_pass_command = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(frame_rate),
        "-i",
        str(frame_pattern),
        "-c:v",
        "libx264",
        "-b:v",
        f"{plan['video_kbps']}k",
        "-maxrate",
        f"{plan['video_kbps']}k",
        "-bufsize",
        f"{plan['video_kbps'] * 2}k",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "veryfast",
        "-pass",
        "2",
        "-passlogfile",
        passlog,
        str(temp_video_path),
    ]
    run_command(job_id, second_pass_command, config.ffmpeg_timeout_seconds, "Video render second pass")

    mux_command = [
        "ffmpeg",
        "-y",
        "-i",
        str(temp_video_path),
        "-i",
        str(audio_path),
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        f"{plan['audio_kbps']}k",
        "-shortest",
        str(output_path),
    ]
    run_command(job_id, mux_command, config.ffmpeg_timeout_seconds, "Audio mux")

    temp_video_path.unlink(missing_ok=True)
    for pass_file in Path(output_path).parent.glob(f"{Path(output_path).stem}.ffmpeg-pass*"):
        pass_file.unlink(missing_ok=True)

    max_bytes = int(config.max_output_mb * 1024 * 1024)
    if Path(output_path).stat().st_size > max_bytes:
        fail_job(job_id, f"Output is larger than {config.max_output_mb:g} MB after bitrate targeting.")

    return output_path


def process_job(job_id):
    job = get_job(job_id)
    if not job:
        raise RuntimeError(f"Job not found: {job_id}")

    root = job_dir(job_id)
    images_dir = root / "images"
    frames_dir = root / "frames"
    audio_path = root / "audio.mp3"
    output_path = output_path_for(job_id)

    try:
        ensure_dir(root)
        update_job(job_id, status="running", step="queued", progress=max(30, job["progress"]), error="")
        images = selected_image_paths(job)
        if not images:
            images = download_images(job_id, job["board_url"], images_dir)
        audio = download_audio(job_id, job["youtube_url"], job["start_time"], job["end_time"], audio_path)
        start_seconds = parse_time(job["start_time"])
        end_seconds = parse_time(job["end_time"])
        duration = end_seconds - start_seconds
        bpm = estimate_bpm(job_id, audio, frames_dir / "analysis")
        frame_rate = fps_from_bpm(bpm)
        frame_pattern = render_frames(job_id, images, frames_dir, duration, frame_rate, audio, bpm)
        mux_video(job_id, frame_pattern, audio, output_path, frame_rate, duration)
        shutil.rmtree(frames_dir, ignore_errors=True)
        update_job(job_id, status="complete", step="complete", progress=100, output_path=output_path, error="")
        logger.info("[%s] complete: %s", job_id, output_path)
        return str(output_path)
    except Exception as exc:
        if get_job(job_id) and get_job(job_id)["status"] != "failed":
            update_job(job_id, status="failed", error=str(exc))
        raise


@celery_app.task(bind=True)
def process_job_task(self, job_id):
    return process_job(job_id)


@celery_app.task(bind=True)
def prepare_gallery_task(self, job_id):
    return prepare_gallery(job_id)


@celery_app.task(bind=True)
def delayed_delete_path(self, path, max_retries=5, sleep_interval=10):
    logger.info("Deleting path after delay: %s", path)
    for _ in range(max_retries):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
                return True
            if os.path.exists(path):
                os.remove(path)
                return True
            return True
        except OSError as exc:
            logger.error("Error deleting %s: %s. Retrying...", path, exc)
            sleep(sleep_interval)
    logger.error("Failed to delete %s after %s attempts.", path, max_retries)
    return False
