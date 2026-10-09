"""Test-only stand-in for yt-dlp. Speaks the subset of the CLI that FluxVid uses."""
import json, subprocess, sys, time
a = sys.argv[1:]
url = a[-1]

def fail(msg):
    sys.stderr.write(msg + "\n"); sys.exit(1)

if "bad" in url: fail("ERROR: Unsupported URL: " + url)
if "private" in url: fail("ERROR: Private video. Sign in if you've been granted access")

INFO = {"title": 'My: Favorite/Video? "Test" <1>', "duration": 42, "extractor_key": "Stub",
        "webpage_url": url, "thumbnail": "https://example.com/t.jpg",
        "formats": [
            {"vcodec": "avc1", "acodec": "none", "height": 1080, "width": 1920, "ext": "mp4", "filesize": 2000, "tbr": 2000},
            {"vcodec": "avc1", "acodec": "none", "height": 720, "width": 1280, "ext": "mp4", "filesize": 1000, "tbr": 1000},
            {"vcodec": "none", "acodec": "mp4a", "abr": 129.5, "ext": "m4a", "filesize": 200},
            {"vcodec": "none", "acodec": "opus", "abr": 160.2, "ext": "webm", "filesize": 250},
            {"vcodec": "none", "acodec": "none", "ext": "mhtml"}]}

if "-J" in a:
    print(json.dumps(INFO)); sys.exit(0)

def say(line):
    print(line, flush=True)

out = a[a.index("-o") + 1]
say("FVP|downloading|400")
if "huge" in url:
    say("FVP|downloading|999999999999"); time.sleep(5)
say("FVP|downloading|800")
if "slow" in url:
    time.sleep(30)
say("FVP|finished|1000")
say("FVP|downloading|100")
say("FVP|finished|200")
say("FVPP|started")
if "-x" in a:
    out = out.replace("%(ext)s", "mp3"); cmd = ["-f", "lavfi", "-i", "sine=d=1", out]
else:
    out = out.replace("%(ext)s", "mp4"); cmd = ["-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", out]
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *cmd], check=True)
say("FVT|" + INFO["title"])
