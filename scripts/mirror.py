#!/usr/bin/env python3
"""Copia o HTML público para public/, sem baixar nem executar PHP."""

import html as html_lib
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ORIGIN = "https://urologistaemcampogrande.com.br"
HOST = "urologistaemcampogrande.com.br"
SKIP_PARTS = ("/wp-admin/", "/wp-json", "/xmlrpc.php", "/feed", "/comments/")
ASSET_EXT = (
    ".css", ".js", ".mjs", ".json", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg",
    ".woff", ".woff2", ".ttf", ".eot", ".ico", ".avif", ".mp4", ".webm",
    ".mp3", ".m4a", ".wav", ".ogg", ".pdf",
)
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
TRUSTINDEX_CSS = (
    '<link rel="stylesheet" id="trustindex-widget-css" '
    'href="/wp-content/uploads/trustindex-google-widget.css" media="all" />'
)
SUSPICIOUS = re.compile(
    r"eval\s*\(\s*function\s*\(\s*p\s*,\s*a\s*,\s*c\s*,\s*k|"
    r"base64_decode|gzinflate|str_rot13|coinhive|cryptonight|"
    r"document\.write\s*\(\s*unescape",
    re.I,
)
OLD_SERVER = re.compile(
    r"background-image\s*:\s*url\(\s*[\"']?https?://srv\d+\.wemarketingdigital\.com\.br[^)\"']*[\"']?\s*\)\s*;?",
    re.I,
)
CTX = ssl.create_default_context()
TITLE_SUFFIXES: list[str] = []
HOSTS: set[str] = set()


def configure_hosts() -> None:
    global HOSTS
    bare = HOST.removeprefix("www.")
    HOSTS = {HOST, bare, "www." + bare}


def fetch(url: str):
    last = None
    for attempt in range(4):
        req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
        try:
            with urllib.request.urlopen(req, context=CTX, timeout=60) as response:
                data = response.read()
                final = response.geturl()
                ctype = response.headers.get("Content-Type", "")
            return data, final if final else url, ctype
        except urllib.error.HTTPError as error:
            data = error.read()
            ctype = error.headers.get("Content-Type", "") or ""
            if error.code == 403 and b"<html" in data[:800].lower():
                return data, url, ctype
            last = error
            if error.code not in (429, 502, 503, 504) or attempt == 3:
                raise
        except Exception as error:
            last = error
            if attempt == 3:
                raise
        time.sleep(4 * (attempt + 1))
    raise last


def load_pages() -> list[str]:
    index = ""
    for path in ("/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap.xml"):
        try:
            data, _, _ = fetch(ORIGIN + path)
        except Exception:
            continue
        text = data.decode("utf-8", "replace")
        if "<loc>" in text and ("<sitemapindex" in text or "<urlset" in text):
            index = text
            break
    pages = []
    if index:
        for loc in re.findall(r"<loc>(.*?)</loc>", index):
            loc = html_lib.unescape(loc.strip())
            path = urllib.parse.urlparse(loc).path.lower()
            if path.endswith(".xml") or "sitemap" in path:
                try:
                    child, _, _ = fetch(loc)
                except Exception as error:
                    print(f"fail sitemap {loc} {error}", flush=True)
                    continue
                pages.extend(
                    html_lib.unescape(item.strip())
                    for item in re.findall(r"<loc>(.*?)</loc>", child.decode("utf-8", "replace"))
                )
            else:
                pages.append(loc)
    ordered = []
    seen = set()
    for page in [ORIGIN + "/"] + pages:
        clean = page if page.endswith("/") else page + "/"
        if clean in seen:
            continue
        seen.add(clean)
        ordered.append(clean)
    return ordered


