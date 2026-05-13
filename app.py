from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from io import BytesIO
import json
import subprocess
import zipfile

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.utils import secure_filename
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

from celery_config import celery_app, logger
from config import config
from jobs import block_checksums, cleanup_unsaved_outputs, create_job, get_job, init_db, mark_interrupted_jobs, mark_saved, recent_jobs, step_payload, update_job
from tasks import delayed_delete_path, ensure_thumbnail, post_settings_from_form, prepare_gallery, prepare_gallery_task, process_job, process_job_task, yt_dlp_base_command
from validation import validate_request


app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=1)


def dispatch_job(job_id):
    if config.local_background_jobs:
        executor.submit(process_job, job_id)
    else:
        process_job_task.delay(job_id)


def dispatch_gallery(job_id):
    if config.local_background_jobs:
        executor.submit(prepare_gallery, job_id)
    else:
        prepare_gallery_task.delay(job_id)


def uploaded_files():
    files = [file for file in request.files.getlist("image_files") if file and file.filename]
    archive = request.files.get("image_zip")
    if archive and archive.filename:
        files.append(archive)
    return files


def save_uploads(job_id, files):
    upload_dir = config.output_dir / job_id / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)
    for file in files:
        filename = secure_filename(file.filename)
        if not filename:
            continue
        destination = upload_dir / filename
        file.save(destination)
        if destination.suffix.lower() == ".zip":
            with zipfile.ZipFile(destination) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    member_name = secure_filename(Path(member.filename).name)
                    if member_name:
                        with archive.open(member) as src, (upload_dir / member_name).open("wb") as dst:
                            dst.write(src.read())
            destination.unlink(missing_ok=True)


def format_seconds(seconds):
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


@app.before_request
def ensure_database():
    init_db()


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        files = uploaded_files()
        validation = validate_request(request.form, config.max_duration_seconds, has_upload=bool(files))
        if validation["errors"]:
            return render_template(
                "index.html",
                errors=validation["errors"],
                values=request.form,
                jobs=recent_jobs(),
                config=config,
            ), 400

        try:
            if files and not validation["data"]["board_url"]:
                validation["data"]["board_url"] = "upload://local"
            job_id = create_job(validation["data"])
            if files:
                save_uploads(job_id, files)
            dispatch_gallery(job_id)
            return redirect(url_for("gallery", job_id=job_id))
        except Exception as exc:
            logger.error("Failed to dispatch job", exc_info=True)
            return render_template(
                "index.html",
                errors=[f"Could not start the job: {exc}"],
                values=request.form,
                jobs=recent_jobs(),
                config=config,
            ), 500

    return render_template("index.html", errors=[], values={}, jobs=recent_jobs(), config=config)


@app.route("/gallery/<job_id>")
def gallery(job_id):
    job = get_job(job_id)
    if job is None:
        return redirect(url_for("index"))
    if job["status"] == "failed":
        return redirect(url_for("status", job_id=job_id))
    images = (job.get("details") or {}).get("images") or []
    return render_template("gallery.html", job=job, images=images)


@app.route("/generate/<job_id>", methods=["POST"])
def generate(job_id):
    job = get_job(job_id)
    if job is None:
        return redirect(url_for("index"))

    images = (job.get("details") or {}).get("images") or []
    selected_checksums = set(request.form.getlist("selected"))
    selected = [image for image in images if image["checksum"] in selected_checksums]
    rejected = [image["checksum"] for image in images if image["checksum"] not in selected_checksums]

    if len(selected) < config.min_images:
        return render_template(
            "gallery.html",
            job=job,
            images=images,
            errors=[f"Keep at least {config.min_images} images selected."],
        ), 400

    if rejected:
        block_checksums(rejected)

    details = dict(job.get("details") or {})
    details["selected_images"] = selected
    details["blocked_from_review"] = len(rejected)
    details["post_settings"] = post_settings_from_form(request.form)
    update_job(job_id, status="queued", step="queued", progress=30, error="", details=details)
    cleanup_unsaved_outputs(except_job_id=job_id)
    dispatch_job(job_id)
    return redirect(url_for("status", job_id=job_id))


@app.route("/image/<job_id>/<checksum>")
def image(job_id, checksum):
    job = get_job(job_id)
    if job is None:
        return "Not found.", 404
    images = (job.get("details") or {}).get("images") or []
    match = next((image for image in images if image["checksum"] == checksum), None)
    if not match:
        return "Not found.", 404
    path = Path(match["path"])
    if not path.exists():
        return "Not found.", 404
    return send_file(path)


@app.route("/thumb/<job_id>/<checksum>")
def thumb(job_id, checksum):
    job = get_job(job_id)
    if job is None:
        return "Not found.", 404
    images = (job.get("details") or {}).get("images") or []
    match = next((image for image in images if image["checksum"] == checksum), None)
    if not match:
        return "Not found.", 404
    path = Path(match["path"])
    if not path.exists():
        return "Not found.", 404
    return send_file(ensure_thumbnail(job_id, path, checksum), mimetype="image/jpeg")


