from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import urllib.error
import re

# ─────────────────────────────────────────────
#  CORS & JSON helpers
# ─────────────────────────────────────────────
CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}

def ok(data: dict) -> tuple:
    return 200, {"success": True, **data}

def err(msg: str, code: int = 400) -> tuple:
    return code, {"success": False, "error": msg}


# ─────────────────────────────────────────────
#  Platform detection
# ─────────────────────────────────────────────
PATTERNS = {
    "tiktok":    re.compile(r"(tiktok\.com/@|tiktok\.com/t/|vm\.tiktok|vt\.tiktok)", re.I),
    "facebook":  re.compile(r"(facebook\.com/.*/videos/|fb\.watch|fb\.gg|facebook\.com/share/v)", re.I),
    "instagram": re.compile(r"(instagram\.com/(p|reel|tv)/)", re.I),
    "youtube":   re.compile(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts)", re.I),
    "twitter":   re.compile(r"(twitter\.com|x\.com)/\w+/status/", re.I),
}

def detect_platform(url: str) -> str | None:
    for platform, pat in PATTERNS.items():
        if pat.search(url):
            return platform
    return None


# ─────────────────────────────────────────────
#  HTTP helpers
# ─────────────────────────────────────────────
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

def http_get(url: str, headers: dict = None, timeout: int = 20) -> bytes:
    h = {**DEFAULT_HEADERS, **(headers or {})}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def http_post(url: str, data, headers: dict = None, timeout: int = 20) -> bytes:
    h = {**DEFAULT_HEADERS, **(headers or {})}
    if isinstance(data, dict):
        body = urllib.parse.urlencode(data).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    else:
        body = data
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def fetch_json(url: str, post_data=None, headers: dict = None) -> dict:
    raw = http_post(url, post_data, headers) if post_data is not None else http_get(url, headers)
    return json.loads(raw.decode("utf-8", errors="replace"))

def format_size(b):
    if not b:
        return None
    mb = b / 1024 / 1024
    return f"{mb:.2f} MB" if mb >= 1 else f"{b/1024:.1f} KB"

def format_duration(s):
    if not s:
        return None
    m, sec = divmod(int(s), 60)
    return f"{m}:{sec:02d}"