def same_origin(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.netloc in HOSTS


def strip_query(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return urllib.parse.urlunparse(parsed._replace(query="", fragment=""))


def should_skip(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    if path.endswith(".php") or any(part in path for part in SKIP_PARTS):
        return True
    return False


def local_path(url: str) -> Path:
    path = urllib.parse.urlparse(strip_query(url)).path
    if path.endswith("/"):
        path += "index.html"
    return PUBLIC / path.lstrip("/")


def extract_urls(text: str, base: str) -> set[str]:
    found = set()
    patterns = [
        r"""(?:href|src|poster|data-src|data-lazy-src)=["']([^"']+)["']""",
        r"""srcset=["']([^"']+)["']""",
        r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""",
        rf"""https:\\/\\/{re.escape(HOST)}\\/[^"\\\s]+""",
    ]
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.I):
            chunk = match.replace("\\/", "/")
            if pattern.startswith("srcset"):
                pieces = [part.strip().split(" ")[0] for part in chunk.split(",")]
            else:
                pieces = [chunk]
            for piece in pieces:
                if not piece or piece.startswith(("data:", "mailto:", "tel:", "javascript:", "#")):
                    continue
                absolute = urllib.parse.urljoin(base, piece)
                found.add(absolute.split("#")[0])
    for match in re.findall(r"[\w./-]+\.bundle\.min\.js", text):
        found.add(urllib.parse.urljoin(base, match))
    for match in re.findall(
        r"/wp-content/uploads/[^\"'\\s>]+\.(?:json|css|js|mjs|png|jpe?g|gif|webp|svg|woff2?|avif|mp4)",
        text,
        flags=re.I,
    ):
        found.add(urllib.parse.urljoin(base, match))
    for match in re.findall(
        r"\\/wp-content\\/uploads\\/(?:[A-Za-z0-9_.-]+\\/)*[A-Za-z0-9_.-]+\.json",
        text,
    ):
        found.add(urllib.parse.urljoin(base, match.replace("\\/", "/")))
    return found


def fix_star_alts(html: str) -> str:
    number = 0

    def repl(match: re.Match) -> str:
        nonlocal number
        tag = match.group(0)
        alt = re.search(r'alt="([^"]*)"', tag)
        if not alt or alt.group(1) != "Google":
            return tag
        number += 1
        label = f"Google star {((number - 1) % 5) + 1}"
        return tag.replace('alt="Google"', f'alt="{label}"', 1)

    return re.sub(r'<img\b[^>]*\bclass="ti-star"[^>]*>', repl, html)


def strip_origin(text: str) -> str:
    for host in sorted(HOSTS, key=len, reverse=True):
        for scheme in ("https", "http"):
            escaped = scheme + ":\\/\\/" + host
            plain = scheme + "://" + host
            text = text.replace(plain + "//", "/")
            text = text.replace(escaped + "\\/\\/", "\\/")
            text = text.replace(escaped + "\\/", "\\/")
            text = text.replace(escaped, "\\/")
            text = text.replace(plain + "/", "/")
            text = text.replace(plain, "/")
        text = text.replace("//" + host + "/", "/")
        text = text.replace("\\/\\/" + host + "\\/", "\\/")
    text = text.replace("//wp-content/", "/wp-content/")
    text = text.replace("//wp-includes/", "/wp-includes/")
    text = text.replace("\\/\\/wp-content\\/", "\\/wp-content\\/")
    text = text.replace("\\/\\/wp-includes\\/", "\\/wp-includes\\/")
    return text


def page_title_from_html(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return ""
    title = html_lib.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    title = re.sub(r"\s+", " ", title).strip()
    for suffix in TITLE_SUFFIXES:
        if title.endswith(suffix):
            return title[: -len(suffix)].strip()
    return title


def plain_title(html: str) -> str:
    match = re.search(r"<title>(.*?)</title>", html, flags=re.I | re.S)
    if not match:
        return ""
    title = html_lib.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    return re.sub(r"\s+", " ", title).strip()


def detect_suffixes(htmls: list[str]) -> list[str]:
    titles = [plain_title(html) for html in htmls]
    titles = [title for title in titles if title]
    found = []
    for sep in (" – ", " — ", " | ", " - "):
        tails = [sep + title.rsplit(sep, 1)[1] for title in titles if sep in title]
        if not tails:
            continue
        suffix, count = Counter(tails).most_common(1)[0]
        if count >= 3 and count >= len(tails) * 0.6:
            found.append(suffix)
    return found


def replace_page_title(html: str) -> str:
    if "[page_title]" not in html and "&#91;page_title&#93;" not in html:
        return html
    title = page_title_from_html(html)
    if not title:
        return html
    safe = html_lib.escape(title, quote=False)
    return html.replace("[page_title]", safe).replace("&#91;page_title&#93;", safe)


def rewrite_html(html: str) -> str:
    html = replace_page_title(html)
    original_canonical = re.search(r'<link rel="canonical" href="([^"]*)"', html, flags=re.I)
    html = strip_origin(html)
    html = re.sub(r"<link[^>]+(?:xmlrpc\.php|/wp-json/|/feed/)[^>]*>", "", html, flags=re.I)
    html = re.sub(
        r'(<link rel="canonical" href=")/',
        lambda match: match.group(1) + ORIGIN + "/",
        html,
        flags=re.I,
    )
    if original_canonical and original_canonical.group(1).rstrip("/") == ORIGIN:
        html = re.sub(
            r'(<link rel="canonical" href=")[^"]*',
            lambda match: match.group(1) + original_canonical.group(1),
            html,
            count=1,
            flags=re.I,
        )
    html = OLD_SERVER.sub("", html)
    html = re.sub(
        r'<script\b[^>]*\bsrc="https://cdn\.trustindex\.io/loader\.js[^"]*"[^>]*>\s*</script>',
        "",
        html,
    )
    html = re.sub(
        r'<div\b[^>]*\bdata-src="https://cdn\.trustindex\.io/loader\.js\?wp-widget"[^>]*>\s*</div>',
        "",
        html,
    )
    html = re.sub(
        r'<pre class="ti-widget">([\s\S]*?)</pre>\s*<pre class="ti-hidden-markup"[^>]*>[\s\S]*?</pre>',
        r'<div class="ti-widget-slot">\1</div>',
        html,
        count=1,
    )
    html = re.sub(
        r'\sstyle="opacity:\s*0;\s*height:\s*0\s*!important;\s*overflow:\s*hidden\s*!important"',
        "",
        html,
    )
    html = re.sub(
        r'<script id="wp-emoji-settings"[\s\S]*?</script>\s*'
        r'<script type="module">[\s\S]*?wp-emoji-loader\.min\.js\s*</script>',
        "",
        html,
        count=1,
    )
    html = fix_star_alts(html)
    if "ti-widget" in html and not re.search(r"<link\b[^>]*trustindex-google-widget\.css", html):
        html = html.replace("</head>", TRUSTINDEX_CSS + "\n</head>", 1)
    return restore_public_urls(html)


def restore_public_urls(html: str) -> str:
    """Devolve o domínio só na prévia de link e nos dados estruturados."""

    def meta(match: re.Match) -> str:
        prop, value = match.group(1), match.group(2)
        if value.startswith("/") and not value.startswith("//"):
            value = ORIGIN + value
        return f'<meta property="{prop}" content="{value}"'

    html = re.sub(
        r'<meta property="(og:url|og:image|og:image:secure_url)" content="([^"]*)"',
        meta,
        html,
    )

    def twitter(match: re.Match) -> str:
        value = match.group(1)
        if value.startswith("/") and not value.startswith("//"):
            value = ORIGIN + value
        return f'<meta name="twitter:image" content="{value}"'

    html = re.sub(r'<meta name="twitter:image" content="([^"]*)"', twitter, html)

    def schema(match: re.Match) -> str:
        block = re.sub(r'"/(?!/)', f'"{ORIGIN}/', match.group(0))
        return re.sub(r'"\\/(?!\\/)', '"' + ORIGIN.replace("/", "\\/") + "\\/", block)

    return re.sub(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>[\s\S]*?</script>',
        schema,
        html,
        flags=re.I,
    )


def pagination_url(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in ("", HOST):
        return None
    if not re.search(r"/page/\d+/?$", parsed.path):
        return None
    path = parsed.path if parsed.path.endswith("/") else parsed.path + "/"
    return ORIGIN + path


def page_candidate(url: str) -> str | None:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc not in (("",) + tuple(HOSTS)) or parsed.query:
        return None
    path = parsed.path or "/"
    lower = path.lower()
    if any(lower.endswith(ext) for ext in ASSET_EXT + (".xml", ".xsl", ".php", ".html")):
        return None
    if lower.startswith(("/wp-content/", "/wp-includes/", "/wp-admin/")):
        return None
    if not path.endswith("/"):
        path += "/"
    absolute = ORIGIN + path
    if should_skip(absolute):
        return None
    return absolute


def queue_found_urls(html: str, final: str, queue: list[str], extra_pages: list[str], seen_pages: set[str]) -> None:
    for url in extract_urls(html, final):
        if same_origin(url) and not should_skip(url):
            queue.append(url)
    for href in re.findall(r"""<a\b[^>]*\bhref=["']([^"'#]+)""", html, flags=re.I):
        if href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        nxt = page_candidate(urllib.parse.urljoin(final, html_lib.unescape(href)))
        if nxt and nxt not in seen_pages and nxt not in extra_pages:
            extra_pages.append(nxt)


def lock_origin() -> None:
    global ORIGIN, HOST
    configure_hosts()
    try:
        _data, final, _ctype = fetch(ORIGIN + "/")
    except Exception:
        return
    netloc = urllib.parse.urlparse(final).netloc
    if netloc in HOSTS and netloc != HOST:
        HOST = netloc
        ORIGIN = "https://" + netloc
        configure_hosts()
        print(f"origin {ORIGIN}", flush=True)


def remember_page(page: str, into_sitemap: bool, captured: list, queue: list, extra_pages: list, seen_pages: set, flags: list) -> None:
    try:
        data, final, ctype = fetch(page)
    except Exception as error:
        flags.append(f"falha pagina {page}: {error}")
        print(f"fail page {page}", flush=True)
        return
    if "text/html" not in ctype:
        flags.append(f"pagina sem html: {page} ({ctype})")
        return
    final_host = urllib.parse.urlparse(final).netloc
    if final_host and final_host not in HOSTS:
        flags.append(f"redirecionou para fora: {page} -> {final}")
        return
    asked = urllib.parse.urlparse(page).path or "/"
    landed = urllib.parse.urlparse(final).path or "/"
    if not landed.endswith("/") and "." not in landed.rsplit("/", 1)[-1]:
        landed += "/"
    if asked != landed:
        REDIRECTS[asked] = landed
        if landed in SEEN_FINALS:
            return
        into_sitemap = False
    if landed in SEEN_FINALS:
        return
    SEEN_FINALS.add(landed)
    html = data.decode("utf-8", "replace")
    if SUSPICIOUS.search(html):
        flags.append(f"html suspeito: {final}")
    captured.append((final, html, into_sitemap))
    queue_found_urls(html, final, queue, extra_pages, seen_pages)


REDIRECTS: dict[str, str] = {}
SEEN_FINALS: set[str] = set()


def write_redirects(flags: list) -> None:
    if not REDIRECTS:
        return
    rules = []
    for source, destination in sorted(REDIRECTS.items()):
        if source == destination:
            continue
        rules.append({"source": source, "destination": destination, "permanent": True})
        stub = PUBLIC / source.lstrip("/") / "index.html"
        if stub.exists():
            continue
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_text(
            "<!doctype html><html><head><meta charset=\"utf-8\">"
            f"<link rel=\"canonical\" href=\"{ORIGIN}{destination}\">"
            f"<meta http-equiv=\"refresh\" content=\"0; url={destination}\">"
            "<meta name=\"robots\" content=\"noindex\">"
            f"</head><body><a href=\"{destination}\">{destination}</a></body></html>\n",
            encoding="utf-8",
        )
    config_path = ROOT / "vercel.json"
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    config["trailingSlash"] = True
    config["redirects"] = rules
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    flags.append(f"redirecionamentos do WordPress mantidos: {len(rules)}")


def main() -> None:
    global TITLE_SUFFIXES
    lock_origin()
    PUBLIC.mkdir(parents=True, exist_ok=True)
    pages = load_pages()
    print(f"pages_to_copy {len(pages)}", flush=True)
    queue = []
    seen = set()
    saved_pages = []
    flags = []
    seen_pages = set(pages)
    extra_pages = []
    captured = []

    for index, page in enumerate(pages, start=1):
        remember_page(page, True, captured, queue, extra_pages, seen_pages, flags)
        if index % 20 == 0:
            print(f"pages {index}/{len(pages)}", flush=True)

    while extra_pages:
        page = extra_pages.pop(0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        before = len(captured)
        remember_page(page, False, captured, queue, extra_pages, seen_pages, flags)
        if len(captured) == before:
            continue
        print(f"page extra {page}", flush=True)

    TITLE_SUFFIXES = detect_suffixes([html for _final, html, _sitemap in captured])
    print(f"title_suffixes {TITLE_SUFFIXES}", flush=True)

    for final, html, into_sitemap in captured:
        if urllib.parse.urlparse(final).path in ("", "/"):
            target = PUBLIC / "index.html"
        else:
            target = local_path(final if final.endswith("/") else final + "/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rewrite_html(html), encoding="utf-8")
        saved_pages.append(
            "/"
            if target.name == "index.html" and target.parent == PUBLIC
            else "/" + str(target.relative_to(PUBLIC)).removesuffix("index.html")
        )
        if not into_sitemap:
            if re.search(r'name="robots"[^>]*content="[^"]*noindex', html, flags=re.I):
                flags.append(f"paginacao noindex, fora do sitemap: {final}")
            else:
                pages.append(final if final.endswith("/") else final + "/")
    pages = [page for page in pages if (urllib.parse.urlparse(page).path or "/") not in REDIRECTS]
    write_redirects(flags)

    assets = 0
    while queue:
        url = queue.pop(0)
        clean = strip_query(url)
        if clean in seen or not same_origin(clean) or should_skip(clean):
            continue
        path = urllib.parse.urlparse(clean).path.lower()
        if not any(path.endswith(ext) for ext in ASSET_EXT):
            continue
        seen.add(clean)
        try:
            data, _final, ctype = fetch(clean)
        except Exception as error:
            flags.append(f"falha {clean}: {error}")
            continue
        if "text/html" in ctype or path.endswith(".php"):
            flags.append(f"ignorado (nao e asset estatico): {clean}")
            continue
        if path.endswith((".css", ".js", ".mjs", ".svg", ".json")) or "javascript" in ctype or "text/css" in ctype:
            text = data.decode("utf-8", "replace")
            if SUSPICIOUS.search(text):
                flags.append(f"asset suspeito: {clean}")
            cleaned = strip_origin(OLD_SERVER.sub("", text))
            if cleaned != text:
                flags.append(f"removida marcacao de servidor antigo: {clean}")
                data = cleaned.encode("utf-8")
                text = cleaned
            if "__elementorLoadChunk" in text and "/assets/js/" in clean:
                base = clean.split("/assets/js/")[0]
                for name in re.findall(r"__elementorLoadChunk\(`([A-Za-z0-9_-]+)`\)", text):
                    queue.append(base + "/assets/js/chunks/" + name + ".min.js")
            for extra in extract_urls(text, clean):
                if same_origin(extra) and not should_skip(extra):
                    queue.append(extra)
        dest = local_path(clean)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        assets += 1
        if assets % 50 == 0:
            print(f"assets {assets}", flush=True)

    locs = []
    listed = set()
    for page in pages:
        path = urllib.parse.urlparse(page).path or "/"
        if not path.endswith("/"):
            path += "/"
        if path in listed:
            continue
        listed.add(path)
        locs.append(f"  <url><loc>{ORIGIN}{path}</loc></url>")
    sitemap = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(locs)
        + "\n</urlset>\n"
    )
    (PUBLIC / "sitemap.xml").write_text(sitemap, encoding="utf-8")
    (PUBLIC / "robots.txt").write_text(
        f"User-agent: *\nAllow: /\n\nSitemap: {ORIGIN}/sitemap.xml\n",
        encoding="utf-8",
    )
    try:
        missing_req = urllib.request.Request(
            ORIGIN + "/esta-pagina-nao-existe-espelho/",
            headers={"User-Agent": BROWSER_UA},
        )
        with urllib.request.urlopen(missing_req, context=CTX, timeout=60) as response:
            flags.append(f"404 inesperado: status {response.status}")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            missing = rewrite_html(error.read().decode("utf-8", "replace"))
            dest = ROOT / "src" / "not-found.html"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(missing, encoding="utf-8")
        else:
            flags.append(f"404 inesperado: {error}")
    except Exception as error:
        flags.append(f"falha 404: {error}")
    if not (ROOT / "src" / "not-found.html").exists():
        (ROOT / "src").mkdir(parents=True, exist_ok=True)
        (ROOT / "src" / "not-found.html").write_text("<h1>Página não encontrada</h1>\n", encoding="utf-8")
        flags.append("404 padrao, a pagina oficial nao devolveu 404")

    report = {"pages": len(saved_pages), "assets": assets, "flags": flags}
    (ROOT / "mirror-report.json").write_text(json.dumps({"pages": saved_pages, "assets": assets, "flags": flags}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