@app.route("/status/<job_id>")
def status(job_id):
    job = get_job(job_id)
    if job is None:
        return redirect(url_for("index"))
    return render_template("status.html", job=job, steps=step_payload(job["step"]))


@app.route("/api/jobs/<job_id>")
def api_job(job_id):
    job = get_job(job_id)
    if job is None:
        return jsonify({"error": "Job not found"}), 404
    job["steps"] = step_payload(job["step"])
    return jsonify(job)


@app.route("/api/youtube")
@app.route("/api/audio-source")
def api_audio_source():
    audio_url = (request.args.get("url") or "").strip()
    if not audio_url:
        return jsonify({"error": "Missing URL"}), 400

    command = yt_dlp_base_command() + [
        "--dump-single-json",
        "--skip-download",
        "--no-playlist",
        audio_url,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return jsonify({"error": "Timed out while reading audio metadata"}), 504

    if result.returncode != 0:
        return jsonify({"error": (result.stderr or result.stdout or "Could not read audio metadata")[-800:]}), 400

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return jsonify({"error": "Could not parse audio metadata"}), 400

    duration = int(payload.get("duration") or 0)
    if duration <= 0:
        return jsonify({"error": "Audio duration is unavailable"}), 400

    return jsonify(
        {
            "title": payload.get("title") or "Audio source",
            "duration": duration,
            "duration_label": format_seconds(duration),
        }
    )


@app.route("/preview_effect/<job_id>", methods=["GET"])
def preview_effect(job_id):
    # Grab the first available frame from the sequence folder to preview
    sequence_dir = config.output_dir / job_id / "frames" / "sequence"
    frames = list(sequence_dir.glob("*.jpg"))
    if not frames:
        return "Not found", 404
        
    img = Image.open(frames[0]).convert("RGBA")
    
    # Example: grab query params
    contrast = float(request.args.get("contrast", 1.0))
    glow = int(request.args.get("glow", 0))
    pixelate = int(request.args.get("pixelate", 0))
    # format tint as r,g,b hex (e.g. "ff0000")
    tint_color = request.args.get("tint")
    opacity = float(request.args.get("opacity", 0.0))

    if contrast != 1.0:
        enhancer = ImageEnhance.Contrast(img)
        img = enhancer.enhance(contrast)
    
    if tint_color and opacity > 0:
        color = tuple(int(tint_color[i:i+2], 16) for i in (0, 2, 4)) + (255,)
        overlay = Image.new("RGBA", img.size, color)
        img = Image.blend(img, overlay, opacity)
        
    if pixelate > 0:
        # crude pixelation
        small = img.resize((img.size[0] // pixelate, img.size[1] // pixelate), Image.NEAREST)
        img = small.resize(img.size, Image.NEAREST)
        
    if glow > 0:
        # Super basic glow effect 
        img_blur = img.filter(ImageFilter.GaussianBlur(glow))
        img = Image.blend(img, img_blur, 0.5)

    buf = BytesIO()
    img.convert("RGB").save(buf, format="JPEG")
    buf.seek(0)
    return send_file(buf, mimetype="image/jpeg")


@app.route("/download/<job_id>")
def download(job_id):
    file_path = output_file_for_response(job_id)
    if file_path is None:
        return "Video not ready yet.", 404

    response = send_file(file_path, as_attachment=True, download_name=f"remislop-{job_id}.mp4")
    
    if config.local_background_jobs:
        import threading
        import time
        import shutil
        def do_delete():
            time.sleep(config.cleanup_after_seconds)
            try:
                if file_path.parent.exists():
                    shutil.rmtree(file_path.parent)
            except Exception as e:
                logger.error(f"Failed to delete {file_path.parent}: {e}")
        threading.Thread(target=do_delete, daemon=True).start()
    elif not celery_app.conf.task_always_eager:
        delayed_delete_path.apply_async(args=[str(file_path.parent)], countdown=config.cleanup_after_seconds)
        
    return response


@app.route("/video/<job_id>")
def video(job_id):
    file_path = output_file_for_response(job_id)
    if file_path is None:
        return "Video not ready yet.", 404
    return send_file(file_path, mimetype="video/mp4", conditional=True)


@app.route("/open/<job_id>", methods=["POST"])
def open_in_explorer(job_id):
    file_path = output_file_for_response(job_id)
    if file_path is None:
        return jsonify({"error": "Video not ready yet."}), 404

    try:
        subprocess.Popen(["explorer.exe", f"/select,{file_path}"])
    except Exception as exc:
        logger.error("Failed to open Explorer", exc_info=True)
        return jsonify({"error": str(exc)}), 500

    return jsonify({"ok": True})


@app.route("/save/<job_id>", methods=["POST"])
def save_video(job_id):
    if output_file_for_response(job_id) is None:
        return jsonify({"error": "Video not ready yet."}), 404
    mark_saved(job_id)
    return jsonify({"ok": True})


def output_file_for_response(job_id):
    job = get_job(job_id)
    if not job or not job.get("output_path"):
        return None

    file_path = Path(job["output_path"])
    if not file_path.exists():
        return None
    return file_path


if __name__ == "__main__":
    init_db()
    mark_interrupted_jobs()
    app.run(host="0.0.0.0")
