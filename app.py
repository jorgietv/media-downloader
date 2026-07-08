"""
HQ Media Downloader — backend engine.

Paste a YouTube / TikTok / Instagram link and get it back at the
HIGHEST quality. Uses yt-dlp to pull the best video-only + best
audio-only streams and merges them with ffmpeg (this is the part
simple downloaders skip, which is why they cap out at 720p).

For downloading your own content, or content you have the rights to.
"""

import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="HQ Media Downloader")

# Allow the page to call the API from anywhere (also works when the
# frontend is served by this same app).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
WORK_DIR = Path(tempfile.gettempdir()) / "hq_downloads"
WORK_DIR.mkdir(parents=True, exist_ok=True)

# In-memory job store. Fine for a single-instance personal service.
JOBS: dict[str, dict] = {}

# Cookies to beat "Sign in to confirm you're not a bot" and reach private /
# members content. Any ONE of these works:
#   1. A Render "Secret File" mounted at /etc/secrets/cookies.txt  (easiest)
#   2. A path in the COOKIES_FILE env var
#   3. The whole cookies.txt text pasted into the COOKIES env var
COOKIEFILE: Path | None = None
_custom_cookie = os.environ.get("COOKIES_FILE", "").strip()
_secret_cookie = Path("/etc/secrets/cookies.txt")
_cookies_env = os.environ.get("COOKIES", "").strip()
if _custom_cookie and Path(_custom_cookie).exists():
    COOKIEFILE = Path(_custom_cookie)
elif _secret_cookie.exists():
    COOKIEFILE = _secret_cookie
elif _cookies_env:
    COOKIEFILE = WORK_DIR / "cookies.txt"
    COOKIEFILE.write_text(_cookies_env)

# Optional guardrail for a public site: refuse absurdly long media.
MAX_DURATION = int(os.environ.get("MAX_DURATION_SECONDS", "0"))  # 0 = no limit

# How long to keep finished files before cleaning them up (seconds).
FILE_TTL = int(os.environ.get("FILE_TTL_SECONDS", "1800"))  # 30 min


def _base_opts() -> dict:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
        # Try YouTube player clients that often slip past datacenter bot-blocks
        # (the "Sign in to confirm you're not a bot" wall) without needing cookies.
        "extractor_args": {
            "youtube": {"player_client": ["tv", "ios", "web_safari", "mweb", "web"]}
        },
    }
    if COOKIEFILE:
        opts["cookiefile"] = str(COOKIEFILE)
    return opts


def _cleanup_old_jobs() -> None:
    now = time.time()
    for job_id, job in list(JOBS.items()):
        if job.get("created", now) + FILE_TTL < now:
            shutil.rmtree(WORK_DIR / job_id, ignore_errors=True)
            JOBS.pop(job_id, None)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class URLReq(BaseModel):
    url: str


class DownloadReq(BaseModel):
    url: str
    mode: str = "video"           # "video" | "audio"
    quality: str = "best"         # video: best|2160|1440|1080|720  audio: mp3|original


class ZipReq(BaseModel):
    job_ids: list[str]


# --------------------------------------------------------------------------- #
# Info: preview the link before downloading
# --------------------------------------------------------------------------- #
@app.post("/api/info")
def info(req: URLReq):
    try:
        with yt_dlp.YoutubeDL({**_base_opts(), "skip_download": True}) as ydl:
            data = ydl.extract_info(req.url, download=False)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_friendly_error(str(e)))

    if data.get("_type") == "playlist" and data.get("entries"):
        data = data["entries"][0]

    heights = sorted(
        {f.get("height") for f in data.get("formats", []) if f.get("height")},
        reverse=True,
    )
    return {
        "title": data.get("title"),
        "uploader": data.get("uploader") or data.get("channel"),
        "thumbnail": data.get("thumbnail"),
        "duration": data.get("duration"),
        "extractor": data.get("extractor_key"),
        "heights": heights,
    }


# --------------------------------------------------------------------------- #
# Download: start a background job, poll status, then fetch the file
# --------------------------------------------------------------------------- #
def _build_format(mode: str, quality: str) -> tuple[str, list]:
    """Return (format_string, postprocessors) for the requested output."""
    if mode == "audio":
        if quality == "mp3":
            return "bestaudio/best", [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "320",
                }
            ]
        # "original" — keep the native best-audio stream, no re-encode = max quality
        return "bestaudio/best", []

    # video
    if quality.isdigit():
        n = int(quality)
        fmt = (
            f"bv*[height<={n}]+ba/"          # best video ≤N merged with best audio
            f"b[height<={n}]/"               # or best pre-merged ≤N
            f"bv*+ba/b"                       # or absolute best available
        )
    else:  # "best"
        fmt = "bv*+ba/b"
    return fmt, []


