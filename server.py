"""Private yt-dlp API: YouTube link in, MP3 (under WhatsApp's 16 MB) out.

Nothing is kept: each request works in a temp folder that is deleted
right after the MP3 is sent back.

POST /download   header X-Token: <YTDLP_TOKEN>   body {"url": "<youtube link>"}
  -> 200 audio/mpeg (filename = video title)  or  JSON {"ok": false, "error": ...}
GET  /           -> health check
"""
import json
import os
import re
import subprocess
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

PORT = int(os.environ.get("PORT", 8765))
TOKEN = os.environ.get("YTDLP_TOKEN")
MAX_BYTES = 15 * 1024 * 1024  # stay under WhatsApp's 16 MB audio limit
MAX_SECONDS = 60 * 60
TEST_MP3 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test.mp3")
YT_RE = re.compile(
    r"^https?://(www\.|m\.)?(youtube\.com/(watch\?v=|shorts/)|youtu\.be/)[A-Za-z0-9_-]{11}[A-Za-z0-9_=&?.-]*$"
)


def to_mp3(url, tmp):
    # 1) best audio stream only, no video
    p = subprocess.run(
        [
            "yt-dlp", "-f", "bestaudio/best", "--no-playlist",
            "--match-filter", f"duration<={MAX_SECONDS}",
            "-o", os.path.join(tmp, "src.%(ext)s"),
            "--print", "after_move:filepath",
            "--print", "after_move:%(title)s",
            "--print", "after_move:%(duration)s",
            url,
        ],
        capture_output=True, text=True, timeout=600,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-500:] or "yt-dlp failed")
    lines = p.stdout.strip().splitlines()
    if len(lines) < 3:
        raise RuntimeError(f"video longer than {MAX_SECONDS // 60} min or unavailable")
    src, title, duration = lines[-3], lines[-2], float(lines[-1] or 0)

    # 2) pick a bitrate that fits the size limit (max 128 kbps)
    kbps = 128
    if duration > 0:
        kbps = max(32, min(128, int(MAX_BYTES * 8 / 1000 / duration) - 2))
    out = os.path.join(tmp, "out.mp3")
    f = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-vn",
         "-c:a", "libmp3lame", "-b:a", f"{kbps}k", out],
        capture_output=True, text=True, timeout=600,
    )
    if f.returncode != 0:
        raise RuntimeError(f.stderr[-500:] or "ffmpeg failed")
    if os.path.getsize(out) > 16 * 1024 * 1024:
        raise RuntimeError("audio too large for WhatsApp")
    return out, title


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path != "/test.mp3":
            return self._json(200, {"ok": True})
        # Temporary: always return the same stored song
        if not TOKEN or self.headers.get("X-Token") != TOKEN:
            return self._json(401, {"ok": False, "error": "unauthorized"})
        if not os.path.isfile(TEST_MP3):
            return self._json(404, {"ok": False, "error": "test.mp3 missing"})
        with open(TEST_MP3, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", 'attachment; filename="test.mp3"')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/download":
            return self._json(404, {"ok": False, "error": "not found"})
        if not TOKEN or self.headers.get("X-Token") != TOKEN:
            return self._json(401, {"ok": False, "error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            url = json.loads(self.rfile.read(length) or b"{}").get("url", "").strip()
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"ok": False, "error": "bad json"})
        if not YT_RE.match(url):
            return self._json(400, {"ok": False, "error": "not a youtube link"})

        with tempfile.TemporaryDirectory() as tmp:  # deleted on exit
            try:
                path, title = to_mp3(url, tmp)
            except (RuntimeError, subprocess.TimeoutExpired) as e:
                return self._json(500, {"ok": False, "error": str(e) or "timed out"})
            with open(path, "rb") as fh:
                data = fh.read()
        name = re.sub(r'[\\/:*?"<>|]', "", title)[:80] or "audio"
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(name)}.mp3")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Set the YTDLP_TOKEN environment variable first.")
    print(f"yt-dlp API listening on :{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
