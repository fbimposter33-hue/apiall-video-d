from http.server import BaseHTTPRequestHandler
import json
import urllib.request
import urllib.parse
import urllib.error
import re

# ─────────────────────────────────────────────
#  Config
# ─────────────────────────────────────────────
RAPIDAPI_KEY = "93e8e0c16bmsh216466a3573b948p1a4dbdjsn3069b3e2d6c0"

# TikTok dedicated API (tiktok-video-no-watermark6) — 100% uptime, freemium
TIKTOK_API_HOST = "tiktok-video-no-watermark6.p.rapidapi.com"

# Multi-platform API (all-socials-downloader) — Facebook, Instagram, YouTube, Twitter
MULTI_API_HOST  = "all-socials-downloader.p.rapidapi.com"

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
TIMEOUT = 10

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

def format_duration(s):
    if not s:
        return None
    try:
        m, sec = divmod(int(s), 60)
        return f"{m}:{sec:02d}"
    except Exception:
        return None


# ─────────────────────────────────────────────
#  API 1 — TikTok dedicated
#  tiktok-video-no-watermark6 (100% uptime, freemium)
#  Endpoint: GET /tik?url=...
# ─────────────────────────────────────────────
def api_tiktok_dedicated(url: str, log: list) -> dict | None:
    log.append("trying: tiktok-video-no-watermark6 (rapidapi)")
    try:
        api_url = f"https://{TIKTOK_API_HOST}/tik?url={urllib.parse.quote(url, safe='')}"
        raw = http_get(api_url, {
            "x-rapidapi-key":  RAPIDAPI_KEY,
            "x-rapidapi-host": TIKTOK_API_HOST,
        })
        j = json.loads(raw.decode("utf-8", errors="replace"))

        # Response: {"code": 0, "data": {"play": "...", "hdplay": "...", "wmplay": "...", "music": "...", "title": "...", "cover": "..."}}
        if j.get("code") != 0 or not j.get("data"):
            log.append(f"fail: tiktok-api code={j.get('code')} msg={j.get('msg','')}")
            return None

        d = j["data"]
        links = {}
        if d.get("hdplay"):  links["hd_no_watermark"] = d["hdplay"]
        if d.get("play"):    links["sd_no_watermark"] = d["play"]
        if d.get("wmplay"):  links["watermark"]       = d["wmplay"]
        if d.get("music"):   links["audio"]            = d["music"]

        if not links:
            log.append("fail: tiktok-api no links")
            return None

        log.append(f"success: tiktok-video-no-watermark6 — {len(links)} link(s)")
        return {
            "title":     d.get("title", "TikTok Video"),
            "thumbnail": d.get("cover"),
            "duration":  format_duration(d.get("duration")),
            "author":    d.get("author", {}).get("nickname") if isinstance(d.get("author"), dict) else d.get("author"),
            "links":     links,
        }
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode()[:200]
        except Exception: pass
        log.append(f"fail: tiktok-api HTTP {e.code} — {body}")
        return None
    except Exception as e:
        log.append(f"fail: tiktok-api {type(e).__name__}: {str(e)[:100]}")
        return None


# ─────────────────────────────────────────────
#  API 2 — tikwm.com (TikTok fallback)
# ─────────────────────────────────────────────
def api_tikwm(url: str, log: list) -> dict | None:
    log.append("trying: tikwm.com")
    try:
        api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url, safe='')}&hd=1"
        j = fetch_json(api_url, headers={"Referer": "https://www.tikwm.com/"})
        if j.get("code") == 0 and j.get("data"):
            d = j["data"]
            if d.get("hdplay") or d.get("play"):
                links = {}
                if d.get("hdplay"):  links["hd_no_watermark"] = d["hdplay"]
                if d.get("play"):    links["sd_no_watermark"] = d["play"]
                if d.get("wmplay"):  links["watermark"]       = d["wmplay"]
                if d.get("music"):   links["audio"]            = d["music"]
                log.append("success: tikwm.com")
                return {
                    "title":     d.get("title", "TikTok Video"),
                    "thumbnail": d.get("cover"),
                    "duration":  format_duration(d.get("duration")),
                    "author":    d.get("author", {}).get("nickname") if isinstance(d.get("author"), dict) else None,
                    "links":     links,
                }
        log.append(f"fail: tikwm code={j.get('code')} msg={j.get('msg','')}")
    except Exception as e:
        log.append(f"fail: tikwm {type(e).__name__}: {str(e)[:80]}")
    return None


