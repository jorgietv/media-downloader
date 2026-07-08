# HQ Media Downloader

Paste a **YouTube / TikTok / Instagram** link and download it back at the **highest quality** — full‑resolution video (up to 4K) *and* audio. No app to install for you or anyone you share it with; it runs as a website.

## Why this gets higher quality than "paste‑a‑link" sites

YouTube (and to a lesser degree TikTok/Instagram) send high resolutions as **two separate streams** — video with no sound, and audio with no picture. Cheap downloaders only grab the single pre‑combined file, which is capped at **720p**. This tool uses `yt-dlp` to pull the **best video stream + best audio stream** and merges them with **ffmpeg** — that's how you get true 1080p / 1440p / 4K, plus clean audio‑only extraction.

---

## What's in this folder

| File | What it is |
|---|---|
| `app.py` | The engine (Python / FastAPI + yt-dlp) |
| `index.html` | The web page you'll see |
| `Dockerfile` | Tells the host how to build it (includes ffmpeg) |
| `requirements.txt` | Python dependencies |
| `render.yaml` | One‑click config for Render |
| `.dockerignore` | Housekeeping |

You don't need to edit any of these to get started.

---

## Deploy it as a public website (no coding)

You'll put these files on **GitHub** (free), then connect a host that can actually run the engine. **Vercel and Netlify can't do this** — their functions time out, cap file sizes, don't include ffmpeg, and their servers get bot‑blocked by YouTube. Use one of the hosts below instead.

### Step 1 — Put the files on GitHub (5 min, no git needed)

1. Make a free account at **github.com**.
2. Click the **+** (top right) → **New repository**. Name it e.g. `media-downloader`, keep it **Private**, click **Create repository**.
3. On the next page click **uploading an existing file**.
4. **Drag all the files from this folder** into the browser and click **Commit changes**. Done — no command line.

### Step 2 — Deploy the engine

**Option A — Render (has a free tier, recommended to start)**

1. Sign up at **render.com** with your GitHub account.
2. Click **New +** → **Blueprint**.
3. Pick your `media-downloader` repo. Render reads `render.yaml` automatically. Click **Apply**.
4. Wait ~3–5 min for the first build. You'll get a public URL like `https://media-downloader-xxxx.onrender.com`.

> Render's **free** plan sleeps after 15 min idle (first load takes ~40s to wake) and has 512 MB RAM, which is fine for audio and 1080p but can struggle on heavy 4K. For smooth always‑on 4K, switch the plan in `render.yaml` from `free` to `starter` (~$7/mo) or use Railway.

**Option B — Railway (~$5/mo, smoothest, no sleep)**

1. Sign up at **railway.com** with GitHub.
2. **New Project** → **Deploy from GitHub repo** → pick your repo.
3. Railway auto‑detects the `Dockerfile` and builds it. Under **Settings → Networking**, click **Generate Domain** to get your public URL.

That's it — open the URL on your phone or computer, paste a link, download.

---

## Beating the YouTube "Sign in to confirm you're not a bot" block

Cloud servers share IP addresses that YouTube throttles, so **YouTube downloads may fail on a host** even though they work from your home computer. The fix is to give the server your logged‑in **cookies**:

1. In Chrome, install a cookies exporter extension such as **"Get cookies.txt LOCALLY"**.
2. Go to youtube.com (signed in), click the extension, and **export** — you get a `cookies.txt` file.
3. Open that file, copy **all** of its text.
4. In your host's dashboard, add an **environment variable** named `COOKIES` and paste the text as the value:
   - **Render:** your service → **Environment** → **Add Environment Variable**.
   - **Railway:** your service → **Variables** → **New Variable**.
5. Save. The service restarts and can now reach YouTube (and your own private/unlisted videos).

> Cookies are like a login session — keep the repo **private** and don't share the URL publicly if you've added your cookies. Re‑export every few weeks if it starts failing.

TikTok and Instagram usually work without cookies; private Instagram content needs them too.

---

## Keeping it working over time

YouTube changes often, so `yt-dlp` ships frequent updates. If downloads start failing, **redeploy** to pull the latest version:
- **Render:** service → **Manual Deploy** → **Clear build cache & deploy**.
- **Railway:** service → **Deployments** → **Redeploy**.

(The `requirements.txt` always requests the newest `yt-dlp` on build.)

---

## Notes on quality & formats

- **Video** downloads as **MP4** merged at your chosen resolution (Best / 4K / 1440p / 1080p / 720p). 4K/1440p from YouTube use the VP9/AV1 codec inside the MP4 — modern phones and players handle it. If a file ever won't play on an older device, pick **1080p** or **Original**.
- **Audio → Original** keeps the native best stream with **no re‑encoding** (true highest quality). **Audio → MP3 320** is slightly lossy but plays everywhere.
- Downloading re‑encodes nothing unless you choose MP3, so you get the platform's maximum available quality — you can't exceed what the platform itself stores.

---

## Optional: try it on your Mac first

If you want to test before deploying (requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)):

```bash
cd media-downloader
docker build -t media-downloader .
docker run -p 8000:8000 media-downloader
```

Then open **http://localhost:8000**.

Or without Docker (needs Python 3.11+ and `ffmpeg` via `brew install ffmpeg`):

```bash
cd media-downloader
pip install -r requirements.txt
uvicorn app:app --port 8000
```

---

*For downloading your own content, or content you have the rights to. You're responsible for how you use it and for following each platform's terms.*
