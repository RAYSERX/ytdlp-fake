FROM python:3.12-slim

# ffmpeg for MP3 encoding; Deno is the JS runtime yt-dlp needs for YouTube
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY --from=denoland/deno:bin-2.1.4 /deno /usr/local/bin/deno

# Always install the latest yt-dlp: YouTube breaks old versions often
RUN pip install --no-cache-dir -U "yt-dlp[default]"

WORKDIR /app
# server.py plus test.mp3 (the temporary fixed song), if present
COPY . .

CMD ["python", "server.py"]
