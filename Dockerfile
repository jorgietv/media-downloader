# HQ Media Downloader — container image
# Includes ffmpeg (required to merge best video + best audio into one file).
FROM python:3.12-slim

# ffmpeg is what lets us reach 1080p/4K by merging separate streams.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Hosts (Railway/Render/Fly) inject the port via $PORT.
ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
