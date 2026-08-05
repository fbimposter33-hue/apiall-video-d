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
#  Platform detection — fixed patterns
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
#  Short URL resolver (vm.tiktok, fb.watch etc)
# ─────────────────────────────────────────────
SHORT_DOMAINS = re.compile(r"(vm\.tiktok\.com|vt\.tiktok\.com|fb\.watch|fb\.gg|bit\.ly|tinyurl\.com|t\.co)", re.I)

def resolve_url(url: str, timeout: int = 5) -> str:
    """Follow redirects to get final URL. Max 5 hops."""
    if not SHORT_DOMAINS.search(url):
        return url
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            method="HEAD",
        )
        opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
        with opener.open(req, timeout=timeout) as r:
            return r.url
    except Exception:
        try:
            req2 = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req2, timeout=timeout) as r:
                return r.url
        except Exception:
            return url


# ─────────────────────────────────────────────
#  HTTP helpers — Vercel-safe 8s timeout
# ─────────────────────────────────────────────
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 8  # Vercel free plan safe limit

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

def cobalt_fetch(url: str) -> dict | None:
    """Shared cobalt.tools call — used by multiple platforms."""
    try:
        req_data = json.dumps({"url": url, "vQuality": "max"}).encode()
        req = urllib.request.Request(
            "https://api.cobalt.tools/",
            data=req_data,
            headers={**DEFAULT_HEADERS, "Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            j = json.loads(r.read().decode())
        status = j.get("status")
        if status in ("stream", "redirect", "tunnel") and j.get("url"):
            return {"video": j["url"]}
        if status == "picker":
            return {f"video_{i+1}": p.get("url") for i, p in enumerate(j.get("picker", []))}
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────
#  TikTok
# ─────────────────────────────────────────────
def download_tiktok(url: str, log: list) -> dict:
    # Resolve short URLs first
    resolved = resolve_url(url)
    if resolved != url:
        log.append(f"resolved: {url} → {resolved}")
        url = resolved

    # 1. tikwm.com
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
        log.append(f"fail: tikwm code={j.get('code')} msg={j.get('msg','')}")
    except Exception as e:
        log.append(f"fail: tikwm {e}")

    # 2. cobalt.tools
    log.append("trying: cobalt.tools")
    links = cobalt_fetch(url)
    if links:
        log.append("success: cobalt.tools")
        return {"platform": "tiktok", "title": "TikTok Video", "links": links}
    log.append("fail: cobalt.tools")

    # 3. ssstik.io
    log.append("trying: ssstik.io")
    try:
        raw = http_post(
            "https://ssstik.io/abc?lang=en",
            {"id": url, "locale": "en", "tt": ""},
            {"Referer": "https://ssstik.io/en", "Origin": "https://ssstik.io"},
        )
        html = raw.decode("utf-8", errors="replace")
        m = re.search(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if m:
            log.append("success: ssstik.io")
            return {"platform": "tiktok", "title": "TikTok Video", "links": {"no_watermark": m.group(1).replace("&amp;", "&")}}
        log.append("fail: ssstik no mp4 found")
    except Exception as e:
        log.append(f"fail: ssstik {e}")

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
        links = re.findall(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if links:
            log.append("success: savetik.net")
            return {"platform": "tiktok", "title": "TikTok Video", "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(links[:3])}}
        log.append("fail: savetik no links")
    except Exception as e:
        log.append(f"fail: savetik {e}")

    # 5. snaptik fallback
    log.append("trying: snaptik.app")
    try:
        raw = http_post(
            "https://snaptik.app/abc2.php",
            {"url": url, "lang": "en"},
            {"Referer": "https://snaptik.app/"},
        )
        html = raw.decode("utf-8", errors="replace")
        m = re.search(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if m:
            log.append("success: snaptik.app")
            return {"platform": "tiktok", "title": "TikTok Video", "links": {"sd_no_watermark": m.group(1).replace("&amp;", "&")}}
        log.append("fail: snaptik no mp4")
    except Exception as e:
        log.append(f"fail: snaptik {e}")

    raise ValueError("TikTok: সকল API ব্যর্থ হয়েছে। লিংক সঠিক আছে? (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Facebook — fixed Reels + fb.watch
# ─────────────────────────────────────────────
def download_facebook(url: str, log: list) -> dict:
    # Resolve fb.watch / fb.gg short URLs
    resolved = resolve_url(url)
    if resolved != url:
        log.append(f"resolved: {url} → {resolved}")
        url = resolved

    # 1. cobalt.tools (handles Reels well)
    log.append("trying: cobalt.tools")
    links = cobalt_fetch(url)
    if links:
        log.append("success: cobalt.tools")
        return {"platform": "facebook", "title": "Facebook Video", "links": links}
    log.append("fail: cobalt.tools")

    # 2. fdown.net
    log.append("trying: fdown.net")
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
            log.append("success: fdown.net")
            return {
                "platform": "facebook",
                "title": "Facebook Video",
                "links": {
                    "sd": sd.group(1).replace("&amp;", "&"),
                    "hd": hd.group(1).replace("&amp;", "&") if hd else None,
                },
            }
        log.append("fail: fdown no sdlink")
    except Exception as e:
        log.append(f"fail: fdown {e}")

    # 3. getfvid.com
    log.append("trying: getfvid.com")
    try:
        j = fetch_json(f"https://getfvid.com/api?url={urllib.parse.quote(url)}&format=json")
        if j.get("links", {}).get("sd"):
            log.append("success: getfvid.com")
            return {
                "platform": "facebook",
                "title": j.get("title", "Facebook Video"),
                "links": {"sd": j["links"]["sd"], "hd": j["links"].get("hd")},
            }
        log.append(f"fail: getfvid {j.get('error','no sd link')}")
    except Exception as e:
        log.append(f"fail: getfvid {e}")

    # 4. fbdownloader.com
    log.append("trying: fbdownloader.com")
    try:
        j = fetch_json(
            "https://fbdownloader.com/api/data",
            {"url": url},
            {"X-Requested-With": "XMLHttpRequest", "Referer": "https://fbdownloader.com/"},
        )
        link = j.get("sd") or j.get("url")
        if link:
            log.append("success: fbdownloader.com")
            return {"platform": "facebook", "title": j.get("title", "Facebook Video"), "links": {"sd": link.replace("&amp;", "&")}}
        log.append(f"fail: fbdownloader no link")
    except Exception as e:
        log.append(f"fail: fbdownloader {e}")

    raise ValueError("Facebook: সকল API ব্যর্থ। ভিডিও কি Public আছে? (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Instagram — cobalt primary + Stories support
# ─────────────────────────────────────────────
def download_instagram(url: str, log: list) -> dict:

    # 1. cobalt.tools (primary)
    log.append("trying: cobalt.tools")
    links = cobalt_fetch(url)
    if links:
        log.append("success: cobalt.tools")
        title = "Instagram Carousel" if len(links) > 1 else "Instagram Video"
        return {"platform": "instagram", "title": title, "links": links}
    log.append("fail: cobalt.tools")

    # 2. instavideosave.net
    log.append("trying: instavideosave.net")
    try:
        raw = http_post(
            "https://instavideosave.net/",
            {"url": url},
            {"Referer": "https://instavideosave.net/"},
        )
        html = raw.decode("utf-8", errors="replace")
        m = re.search(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if m:
            log.append("success: instavideosave.net")
            return {"platform": "instagram", "title": "Instagram Video", "links": {"video": m.group(1).replace("&amp;", "&")}}
        log.append("fail: instavideosave no mp4")
    except Exception as e:
        log.append(f"fail: instavideosave {e}")

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
            links = {f"video_{i+1}": item.get("url") for i, item in enumerate(media)}
            return {"platform": "instagram", "title": "Instagram Video", "links": links}
        log.append(f"fail: igram no media")
    except Exception as e:
        log.append(f"fail: igram {e}")

    # 4. snapinsta.app
    log.append("trying: snapinsta.app")
    try:
        raw = http_post(
            "https://snapinsta.app/action.php",
            {"url": url},
            {"Referer": "https://snapinsta.app/"},
        )
        j = json.loads(raw.decode())
        if j.get("url"):
            log.append("success: snapinsta.app")
            return {"platform": "instagram", "title": "Instagram Video", "links": {"video": j["url"]}}
        log.append(f"fail: snapinsta no url")
    except Exception as e:
        log.append(f"fail: snapinsta {e}")

    # 5. saveinsta.app
    log.append("trying: saveinsta.app")
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
            log.append("success: saveinsta.app")
            return {"platform": "instagram", "title": "Instagram Video", "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(links[:3])}}
        log.append("fail: saveinsta no links")
    except Exception as e:
        log.append(f"fail: saveinsta {e}")

    raise ValueError("Instagram: সকল API ব্যর্থ। Profile কি Private? (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  YouTube — cobalt primary, direct links
# ─────────────────────────────────────────────
def download_youtube(url: str, log: list) -> dict:

    # 1. cobalt.tools (direct link)
    log.append("trying: cobalt.tools")
    links = cobalt_fetch(url)
    if links:
        log.append("success: cobalt.tools")
        return {"platform": "youtube", "title": "YouTube Video", "links": links}
    log.append("fail: cobalt.tools")

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
                return {"platform": "youtube", "title": j.get("title", "YouTube Video"), "links": links}
        log.append("fail: yt5s no links")
    except Exception as e:
        log.append(f"fail: yt5s {e}")

    # 3. y2mate (returns metadata + k key, not direct link)
    log.append("trying: y2mate.com")
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
                        links[f"{fmt}_{quality}"] = {
                            "quality": info.get("q"),
                            "size": info.get("size"),
                            "k": info.get("k"),
                        }
            if links:
                log.append("success: y2mate.com (metadata only)")
                return {
                    "platform": "youtube",
                    "title": j.get("title", "YouTube Video"),
                    "thumbnail": j.get("thumbnail"),
                    "vid": j.get("vid"),
                    "note": "⚠️ y2mate returns metadata only. Use k+vid to get direct link.",
                    "links_meta": links,
                }
        log.append(f"fail: y2mate status={j.get('status')}")
    except Exception as e:
        log.append(f"fail: y2mate {e}")

    raise ValueError("YouTube: সকল API ব্যর্থ। কিছুক্ষণ পরে আবার চেষ্টা করুন। (?debug=1 দিয়ে details দেখুন)")


# ─────────────────────────────────────────────
#  Twitter / X
# ─────────────────────────────────────────────
def download_twitter(url: str, log: list) -> dict:

    # 1. cobalt.tools
    log.append("trying: cobalt.tools")
    links = cobalt_fetch(url)
    if links:
        log.append("success: cobalt.tools")
        return {"platform": "twitter", "title": "Twitter/X Video", "links": links}
    log.append("fail: cobalt.tools")

    # 2. twitsave.com
    log.append("trying: twitsave.com")
    try:
        raw = http_get(
            f"https://twitsave.com/info?url={urllib.parse.quote(url)}",
            {"Referer": "https://twitsave.com/"},
        )
        html = raw.decode("utf-8", errors="replace")
        links_found = re.findall(r'href="(https://video\.twimg\.com/[^"]+\.mp4[^"]*)"', html)
        if links_found:
            log.append("success: twitsave.com")
            return {"platform": "twitter", "title": "Twitter/X Video", "links": {f"quality_{i+1}": l for i, l in enumerate(links_found)}}
        log.append("fail: twitsave no mp4")
    except Exception as e:
        log.append(f"fail: twitsave {e}")

    # 3. twittervideodownloader.com
    log.append("trying: twittervideodownloader.com")
    try:
        raw = http_post(
            "https://twittervideodownloader.com/download",
            {"tweet": url},
            {"Referer": "https://twittervideodownloader.com/", "Origin": "https://twittervideodownloader.com"},
        )
        html = raw.decode("utf-8", errors="replace")
        links_found = re.findall(r'href="(https?://[^"]+\.mp4[^"]*)"', html, re.I)
        if links_found:
            log.append("success: twittervideodownloader.com")
            return {"platform": "twitter", "title": "Twitter/X Video", "links": {f"video_{i+1}": l.replace("&amp;", "&") for i, l in enumerate(links_found[:3])}}
        log.append("fail: twittervideodownloader no mp4")
    except Exception as e:
        log.append(f"fail: twittervideodownloader {e}")

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

    log = [] if debug else None

    # Resolve short URLs for platform detection
    resolved = resolve_url(url)
    platform = platform_override or detect_platform(resolved) or detect_platform(url)

    if not platform:
        return err(
            "Unsupported platform. Supported: tiktok, facebook, instagram, youtube, twitter",
            400, log
        )

    handler = HANDLERS.get(platform)
    if not handler:
        return err(f"Platform '{platform}' এখনো সাপোর্ট নেই", 400, log)

    try:
        result = handler(url, log if log is not None else [])
        return ok(result, log)
    except ValueError as e:
        return err(str(e), 422, log)
    except Exception as e:
        return err(f"Internal error: {str(e)}", 500, log)


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
        debug    = str(data.get("debug", "")).strip() == "1"
        status, body = process(url, platform, debug)
        self.send_json(status, body)
