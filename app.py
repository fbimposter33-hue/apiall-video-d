from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import urllib.error
import re

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────
RAPIDAPI_KEY  = "93e8e0c16bmsh216466a3573b948p1a4dbdjsn3069b3e2d6c0"
RAPIDAPI_HOST = "social-media-video-downloader.p.rapidapi.com"

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json",
}

def ok(data: dict, debug_log: list = None) -> tuple:
    body = {"success": True, **data}
    if debug_log is not None:
        body["_debug"] = debug_log
    return 200, body

def err(msg: str, code: int = 400, debug_log: list = None) -> tuple:
    body = {"success": False, "error": msg}
    if debug_log is not None:
        body["_debug"] = debug_log
    return code, body


# ─────────────────────────────────────────────
#  Platform detection
# ─────────────────────────────────────────────
PATTERNS = {
    "tiktok":    re.compile(r"(tiktok\.com/@|tiktok\.com/t/|vm\.tiktok|vt\.tiktok|tiktok\.com/v/)", re.I),
    "facebook":  re.compile(r"(facebook\.com/.*/videos/|fb\.watch|fb\.gg|facebook\.com/share/v|facebook\.com/reel/|facebook\.com/watch)", re.I),
    "instagram": re.compile(r"(instagram\.com/(p|reel|tv|stories)/)", re.I),
    "youtube":   re.compile(r"(youtube\.com/watch|youtu\.be/|youtube\.com/shorts)", re.I),
    "twitter":   re.compile(r"(twitter\.com|x\.com)/\w+/status/", re.I),
}

def detect_platform(url: str) -> str | None:
    for platform, pat in PATTERNS.items():
        if pat.search(url):
            return platform
    return None


# ─────────────────────────────────────────────
#  Short URL resolver
# ─────────────────────────────────────────────
SHORT_DOMAINS = re.compile(r"(vm\.tiktok\.com|vt\.tiktok\.com|fb\.watch|fb\.gg|bit\.ly|t\.co)", re.I)

def resolve_url(url: str) -> str:
    if not SHORT_DOMAINS.search(url):
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        with opener.open(req, timeout=5) as r:
            return r.url
    except Exception:
        try:
            req2 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req2, timeout=5) as r:
                return r.url
        except Exception:
            return url


# ─────────────────────────────────────────────
#  HTTP helpers
# ─────────────────────────────────────────────
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 8

def http_get(url: str, headers: dict = None, timeout: int = TIMEOUT) -> bytes:
    h = {**DEFAULT_HEADERS, **(headers or {})}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def http_post(url: str, data, headers: dict = None, timeout: int = TIMEOUT) -> bytes:
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
#  RapidAPI — Social Media Video Downloader
#  Supports: instagram, tiktok, facebook, youtube, twitter
# ─────────────────────────────────────────────
def rapidapi_download(url: str, log: list) -> dict | None:
    log.append("trying: rapidapi social-media-video-downloader")
    try:
        api_url = f"https://{RAPIDAPI_HOST}/smvd/get/all?url={urllib.parse.quote(url, safe='')}"
        raw = http_get(api_url, {
            "x-rapidapi-key":  RAPIDAPI_KEY,
            "x-rapidapi-host": RAPIDAPI_HOST,
        })
        j = json.loads(raw.decode("utf-8", errors="replace"))

        # Response: {"success": true, "src": [...], "title": "...", "thumbnail": "..."}
        if not j.get("success"):
            log.append(f"fail: rapidapi — {j.get('message', 'unknown error')}")
            return None

        sources = j.get("src", []) or []
        if not sources:
            log.append("fail: rapidapi — no sources")
            return None

        log.append(f"success: rapidapi — {len(sources)} source(s)")

        # Build links dict — each src has {url, quality, ext, size}
        links = {}
        for i, src in enumerate(sources):
            src_url = src.get("url")
            quality = src.get("quality") or src.get("ext") or f"stream_{i+1}"
            if src_url:
                links[str(quality)] = src_url

        return {
            "title":     j.get("title", "Video"),
            "thumbnail": j.get("thumbnail"),
            "duration":  format_duration(j.get("duration")),
            "links":     links,
        }
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:200]
        except Exception:
            pass
        log.append(f"fail: rapidapi HTTP {e.code} — {body}")
        return None
    except Exception as e:
        log.append(f"fail: rapidapi {type(e).__name__}: {str(e)[:100]}")
        return None