# ─────────────────────────────────────────────
#  API 3 — all-socials-downloader (multi-platform)
#  Supports: Facebook, Instagram, YouTube, Twitter
#  Endpoint: GET /download?url=...
# ─────────────────────────────────────────────
def api_all_socials(url: str, platform: str, log: list) -> dict | None:
    log.append(f"trying: all-socials-downloader (rapidapi) [{platform}]")
    try:
        api_url = f"https://{MULTI_API_HOST}/download?url={urllib.parse.quote(url, safe='')}"
        raw = http_get(api_url, {
            "x-rapidapi-key":  RAPIDAPI_KEY,
            "x-rapidapi-host": MULTI_API_HOST,
        })
        j = json.loads(raw.decode("utf-8", errors="replace"))

        # Try multiple common response shapes
        medias = j.get("medias") or j.get("data") or j.get("links") or j.get("result") or []

        links = {}
        if isinstance(medias, list):
            for i, item in enumerate(medias):
                if isinstance(item, dict):
                    u = item.get("url") or item.get("src") or item.get("link")
                    q = item.get("quality") or item.get("ext") or item.get("type") or f"stream_{i+1}"
                    if u:
                        links[str(q)] = u
        elif isinstance(medias, dict):
            for k, v in medias.items():
                if isinstance(v, str) and v.startswith("http"):
                    links[k] = v
                elif isinstance(v, dict):
                    u = v.get("url") or v.get("link")
                    if u:
                        links[k] = u

        # Also check top-level url field
        if not links and j.get("url"):
            links["video_1"] = j["url"]

        if not links:
            log.append(f"fail: all-socials no links — keys={list(j.keys())[:5]}")
            return None

        log.append(f"success: all-socials-downloader — {len(links)} link(s)")
        return {
            "title":     j.get("title") or j.get("name") or f"{platform.title()} Video",
            "thumbnail": j.get("thumbnail") or j.get("thumb") or j.get("picture"),
            "duration":  format_duration(j.get("duration")),
            "links":     links,
        }
    except urllib.error.HTTPError as e:
        body = ""
        try: body = e.read().decode()[:200]
        except Exception: pass
        log.append(f"fail: all-socials HTTP {e.code} — {body}")
        return None
    except Exception as e:
        log.append(f"fail: all-socials {type(e).__name__}: {str(e)[:100]}")
        return None