def _run_job(job_id: str, req: DownloadReq) -> None:
    job = JOBS[job_id]
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    fmt, postprocessors = _build_format(req.mode, req.quality)

    def hook(d):
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                pct = d.get("downloaded_bytes", 0) / total * 100
                job["progress"] = round(min(pct, 99.0), 1)
            job["stage"] = "downloading"
        elif d.get("status") == "finished":
            job["stage"] = "processing"
            job["progress"] = 99.0

    opts = {
        **_base_opts(),
        "outtmpl": str(job_dir / "%(title).150B.%(ext)s"),
        "format": fmt,
        "progress_hooks": [hook],
        "postprocessors": postprocessors,
    }
    if req.mode == "video":
        opts["merge_output_format"] = "mp4"

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            meta = ydl.extract_info(req.url, download=False)
            if meta.get("_type") == "playlist" and meta.get("entries"):
                meta = meta["entries"][0]
            if MAX_DURATION and (meta.get("duration") or 0) > MAX_DURATION:
                raise RuntimeError(
                    f"This is longer than the {MAX_DURATION // 60} min limit set for this site."
                )
            ydl.download([req.url])
            job["title"] = meta.get("title")

        files = [p for p in job_dir.iterdir() if p.is_file() and p.name != "cookies.txt"]
        if not files:
            raise RuntimeError("Download finished but no file was produced.")
        final = max(files, key=lambda p: p.stat().st_size)
        job["filepath"] = str(final)
        job["filename"] = final.name
        job["status"] = "done"
        job["progress"] = 100.0
        job["stage"] = "done"
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = _friendly_error(str(e))


@app.post("/api/download")
def start_download(req: DownloadReq):
    _cleanup_old_jobs()
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "status": "downloading",
        "stage": "starting",
        "progress": 0.0,
        "title": None,
        "filename": None,
        "filepath": None,
        "error": None,
        "created": time.time(),
    }
    threading.Thread(target=_run_job, args=(job_id, req), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/status/{job_id}")
def status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job")
    return {k: job[k] for k in ("status", "stage", "progress", "title", "filename", "error")}


@app.get("/api/file/{job_id}")
def get_file(job_id: str):
    job = JOBS.get(job_id)
    if not job or job.get("status") != "done" or not job.get("filepath"):
        raise HTTPException(status_code=404, detail="File not ready")
    return FileResponse(
        job["filepath"],
        filename=job["filename"],
        media_type="application/octet-stream",
    )


@app.post("/api/zip")
def zip_files(req: ZipReq):
    """Bundle several finished downloads into one .zip (for bulk downloads)."""
    items = []
    for jid in req.job_ids:
        job = JOBS.get(jid)
        if job and job.get("status") == "done" and job.get("filepath"):
            items.append((job["filename"], job["filepath"]))
    if not items:
        raise HTTPException(status_code=404, detail="No finished files to zip")

    zip_path = WORK_DIR / f"bundle_{uuid.uuid4().hex[:8]}.zip"
    seen: dict[str, int] = {}
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        for name, path in items:
            # Avoid clobbering identical filenames inside the archive.
            arc = name
            if arc in seen:
                seen[arc] += 1
                stem, dot, ext = name.rpartition(".")
                arc = f"{stem}_{seen[name]}.{ext}" if dot else f"{name}_{seen[name]}"
            else:
                seen[arc] = 0
            zf.write(path, arcname=arc)
    return FileResponse(str(zip_path), filename="downloads.zip", media_type="application/zip")


# --------------------------------------------------------------------------- #
# Frontend
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def index():
    return (BASE_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _friendly_error(msg: str) -> str:
    low = msg.lower()
    if "sign in to confirm" in low or "bot" in low:
        return (
            "The platform blocked the server as a bot. Add a COOKIES value "
            "(see the deploy guide) to fix this — very common for YouTube on cloud hosts."
        )
    if "private" in low or "login" in low or "unavailable" in low:
        return "This video looks private or unavailable. If it's yours, add COOKIES to access it."
    if "unsupported url" in low or "no video" in low:
        return "That link isn't supported or has no downloadable media."
    # Trim noisy yt-dlp prefixes
    return msg.replace("ERROR: ", "").strip()[:300]
