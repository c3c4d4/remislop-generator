import hashlib
import os
import random
import shutil
import subprocess
import sys
import wave
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from time import sleep
from urllib.parse import urlparse, urlunparse

from PIL import Image

from celery_config import celery_app, logger
from config import config
from jobs import blocked_checksums, get_job, job_dir, output_path_for, update_job
from validation import parse_time, split_source_urls


IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp")


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


def find_images(directory):
    return sorted(
        path
        for path in Path(directory).rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
    )


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
    copy_tree_contents(temp_dir, target_dir)

    downloaded = find_images(temp_dir)
    if downloaded:
        if source_cache_dir.exists():
            shutil.rmtree(source_cache_dir)
        copy_tree_contents(temp_dir, source_cache_dir)

    shutil.rmtree(temp_dir, ignore_errors=True)
    if result.returncode != 0:
        return [(source_url, (result.stderr or result.stdout or "").strip())]
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
    update_job(job_id, step="downloading_audio", progress=35)
    start_seconds = parse_time(start_time)
    end_seconds = parse_time(end_time)
    if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
        fail_job(job_id, "Invalid audio time range.")

    cache_path = config.cache_dir / "audio" / f"{media_key(youtube_url, start_seconds, end_seconds)}.mp3"
    ensure_dir(cache_path.parent)
    ensure_dir(Path(audio_path).parent)

    if cache_path.exists():
        shutil.copy2(cache_path, audio_path)
        return audio_path

    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-playlist",
        "--extract-audio",
        "--audio-format",
        "mp3",
        "--postprocessor-args",
        f"-ss {start_seconds} -to {end_seconds}",
        "--output",
        str(audio_path),
        youtube_url,
    ]
    run_command(job_id, command, config.youtube_timeout_seconds, "Audio download")

    if not Path(audio_path).exists():
        candidates = list(Path(audio_path).parent.glob(f"{Path(audio_path).stem}*.mp3"))
        if candidates:
            candidates[0].replace(audio_path)
        else:
            fail_job(job_id, "Audio extraction completed without producing an MP3 file.")

    shutil.copy2(audio_path, cache_path)
    return audio_path


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


def collection_canvas_size(image_paths, target_height=1080):
    max_width = 0
    for path in image_paths:
        try:
            with Image.open(path) as img:
                width, height = img.size
                if height > 0:
                    scaled_width = round(width * (target_height / height))
                    max_width = max(max_width, scaled_width)
        except Exception:
            continue

    if max_width <= 0:
        return 1920, 1080

    if max_width % 2:
        max_width += 1
    return max_width, target_height


@lru_cache(maxsize=8)
def load_watermark_mask(path, logo_size):
    if not Path(path).exists():
        return None
    with Image.open(path) as image:
        logo = image.convert("RGBA")
    logo.thumbnail((logo_size, logo_size), Image.Resampling.LANCZOS)
    return logo


def repaint_logo(logo, color):
    alpha = logo.getchannel("A")
    painted = Image.new("RGBA", logo.size, color)
    painted.putalpha(alpha)
    return painted


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


def apply_watermark(frame, frame_number, background_theme, frame_rate, bpm):
    logo_size = config.watermark_size
    margin = config.watermark_margin
    mask = load_watermark_mask(str(config.watermark_source_path), logo_size)
    if mask is None:
        return frame

    if background_theme == "dark":
        logo = repaint_logo(mask, (255, 255, 255, 220))
    else:
        logo = repaint_logo(mask, (0, 0, 0, 220))

    degrees_per_frame = 360 * (max(1, bpm) / 60) / max(1, frame_rate)
    angle = -(frame_number * degrees_per_frame)
    logo = logo.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
    width, height = frame.size
    left = max(0, width - margin - logo.width)
    top = max(0, height - margin - logo.height)
    frame.alpha_composite(logo, (left, top))
    return frame


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


def render_frames(job_id, images, frames_dir, duration, frame_rate, audio_path):
    update_job(job_id, step="rendering", progress=60, details={"image_count": len(images)})
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
    bpm = estimate_bpm(job_id, audio_path, frames_dir / "analysis")
    base = Image.new("RGBA", canvas_size, background_color)
    for frame_number in range(total_frames):
        layer_path = prepared_layers[frame_number % len(prepared_layers)]
        with Image.open(layer_path) as layer:
            base.alpha_composite(layer)
        frame = apply_watermark(base.copy(), frame_number, background_theme, frame_rate, bpm)
        destination = sequence_dir / f"{frame_number:05d}.jpg"
        frame.convert("RGB").save(destination, format="JPEG", quality=88, optimize=True)

    update_job(
        job_id,
        details={
            "image_count": len(images),
            "sequence_frames": total_frames,
            "duration_seconds": duration,
            "background_theme": background_theme,
            "bpm": bpm,
            "canvas_size": canvas_size,
        },
    )

    return sequence_dir / "%05d.jpg"


def mux_video(job_id, frame_pattern, audio_path, output_path, frame_rate, duration):
    update_job(job_id, step="muxing", progress=82)
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
        images = selected_image_paths(job)
        if not images:
            images = download_images(job_id, job["board_url"], images_dir)
        audio = download_audio(job_id, job["youtube_url"], job["start_time"], job["end_time"], audio_path)
        start_seconds = parse_time(job["start_time"])
        end_seconds = parse_time(job["end_time"])
        duration = end_seconds - start_seconds
        frame_pattern = render_frames(job_id, images, frames_dir, duration, job["frame_rate"], audio)
        mux_video(job_id, frame_pattern, audio, output_path, job["frame_rate"], duration)
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
