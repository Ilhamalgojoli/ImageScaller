import io
import itertools
import logging
import subprocess
import sys
from pathlib import Path
from threading import Lock, Thread
from time import monotonic
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

if VENV_PYTHON.is_file() and Path(sys.executable).resolve() != VENV_PYTHON.resolve():
    raise SystemExit(
        subprocess.call(
            [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]],
            cwd=ROOT,
        )
    )

import webview
from flask import Flask, abort, jsonify, request, send_file, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.serving import make_server
from werkzeug.utils import secure_filename

from src.upscaler import OUTPUT_LONG_EDGE, RealESRGANUpscaler, decode_image

MODEL_PATHS = {
    2: ROOT / "models" / "RealESRGAN_x2plus.pth",
    4: ROOT / "models" / "RealESRGAN_x4plus.pth",
}
OUTPUT_DIR = Path.home() / "Pictures" / "ResultImg"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
app.logger.setLevel(logging.INFO)

upscalers = {}
model_lock = Lock()
inference_lock = Lock()
progress_lock = Lock()
progress_jobs = {}
PROGRESS_JOB_TTL = 300

def update_progress(job_id, **updates):
    with progress_lock:
        progress = progress_jobs.get(job_id)
        if progress is not None:
            progress.update(updates)
            progress["updated_at"] = monotonic()


def cleanup_progress_jobs():
    expiration = monotonic() - PROGRESS_JOB_TTL
    with progress_lock:
        for job_id in [
            job_id
            for job_id, progress in progress_jobs.items()
            if progress["updated_at"] < expiration
        ]:
            del progress_jobs[job_id]


def get_upscaler(scale):
    if scale not in MODEL_PATHS:
        raise ValueError("Pilih model x2 atau x4.")
    with model_lock:
        if scale not in upscalers:
            model_path = MODEL_PATHS[scale]
            if not model_path.is_file():
                raise FileNotFoundError(f"Model Real-ESRGAN tidak ditemukan: {model_path}")
            upscalers[scale] = RealESRGANUpscaler(model_path, scale)
            app.logger.info("Real-ESRGAN x%s siap menggunakan %s", scale, upscalers[scale].device)
    return upscalers[scale]


def save_upscaled_image(source_name, image_bytes, scale):
    base_name = secure_filename(Path(source_name).stem) or "gambar"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for suffix in itertools.count(1):
        numbered_suffix = "" if suffix == 1 else f" ({suffix})"
        output_path = OUTPUT_DIR / f"{base_name}_{scale}x{numbered_suffix}.jpg"
        try:
            output_file = output_path.open("xb")
        except FileExistsError:
            continue

        with output_file:
            try:
                output_file.write(image_bytes)
            except OSError:
                output_path.unlink(missing_ok=True)
                raise
        return output_path


@app.errorhandler(RequestEntityTooLarge)
def handle_large_upload(_error):
    return jsonify(error="Ukuran file maksimal 20 MB."), 413

@app.route("/")
def index():
    return send_from_directory(ROOT, "index.html")


@app.route("/src/<path:filename>")
def src_file(filename):
    if filename not in {"script.js", "output.css"}:
        abort(404)
    return send_from_directory(ROOT / "src", filename)


@app.post("/api/upscale")
def upscale_image():
    try:
        scale = int(request.form.get("scale", "4"))
    except ValueError:
        return jsonify(error="Pilih model x2 atau x4."), 400
    if scale not in MODEL_PATHS:
        return jsonify(error="Pilih model x2 atau x4."), 400

    upload = request.files.get("image")
    if upload is None or not upload.filename:
        return jsonify(error="Pilih gambar yang ingin diperbesar."), 400

    image_bytes = upload.stream.read()
    if not image_bytes:
        return jsonify(error="File gambar kosong."), 400

    try:
        image = decode_image(image_bytes)
    except ValueError as error:
        return jsonify(error=str(error)), 400

    cleanup_progress_jobs()
    try:
        job_id = UUID(request.headers.get("X-Progress-Id", str(uuid4()))).hex
    except ValueError:
        return jsonify(error="ID proses gambar tidak valid."), 400

    with progress_lock:
        progress_jobs[job_id] = {
            "stage": "waiting",
            "completed_tiles": 0,
            "total_tiles": 0,
            "updated_at": monotonic(),
        }

    try:
        with inference_lock:
            update_progress(job_id, stage="loading_model")
            model = get_upscaler(scale)
            update_progress(job_id, stage="processing")
            result = model.enhance(
                image,
                on_progress=lambda completed, total: update_progress(
                    job_id,
                    completed_tiles=completed,
                    total_tiles=total,
                ),
            )
    except (FileNotFoundError, RuntimeError, OSError):
        update_progress(job_id, stage="error")
        app.logger.exception("Real-ESRGAN gagal memproses gambar.")
        return jsonify(error="Upscaling gagal. Periksa model dan kapasitas memori, lalu coba lagi."), 500

    try:
        output_path = save_upscaled_image(upload.filename, result, scale)
    except OSError:
        update_progress(job_id, stage="error")
        app.logger.exception("Hasil Real-ESRGAN gagal disimpan.")
        return jsonify(error="Hasil gagal disimpan. Periksa izin folder dan ruang penyimpanan."), 500

    update_progress(job_id, stage="complete")
    response = send_file(
        io.BytesIO(result),
        mimetype="image/jpeg",
        as_attachment=False,
        download_name=output_path.name,
    )
    response.headers["X-Output-Path"] = str(output_path)
    response.headers["X-Output-Size"] = str(len(result))
    resize_factor = OUTPUT_LONG_EDGE / max(image.shape[1], image.shape[0])
    output_width = max(1, round(image.shape[1] * resize_factor))
    output_height = max(1, round(image.shape[0] * resize_factor))
    response.headers["X-Output-Resolution"] = f"{output_width}x{output_height}"
    return response


@app.get("/api/upscale/progress/<job_id>")
def upscale_progress(job_id):
    try:
        job_id = UUID(job_id).hex
    except ValueError:
        return jsonify(error="ID proses gambar tidak valid."), 400

    with progress_lock:
        progress = progress_jobs.get(job_id)
        if progress is None:
            return jsonify(error="Proses gambar tidak ditemukan atau sudah kedaluwarsa."), 404
        return jsonify({key: value for key, value in progress.items() if key != "updated_at"})


def start_server():
    server = make_server("127.0.0.1", 5500, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()


if __name__ == "__main__":
    start_server()
    webview.create_window("Image Scaler", "http://127.0.0.1:5500")
    webview.start()