# ─────────────────────────────────────────────
#  TikTok — multiple APIs
# ─────────────────────────────────────────────
def download_tiktok(url: str) -> dict:

    # 1. tikwm.com (best, no watermark)
    try:
        j = fetch_json(
            f"https://www.tikwm.com/api/?url={urllib.parse.quote(url)}&hd=1",
            headers={"Referer": "https://www.tikwm.com/"}
        )
        if j.get("code") == 0 and j.get("data"):
            d = j["data"]
            video_url = d.get("hdplay") or d.get("play")
            if video_url:
                return {
                    "platform": "tiktok",
                    "title": d.get("title", "TikTok Video"),
                    "thumbnail": d.get("cover"),
                    "duration": format_duration(d.get("duration")),
                    "author": d.get("author", {}).get("nickname"),
                    "links": {
                        "hd_no_watermark": d.get("hdplay"),
                        "sd_no_watermark": d.get("play"),
                        "watermark": d.get("wmplay"),
                        "audio": d.get("music"),
                    },
                }
    except Exception:
        pass

    # 2. tiktok-downloader.com API
    try:
        j = fetch_json(
            "https://tiktok-downloader-download-tiktok-videos-without-watermark.p.rapidapi.com/index?url=" + urllib.parse.quote(url),
            headers={
                "X-RapidAPI-Host": "tiktok-downloader-download-tiktok-videos-without-watermark.p.rapidapi.com",
            }
        )
        if j.get("video"):
            videos = j["video"]
            links = {f"video_{i+1}": v for i, v in enumerate(videos if isinstance(videos, list) else [videos])}
            return {"platform": "tiktok", "title": "TikTok Video", "links": links}
    except Exception:
        pass

    # 3. ssstik.io
    try:
        raw = http_post(
            "https://ssstik.io/abc?lang=en",
            {"id": url, "locale": "en", "tt": ""},
            {"Referer": "https://ssstik.io/en", "Origin": "https://ssstik.io"},
        )
        html = raw.decode("utf-8", errors="replace")
        m = re.search(r'href="(https?://[^"]+\.mp4[^"]*)"[^>]*>\s*(?:Without watermark|Download)', html, re.I)
        if not m:
            m = re.search(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if m:
            return {
                "platform": "tiktok",
                "title": "TikTok Video",
                "links": {"no_watermark": m.group(1).replace("&amp;", "&")},
            }
    except Exception:
        pass

    # 4. savetik.net
    try:
        raw = http_post(
            "https://savetik.net/api/ajaxSearch",
            {"q": url, "lang": "en"},
            {"Referer": "https://savetik.net/", "Origin": "https://savetik.net"},
        )
        j = json.loads(raw.decode())
        html = j.get("data", "")
        links = re.findall(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if links:
            return {
                "platform": "tiktok",
                "title": "TikTok Video",
                "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(links[:3])},
            }
    except Exception:
        pass

    # 5. musicaldown.com
    try:
        raw = http_post(
            "https://musicaldown.com/api/process",
            {"url": url},
            {"Referer": "https://musicaldown.com/", "Origin": "https://musicaldown.com"},
        )
        j = json.loads(raw.decode())
        if j.get("url"):
            return {"platform": "tiktok", "title": "TikTok Video", "links": {"video": j["url"]}}
    except Exception:
        pass

    # 6. snaptik fallback
    try:
        raw = http_post(
            "https://snaptik.app/abc2.php",
            {"url": url, "lang": "en"},
            {"Referer": "https://snaptik.app/"},
        )
        html = raw.decode("utf-8", errors="replace")
        m = re.search(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if m:
            return {
                "platform": "tiktok",
                "title": "TikTok Video",
                "links": {"sd_no_watermark": m.group(1).replace("&amp;", "&")},
            }
    except Exception:
        pass

    raise ValueError("TikTok: সকল API ব্যর্থ হয়েছে। লিংক সঠিক আছে?")


# ─────────────────────────────────────────────
#  Facebook
# ─────────────────────────────────────────────
def download_facebook(url: str) -> dict:
    # 1. fdown.net
    try:
        raw = http_post(
            "https://fdown.net/download.php",
            {"URLz": url},
            {"Referer": "https://fdown.net/"},
        )
        html = raw.decode("utf-8", errors="replace")
        sd = re.search(r'id="sdlink"[^>]*href="([^"]+)"', html, re.I) or \
             re.search(r'href="([^"]+)"[^>]*id="sdlink"', html, re.I)
        hd = re.search(r'id="hdlink"[^>]*href="([^"]+)"', html, re.I) or \
             re.search(r'href="([^"]+)"[^>]*id="hdlink"', html, re.I)
        if sd:
            return {
                "platform": "facebook",
                "title": "Facebook Video",
                "links": {
                    "sd": sd.group(1).replace("&amp;", "&"),
                    "hd": hd.group(1).replace("&amp;", "&") if hd else None,
                },
            }
    except Exception:
        pass

    # 2. getfvid.com
    try:
        j = fetch_json(f"https://getfvid.com/api?url={urllib.parse.quote(url)}&format=json")
        if j.get("links", {}).get("sd"):
            return {
                "platform": "facebook",
                "title": j.get("title", "Facebook Video"),
                "links": {"sd": j["links"]["sd"], "hd": j["links"].get("hd")},
            }
    except Exception:
        pass

    # 3. fbdownloader.com
    try:
        j = fetch_json(
            "https://fbdownloader.com/api/data",
            {"url": url},
            {"X-Requested-With": "XMLHttpRequest", "Referer": "https://fbdownloader.com/"},
        )
        link = j.get("sd") or j.get("url")
        if link:
            return {
                "platform": "facebook",
                "title": j.get("title", "Facebook Video"),
                "links": {"sd": link.replace("&amp;", "&")},
            }
    except Exception:
        pass

    # 4. savefrom.net style
    try:
        j = fetch_json(
            "https://worker.sf-tools.com/savefrom.php",
            {"sf_url": url, "lang": "en"},
            {"Referer": "https://en.savefrom.net/"},
        )
        if j.get("url"):
            links = {}
            for item in (j["url"] if isinstance(j["url"], list) else [j["url"]]):
                q = item.get("id", "video")
                links[q] = item.get("url") or item.get("nd")
            return {"platform": "facebook", "title": j.get("meta", {}).get("title", "Facebook Video"), "links": links}
    except Exception:
        pass

    raise ValueError("Facebook: সকল API ব্যর্থ। ভিডিও কি Public আছে?")


# ─────────────────────────────────────────────
#  Instagram
# ─────────────────────────────────────────────
def download_instagram(url: str) -> dict:
    # 1. instavideosave.net
    try:
        raw = http_post(
            "https://instavideosave.net/",
            {"url": url},
            {"Referer": "https://instavideosave.net/"},
        )
        html = raw.decode("utf-8", errors="replace")
        m = re.search(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if m:
            return {"platform": "instagram", "title": "Instagram Video", "links": {"video": m.group(1).replace("&amp;", "&")}}
    except Exception:
        pass

    # 2. snapinsta.app
    try:
        raw = http_post(
            "https://snapinsta.app/action.php",
            {"url": url},
            {"Referer": "https://snapinsta.app/"},
        )
        j = json.loads(raw.decode())
        if j.get("url"):
            return {"platform": "instagram", "title": "Instagram Video", "links": {"video": j["url"]}}
    except Exception:
        pass

    # 3. igram.world
    try:
        j = fetch_json(
            "https://igram.world/api/convert",
            {"url": url, "lang": "en"},
            {"Referer": "https://igram.world/"},
        )
        media = j.get("media", [])
        if media:
            links = {f"video_{i+1}": item.get("url") for i, item in enumerate(media)}
            return {"platform": "instagram", "title": "Instagram Video", "links": links}
    except Exception:
        pass

    # 4. saveinsta.app
    try:
        raw = http_post(
            "https://saveinsta.app/api/ajaxSearch",
            {"q": url, "lang": "en"},
            {"Referer": "https://saveinsta.app/", "Origin": "https://saveinsta.app"},
        )
        j = json.loads(raw.decode())
        html = j.get("data", "")
        links = re.findall(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if links:
            return {"platform": "instagram", "title": "Instagram Video", "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(links[:3])}}
    except Exception:
        pass

    raise ValueError("Instagram: সকল API ব্যর্থ। Profile কি Private?")


# ─────────────────────────────────────────────
#  YouTube
# ─────────────────────────────────────────────
def download_youtube(url: str) -> dict:
    # 1. cobalt.tools (most reliable)
    try:
        req_data = json.dumps({"url": url, "vQuality": "max"}).encode()
        req = urllib.request.Request(
            "https://api.cobalt.tools/",
            data=req_data,
            headers={**DEFAULT_HEADERS, "Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode())
        if j.get("status") in ("stream", "redirect", "tunnel") and j.get("url"):
            return {"platform": "youtube", "title": "YouTube Video", "links": {"video": j["url"]}}
        if j.get("status") == "picker":
            links = {f"video_{i}": p.get("url") for i, p in enumerate(j.get("picker", []))}
            return {"platform": "youtube", "title": "YouTube Video", "links": links}
    except Exception:
        pass

    # 2. y2mate
    try:
        j = fetch_json(
            "https://www.y2mate.com/mates/analyzeV2/ajax",
            {"k_query": url, "k_page": "home", "hl": "en", "q_auto": 0},
            {"Referer": "https://www.y2mate.com/"},
        )
        if j.get("status") == "Ok":
            links = {}
            for fmt, items in (j.get("links", {}) or {}).items():
                for quality, info in (items or {}).items():
                    if isinstance(info, dict) and info.get("f") in ("mp4", "mp3"):
                        links[f"{fmt}_{quality}"] = {"quality": info.get("q"), "size": info.get("size"), "k": info.get("k")}
            return {
                "platform": "youtube",
                "title": j.get("title", "YouTube Video"),
                "thumbnail": j.get("thumbnail"),
                "note": "Use /api/youtube-link?k={k}&vid={vid} to get direct URL",
                "vid": j.get("vid"),
                "links_meta": links,
            }
    except Exception:
        pass

    # 3. yt5s.io
    try:
        j = fetch_json(
            "https://yt5s.io/api/ajaxSearch",
            {"q": url, "lang": "en"},
            {"Referer": "https://yt5s.io/", "Origin": "https://yt5s.io"},
        )
        if j.get("links"):
            links = {}
            for quality, info in j["links"].get("mp4", {}).items():
                if isinstance(info, dict):
                    links[f"mp4_{quality}"] = info.get("url") or info.get("k")
            return {"platform": "youtube", "title": j.get("title", "YouTube Video"), "links": links}
    except Exception:
        pass

    raise ValueError("YouTube: সকল API ব্যর্থ। কিছুক্ষণ পরে আবার চেষ্টা করুন।")


# ─────────────────────────────────────────────
#  Twitter / X
# ─────────────────────────────────────────────
def download_twitter(url: str) -> dict:
    # 1. twitsave.com
    try:
        raw = http_get(
            f"https://twitsave.com/info?url={urllib.parse.quote(url)}",
            {"Referer": "https://twitsave.com/"},
        )
        html = raw.decode("utf-8", errors="replace")
        links = re.findall(r'href="(https://video\.twimg\.com/[^"]+\.mp4[^"]*)"', html)
        if links:
            return {"platform": "twitter", "title": "Twitter/X Video", "links": {f"quality_{i+1}": l for i, l in enumerate(links)}}
    except Exception:
        pass

    # 2. cobalt.tools
    try:
        req_data = json.dumps({"url": url, "vQuality": "max"}).encode()
        req = urllib.request.Request(
            "https://api.cobalt.tools/",
            data=req_data,
            headers={**DEFAULT_HEADERS, "Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode())
        if j.get("url"):
            return {"platform": "twitter", "title": "Twitter/X Video", "links": {"video": j["url"]}}
    except Exception:
        pass

    # 3. twittervideodownloader.com
    try:
        raw = http_post(
            "https://twittervideodownloader.com/download",
            {"tweet": url},
            {"Referer": "https://twittervideodownloader.com/", "Origin": "https://twittervideodownloader.com"},
        )
        html = raw.decode("utf-8", errors="replace")
        links = re.findall(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if links:
            return {"platform": "twitter", "title": "Twitter/X Video", "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(links[:3])}}
    except Exception:
        pass

    raise ValueError("Twitter/X: ভিডিও পাওয়া যায়নি।")


# ─────────────────────────────────────────────
#  Router
# ─────────────────────────────────────────────
HANDLERS = {
    "tiktok":    download_tiktok,
    "facebook":  download_facebook,
    "instagram": download_instagram,
    "youtube":   download_youtube,
    "twitter":   download_twitter,
}

def process(url: str, platform_override: str = None) -> tuple:
    if not url:
        return err("url parameter আবশ্যক", 400)
    platform = platform_override or detect_platform(url)
    if not platform:
        return err("Unsupported platform. Supported: tiktok, facebook, instagram, youtube, twitter", 400)
    handler = HANDLERS.get(platform)
    if not handler:
        return err(f"Platform '{platform}' এখনো সাপোর্ট নেই", 400)
    try:
        result = handler(url)
        return ok(result)
    except ValueError as e:
        return err(str(e), 422)
    except Exception as e:
        return err(f"Internal error: {str(e)}", 500)


# ─────────────────────────────────────────────
#  Vercel handler
# ─────────────────────────────────────────────
class handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def send_json(self, status: int, body: dict):
        encoded = json.dumps(body, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        url      = (params.get("url") or [""])[0].strip()
        platform = (params.get("platform") or [""])[0].strip().lower() or None
        status, body = process(url, platform)
        self.send_json(status, body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw    = self.rfile.read(length)
        ct     = self.headers.get("Content-Type", "")
        if "application/json" in ct:
            try:
                data = json.loads(raw.decode())
            except Exception:
                self.send_json(400, {"success": False, "error": "Invalid JSON"})
                return
        else:
            data = dict(urllib.parse.parse_qsl(raw.decode()))
        url      = data.get("url", "").strip()
        platform = data.get("platform", "").strip().lower() or None
        status, body = process(url, platform)
        self.send_json(status, body)