# ─────────────────────────────────────────────
#  TikTok handler
# ─────────────────────────────────────────────
def download_tiktok(url: str, log: list) -> dict:
    resolved = resolve_url(url)
    if resolved != url:
        log.append(f"resolved: {url} → {resolved}")
        url = resolved

    # 1. TikTok dedicated API (primary)
    r = api_tiktok_dedicated(url, log)
    if r:
        return {"platform": "tiktok", **r}

    # 2. tikwm.com
    r = api_tikwm(url, log)
    if r:
        return {"platform": "tiktok", **r}

    # 3. fdown/ssstik fallback
    log.append("trying: ssstik.io")
    try:
        raw = http_post(
            "https://ssstik.io/abc?url=dl",
            {"id": url, "locale": "en", "tt": ""},
            {"Referer": "https://ssstik.io/en", "Origin": "https://ssstik.io"},
        )
        html = raw.decode("utf-8", errors="replace")
        found = re.findall(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if found:
            log.append("success: ssstik.io")
            return {"platform": "tiktok", "title": "TikTok Video", "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(found[:3])}}
        log.append("fail: ssstik no links")
    except Exception as e:
        log.append(f"fail: ssstik {type(e).__name__}: {str(e)[:80]}")

    raise ValueError("TikTok: সকল API ব্যর্থ। (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Facebook handler
# ─────────────────────────────────────────────
def download_facebook(url: str, log: list) -> dict:
    resolved = resolve_url(url)
    if resolved != url:
        log.append(f"resolved: {url} → {resolved}")
        url = resolved

    # 1. all-socials-downloader
    r = api_all_socials(url, "facebook", log)
    if r:
        return {"platform": "facebook", **r}

    # 2. fdown.net
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
        log.append(f"fail: fdown {type(e).__name__}: {str(e)[:80]}")

    # 3. getfvid.com
    log.append("trying: getfvid.com")
    try:
        raw = http_post("https://www.getfvid.com/downloader", {"url": url}, {"Referer": "https://www.getfvid.com/"})
        html = raw.decode("utf-8", errors="replace")
        found = re.findall(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if found:
            log.append("success: getfvid.com")
            return {"platform": "facebook", "title": "Facebook Video", "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(found[:2])}}
        log.append("fail: getfvid no mp4")
    except Exception as e:
        log.append(f"fail: getfvid {type(e).__name__}: {str(e)[:80]}")

    raise ValueError("Facebook: সকল API ব্যর্থ। ভিডিও Public আছে? (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Instagram handler
# ─────────────────────────────────────────────
def download_instagram(url: str, log: list) -> dict:

    # 1. all-socials-downloader
    r = api_all_socials(url, "instagram", log)
    if r:
        return {"platform": "instagram", **r}

    # 2. snapinsta.app
    log.append("trying: snapinsta.app")
    try:
        token_raw = http_get("https://snapinsta.app/", {"Referer": "https://snapinsta.app/"})
        token_html = token_raw.decode("utf-8", errors="replace")
        token_match = re.search(r'name="_token"\s+value="([^"]+)"', token_html)
        if token_match:
            token = token_match.group(1)
            raw = http_post(
                "https://snapinsta.app/action.php",
                {"url": url, "_token": token},
                {"Referer": "https://snapinsta.app/", "Origin": "https://snapinsta.app"},
            )
            j = json.loads(raw.decode("utf-8", errors="replace"))
            media = j.get("data", [])
            if media:
                links_dict = {}
                for i, item in enumerate(media if isinstance(media, list) else [media]):
                    item_url = item.get("url") or item.get("src") if isinstance(item, dict) else None
                    if item_url:
                        links_dict[f"video_{i+1}"] = item_url
                if links_dict:
                    log.append("success: snapinsta.app")
                    return {"platform": "instagram", "title": "Instagram Video", "links": links_dict}
        log.append("fail: snapinsta no media")
    except Exception as e:
        log.append(f"fail: snapinsta {type(e).__name__}: {str(e)[:80]}")

    # 3. indown.io
    log.append("trying: indown.io")
    try:
        token_raw = http_get("https://indown.io/", {"Referer": "https://indown.io/"})
        token_html = token_raw.decode("utf-8", errors="replace")
        token_match = re.search(r'name="referer"\s+value="([^"]+)"', token_html) or \
                      re.search(r'name="_token"\s+value="([^"]+)"', token_html)
        if token_match:
            raw = http_post(
                "https://indown.io/download",
                {"url": url, "referer": token_match.group(1), "locale": "en"},
                {"Referer": "https://indown.io/", "Origin": "https://indown.io"},
            )
            html = raw.decode("utf-8", errors="replace")
            found = re.findall(r'href="(https?://[^"]+(?:\.mp4|\.jpg|cdninstagram)[^"]*)"', html, re.I)
            if found:
                log.append("success: indown.io")
                return {"platform": "instagram", "title": "Instagram Video", "links": {f"media_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(found[:4])}}
        log.append("fail: indown no links")
    except Exception as e:
        log.append(f"fail: indown {type(e).__name__}: {str(e)[:80]}")

    raise ValueError("Instagram: সকল API ব্যর্থ। Profile Private? (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  YouTube handler
# ─────────────────────────────────────────────
def download_youtube(url: str, log: list) -> dict:

    # 1. all-socials-downloader
    r = api_all_socials(url, "youtube", log)
    if r:
        return {"platform": "youtube", **r}

    # 2. yt5s.io
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
                return {"platform": "youtube", "title": j.get("title", "YouTube Video"), "thumbnail": j.get("thumbnail"), "links": links}
        log.append("fail: yt5s no links")
    except Exception as e:
        log.append(f"fail: yt5s {type(e).__name__}: {str(e)[:80]}")

    # 3. loader.to
    log.append("trying: loader.to")
    try:
        j = fetch_json(
            f"https://loader.to/api/button/?url={urllib.parse.quote(url)}&f=mp4",
            headers={"Referer": "https://loader.to/"},
        )
        if j.get("success") and j.get("id"):
            # Poll for download link
            dl_url = f"https://loader.to/api/info/?id={j['id']}"
            for _ in range(3):
                import time; time.sleep(2)
                info = fetch_json(dl_url)
                if info.get("download_url"):
                    log.append("success: loader.to")
                    return {"platform": "youtube", "title": "YouTube Video", "links": {"mp4": info["download_url"]}}
        log.append("fail: loader.to no link")
    except Exception as e:
        log.append(f"fail: loader.to {type(e).__name__}: {str(e)[:80]}")

    raise ValueError("YouTube: সকল API ব্যর্থ। (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Twitter / X handler
# ─────────────────────────────────────────────
def download_twitter(url: str, log: list) -> dict:

    # 1. all-socials-downloader
    r = api_all_socials(url, "twitter", log)
    if r:
        return {"platform": "twitter", **r}

    # 2. twitsave.com
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
        log.append(f"fail: twitsave {type(e).__name__}: {str(e)[:80]}")

    # 3. sxtwitter.com / vxtwitter.com
    log.append("trying: vxtwitter.com")
    try:
        vx_url = url.replace("twitter.com", "vxtwitter.com").replace("x.com", "vxtwitter.com")
        raw = http_get(vx_url, {"Referer": "https://vxtwitter.com/"})
        html = raw.decode("utf-8", errors="replace")
        found = re.findall(r'<meta\s+property="og:video(?::url)?"\s+content="([^"]+)"', html, re.I)
        if found:
            log.append("success: vxtwitter.com")
            return {"platform": "twitter", "title": "Twitter/X Video", "links": {"video_1": found[0]}}
        log.append("fail: vxtwitter no video meta")
    except Exception as e:
        log.append(f"fail: vxtwitter {type(e).__name__}: {str(e)[:80]}")

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
