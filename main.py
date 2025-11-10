from flask import Flask, Response, render_template_string, jsonify, request
import os
import random
import time
import requests
import io

# ---------------- CONFIG ----------------
MUSIC_DIR = "music"
GENRE = "swing jazz"

# pull from env if present (good for Render)
LASTFM_API_KEY = os.environ.get("LASTFM_API_KEY", "6652931a0bb826b32cf1d02a3f0ae88e")

# ElevenLabs
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "sk_26996366829d317a774db613cadbb1d90c15e5fae37559a2")
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "IVtCAtlu3DNNB0ZLPyRA")

RECOMMEND_LIMIT = 5
# ----------------------------------------

app = Flask(__name__)

# collect local songs
if os.path.isdir(MUSIC_DIR):
    local_songs = [
        os.path.join(MUSIC_DIR, f)
        for f in os.listdir(MUSIC_DIR)
        if f.lower().endswith(".mp3")
    ]
else:
    local_songs = []

current_song = None               # can be file path OR "Title - Artist"
current_meta = {
    "title": None,
    "artist": None,
    "album": None,
    "image": None,
    "source": None,  # "local" or "lastfm"
}
playlist = []


def fetch_recommended_tracks(genre):
    if not LASTFM_API_KEY or LASTFM_API_KEY == "YOUR_LASTFM_API_KEY":
        return []
    try:
        url = (
            "https://ws.audioscrobbler.com/2.0/"
            f"?method=tag.gettoptracks&tag={genre}"
            f"&limit={RECOMMEND_LIMIT}&api_key={LASTFM_API_KEY}&format=json"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        tracks = data.get("tracks", {}).get("track", [])
        out = []
        for t in tracks:
            title = t.get("name")
            artist = t.get("artist", {}).get("name")
            if title and artist:
                out.append(f"{title} - {artist}")
        return out
    except Exception as e:
        print("Recommendation fetch failed:", e)
        return []


def fetch_track_info_from_lastfm(title, artist):
    """Try to get artwork + extra info from Last.fm for display."""
    if not LASTFM_API_KEY or LASTFM_API_KEY == "YOUR_LASTFM_API_KEY":
        return {}
    try:
        url = (
            "https://ws.audioscrobbler.com/2.0/"
            f"?method=track.getInfo&api_key={LASTFM_API_KEY}"
            f"&artist={requests.utils.quote(artist)}"
            f"&track={requests.utils.quote(title)}"
            f"&format=json"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        track = data.get("track", {})
        album = track.get("album", {})
        images = album.get("image", [])
        image_url = None
        if images:
            # pick the biggest image
            image_url = images[-1].get("#text")
        return {
            "title": track.get("name") or title,
            "artist": track.get("artist", {}).get("name") or artist,
            "album": album.get("title"),
            "image": image_url,
            "source": "lastfm",
        }
    except Exception as e:
        print("track info fetch failed:", e)
        return {}


def synthesize_host_voice(text):
    if not ELEVENLABS_API_KEY or ELEVENLABS_API_KEY == "YOUR_ELEVENLABS_API_KEY":
        print("HOST (text only):", text)
        return io.BytesIO(b"")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.55,
            "similarity_boost": 0.7,
            "style": 0.6,
            "use_speaker_boost": True
        }
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        resp.raise_for_status()
        return io.BytesIO(resp.content)
    except Exception as e:
        print("TTS failed:", e)
        return io.BytesIO(b"")


def build_playlist():
    global playlist
    recs = fetch_recommended_tracks(GENRE)
    playlist = list(local_songs)
    random.shuffle(playlist)
    playlist.extend(recs)
    if not playlist:
        playlist = []


def song_stream(path):
    with open(path, "rb") as f:
        chunk = f.read(1024)
        while chunk:
            yield chunk
            chunk = f.read(1024)


def set_now_playing_from_local(path):
    global current_meta
    name = os.path.basename(path)
    # basic split: "Artist - Title.mp3" style filenames? we'll just show filename
    current_meta = {
        "title": name,
        "artist": None,
        "album": None,
        "image": None,
        "source": "local",
    }


def set_now_playing_from_string(s):
    global current_meta
    # s is "Title - Artist"
    parts = s.split(" - ", 1)
    title = parts[0].strip()
    artist = parts[1].strip() if len(parts) > 1 else None
    info = fetch_track_info_from_lastfm(title, artist) if artist else {}
    if info:
        current_meta = info
    else:
        current_meta = {
            "title": title,
            "artist": artist,
            "album": None,
            "image": None,
            "source": "lastfm",
        }


@app.route("/")
def home():
    html = """
    <html>
    <head>
        <title>Vintage FM</title>
        <meta charset="utf-8" />
        <style>
            body { font-family: Arial, sans-serif; max-width: 600px; margin: 2rem auto; }
            .now { display: flex; gap: 1rem; align-items: center; }
            img.cover { width: 120px; height: 120px; object-fit: cover; border: 1px solid #ccc; }
            button { padding: 0.4rem 0.8rem; }
        </style>
        <script>
            async function refreshNowPlaying() {
                const res = await fetch('/nowplaying');
                const data = await res.json();
                document.getElementById('np-title').innerText = data.title || 'Unknown';
                document.getElementById('np-artist').innerText = data.artist || '';
                const img = document.getElementById('np-image');
                if (data.image) {
                    img.src = data.image;
                    img.style.display = 'block';
                } else {
                    img.style.display = 'none';
                }
            }
            setInterval(refreshNowPlaying, 5000);
            window.onload = refreshNowPlaying;
        </script>
    </head>
    <body>
        <h1>Vintage FM</h1>
        <div class="now">
            <img id="np-image" class="cover" style="display:none" />
            <div>
                <div id="np-title" style="font-size:1.2rem; font-weight:bold;">Loading...</div>
                <div id="np-artist" style="color:#555;"></div>
                <p><a href="/stream">Listen Live</a></p>
            </div>
        </div>
        <form action="/skip" method="post" style="margin-top:1rem;">
            <button type="submit">Skip Track</button>
        </form>
    </body>
    </html>
    """
    return render_template_string(html)


@app.route("/nowplaying")
def now_playing():
    return jsonify(current_meta)


@app.route("/stream")
def stream():
    global current_song

    def generate():
        while True:
            if not playlist:
                build_playlist()

            for item in list(playlist):
                current_song = item

                if os.path.exists(item):
                    set_now_playing_from_local(item)

                    if random.random() < 0.3:
                        intro = synthesize_host_voice("You are tuned to Vintage F M, keeping the good sounds alive.")
                        yield intro.read()

                    yield from song_stream(item)
                else:
                    set_now_playing_from_string(item)
                    announce = synthesize_host_voice(f"Up next, {item}.")
                    yield announce.read()

                host_lines = [
                    "That was another fine number here on Vintage F M.",
                    "Stay with us, more melodies are on the way.",
                    "Vintage F M: your station for timeless tunes."
                ]
                outro = synthesize_host_voice(random.choice(host_lines))
                yield outro.read()

                time.sleep(1)

    return Response(generate(), mimetype="audio/mpeg")


@app.route("/skip", methods=["POST"])
def skip_track():
    build_playlist()
    return "<p>Skipping...</p><meta http-equiv='refresh' content='1; url=/' />"


if __name__ == "__main__":
    build_playlist()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