# ─────────────────────────────────────────────
#  cobalt.tools — universal fallback
# ─────────────────────────────────────────────
def cobalt_fetch(url: str, log: list) -> dict | None:
    log.append("trying: cobalt.tools")
    try:
        req_data = json.dumps({"url": url, "vQuality": "max"}).encode()
        req = urllib.request.Request(
            "https://api.cobalt.tools/",
            data=req_data,
            headers={
                **DEFAULT_HEADERS,
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://cobalt.tools",
                "Referer": "https://cobalt.tools/",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            j = json.loads(r.read().decode())
        status = j.get("status")
        if status in ("stream", "redirect", "tunnel") and j.get("url"):
            log.append("success: cobalt.tools")
            return {"video": j["url"]}
        if status == "picker":
            links = {f"video_{i+1}": p.get("url") for i, p in enumerate(j.get("picker", []))}
            log.append(f"success: cobalt.tools picker {len(links)} items")
            return links
        log.append(f"fail: cobalt status={status} error={j.get('error','')}")
    except Exception as e:
        log.append(f"fail: cobalt {type(e).__name__}: {str(e)[:80]}")
    return None


# ─────────────────────────────────────────────
#  TikTok
# ─────────────────────────────────────────────
def download_tiktok(url: str, log: list) -> dict:
    resolved = resolve_url(url)
    if resolved != url:
        log.append(f"resolved: {url} → {resolved}")
        url = resolved

    # 1. RapidAPI (primary)
    r = rapidapi_download(url, log)
    if r:
        return {"platform": "tiktok", **r}

    # 2. tikwm.com
    log.append("trying: tikwm.com")
    try:
        j = fetch_json(
            f"https://www.tikwm.com/api/?url={urllib.parse.quote(url)}&hd=1",
            headers={"Referer": "https://www.tikwm.com/"}
        )
        if j.get("code") == 0 and j.get("data"):
            d = j["data"]
            if d.get("hdplay") or d.get("play"):
                log.append("success: tikwm.com")
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
        log.append(f"fail: tikwm code={j.get('code')}")
    except Exception as e:
        log.append(f"fail: tikwm {e}")

    # 3. cobalt.tools
    links = cobalt_fetch(url, log)
    if links:
        return {"platform": "tiktok", "title": "TikTok Video", "links": links}

    # 4. savetik.net
    log.append("trying: savetik.net")
    try:
        raw = http_post(
            "https://savetik.net/api/ajaxSearch",
            {"q": url, "lang": "en"},
            {"Referer": "https://savetik.net/", "Origin": "https://savetik.net"},
        )
        j = json.loads(raw.decode())
        html = j.get("data", "")
        found = re.findall(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if found:
            log.append("success: savetik.net")
            return {"platform": "tiktok", "title": "TikTok Video", "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(found[:3])}}
        log.append("fail: savetik no links")
    except Exception as e:
        log.append(f"fail: savetik {e}")

    raise ValueError("TikTok: সকল API ব্যর্থ। (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Facebook
# ─────────────────────────────────────────────
def download_facebook(url: str, log: list) -> dict:
    resolved = resolve_url(url)
    if resolved != url:
        log.append(f"resolved: {url} → {resolved}")
        url = resolved

    # 1. RapidAPI (primary)
    r = rapidapi_download(url, log)
    if r:
        return {"platform": "facebook", **r}

    # 2. cobalt.tools
    links = cobalt_fetch(url, log)
    if links:
        return {"platform": "facebook", "title": "Facebook Video", "links": links}

    # 3. fdown.net
    log.append("trying: fdown.net")
    try:
        raw = http_post("https://fdown.net/download.php", {"URLz": url}, {"Referer": "https://fdown.net/"})
        html = raw.decode("utf-8", errors="replace")
        sd = re.search(r'id="sdlink"[^>]*href="([^"]+)"', html, re.I) or \
             re.search(r'href="([^"]+)"[^>]*id="sdlink"', html, re.I)
        hd = re.search(r'id="hdlink"[^>]*href="([^"]+)"', html, re.I) or \
             re.search(r'href="([^"]+)"[^>]*id="hdlink"', html, re.I)
        if sd:
            log.append("success: fdown.net")
            return {"platform": "facebook", "title": "Facebook Video", "links": {
                "sd": sd.group(1).replace("&amp;", "&"),
                "hd": hd.group(1).replace("&amp;", "&") if hd else None,
            }}
        log.append("fail: fdown no sdlink")
    except Exception as e:
        log.append(f"fail: fdown {e}")

    raise ValueError("Facebook: সকল API ব্যর্থ। ভিডিও Public আছে? (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Instagram
# ─────────────────────────────────────────────
def download_instagram(url: str, log: list) -> dict:

    # 1. RapidAPI (primary)
    r = rapidapi_download(url, log)
    if r:
        return {"platform": "instagram", **r}

    # 2. cobalt.tools
    links = cobalt_fetch(url, log)
    if links:
        title = "Instagram Carousel" if len(links) > 1 else "Instagram Video"
        return {"platform": "instagram", "title": title, "links": links}

    # 3. igram.world
    log.append("trying: igram.world")
    try:
        j = fetch_json(
            "https://igram.world/api/convert",
            {"url": url, "lang": "en"},
            {"Referer": "https://igram.world/"},
        )
        media = j.get("media", [])
        if media:
            log.append("success: igram.world")
            return {"platform": "instagram", "title": "Instagram Video", "links": {f"video_{i+1}": item.get("url") for i, item in enumerate(media)}}
        log.append("fail: igram no media")
    except Exception as e:
        log.append(f"fail: igram {e}")

    raise ValueError("Instagram: সকল API ব্যর্থ। Profile Private? (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  YouTube
# ─────────────────────────────────────────────
def download_youtube(url: str, log: list) -> dict:

    # 1. RapidAPI (primary)
    r = rapidapi_download(url, log)
    if r:
        return {"platform": "youtube", **r}

    # 2. cobalt.tools
    links = cobalt_fetch(url, log)
    if links:
        return {"platform": "youtube", "title": "YouTube Video", "links": links}

    # 3. yt5s.io
    log.append("trying: yt5s.io")
    try:
        j = fetch_json(
            "https://yt5s.io/api/ajaxSearch",
            {"q": url, "lang": "en"},
            {"Referer": "https://yt5s.io/", "Origin": "https://yt5s.io"},
        )
        if j.get("links"):
            links = {}
            for quality, info in j["links"].get("mp4", {}).items():
                if isinstance(info, dict) and info.get("url"):
                    links[f"mp4_{quality}"] = info["url"]
            if links:
                log.append("success: yt5s.io")
                return {"platform": "youtube", "title": j.get("title", "YouTube Video"), "links": links}
        log.append("fail: yt5s no links")
    except Exception as e:
        log.append(f"fail: yt5s {e}")

    raise ValueError("YouTube: সকল API ব্যর্থ। (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Twitter / X
# ─────────────────────────────────────────────
def download_twitter(url: str, log: list) -> dict:

    # 1. RapidAPI (primary)
    r = rapidapi_download(url, log)
    if r:
        return {"platform": "twitter", **r}

    # 2. cobalt.tools
    links = cobalt_fetch(url, log)
    if links:
        return {"platform": "twitter", "title": "Twitter/X Video", "links": links}

    # 3. twitsave.com
    log.append("trying: twitsave.com")
    try:
        raw = http_get(f"https://twitsave.com/info?url={urllib.parse.quote(url)}", {"Referer": "https://twitsave.com/"})
        html = raw.decode("utf-8", errors="replace")
        found = re.findall(r'href="(https://video\.twimg\.com/[^"]+\.mp4[^"]*)"', html)
        if found:
            log.append("success: twitsave.com")
            return {"platform": "twitter", "title": "Twitter/X Video", "links": {f"quality_{i+1}": l for i, l in enumerate(found)}}
        log.append("fail: twitsave no mp4")
    except Exception as e:
        log.append(f"fail: twitsave {e}")

    raise ValueError("Twitter/X: ভিডিও পাওয়া যায়নি। (?debug=1 দিয়ে details দেখুন)")


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

def process(url: str, platform_override: str = None, debug: bool = False) -> tuple:
    if not url:
        return err("url parameter আবশ্যক", 400)

    log = []

    resolved = resolve_url(url)
    platform = platform_override or detect_platform(resolved) or detect_platform(url)

    if not platform:
        return err("Unsupported platform. Supported: tiktok, facebook, instagram, youtube, twitter", 400, log if debug else None)

    handler = HANDLERS.get(platform)
    if not handler:
        return err(f"Platform '{platform}' এখনো সাপোর্ট নেই", 400, log if debug else None)

    try:
        result = handler(url, log)
        return ok(result, log if debug else None)
    except ValueError as e:
        return err(str(e), 422, log if debug else None)
    except Exception as e:
        return err(f"Internal error: {str(e)}", 500, log if debug else None)


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
        debug    = (params.get("debug") or [""])[0] == "1"
        status, body = process(url, platform, debug)
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
        debug    = str(data.get("debug", "")) == "1"
        status, body = process(url, platform, debug)
        self.send_json(status, body)
