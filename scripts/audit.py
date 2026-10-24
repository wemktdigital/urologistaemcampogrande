#!/usr/bin/env python3
"""Compara cada página copiada com a versão oficial e lista arquivos locais que faltam."""

import html as html_lib
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public"
ORIGIN = "https://urologistaemcampogrande.com.br"
HOST = "urologistaemcampogrande.com.br"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
CTX = ssl.create_default_context()


def fetch(url: str) -> tuple[int, str]:
    for attempt in range(3):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, context=CTX, timeout=90) as response:
                return response.status, response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as error:
            return error.code, error.read().decode("utf-8", "replace")
        except Exception:
            time.sleep(4 * (attempt + 1))
    return 0, ""


def text_of(fragment: str) -> str:
    fragment = re.sub(r"<[^>]+>", " ", fragment)
    return re.sub(r"\s+", " ", html_lib.unescape(fragment)).strip()


def first(pattern: str, html: str) -> str:
    match = re.search(pattern, html, flags=re.I | re.S)
    return html_lib.unescape(match.group(1)).strip() if match else ""


def headings(html: str) -> list[str]:
    return [
        f"h{level}:{text_of(body)}"
        for level, body in re.findall(r"<h([1-6])\b[^>]*>(.*?)</h\1>", html, flags=re.I | re.S)
    ]


def visible_text(html: str) -> str:
    html = re.sub(r"<(script|style|noscript|template)\b[\s\S]*?</\1>", " ", html, flags=re.I)
    html = re.sub(r"<!--[\s\S]*?-->", " ", html)
    return text_of(html)


def normalize(url: str) -> str:
    url = html_lib.unescape(url.strip())
    if url.startswith(("mailto:", "tel:", "#", "javascript:", "data:")):
        return url
    if url.startswith(f"https://{HOST}//") or url.startswith(f"http://{HOST}//"):
        url = "/" + url.split("//", 2)[2]
    parsed = urllib.parse.urlparse(urllib.parse.urljoin(ORIGIN + "/", url))
    if parsed.netloc == HOST:
        return re.sub(r"^/+", "/", parsed.path or "/") + (("?" + parsed.query) if parsed.query else "")
    return parsed.geturl()


def links(html: str) -> set[str]:
    out = set()
    for href in re.findall(r"""<a\b[^>]*\bhref=["']([^"']*)["']""", html, flags=re.I):
        value = normalize(href)
        if "/wp-json" in value or "/feed" in value or "xmlrpc" in value:
            continue
        out.add(value)
    return out


def images(html: str) -> set[str]:
    out = set()
    for src in re.findall(r"""<img\b[^>]*\bsrc=["']([^"']+)["']""", html, flags=re.I):
        out.add(normalize(src).split("?")[0])
    return out


def tracking(html: str) -> set[str]:
    return set(re.findall(r"GTM-[A-Z0-9]+|\bG-[A-Z0-9]{8,}\b|AW-\d{6,}|fbq\('init', '\d+'", html))


def local_refs(html: str) -> set[str]:
    refs = set()
    for value in re.findall(r"""(?:src|href|data-src|poster)=["'](/[^"'#]+)["']""", html):
        refs.add(value)
    for value in re.findall(r"""srcset=["']([^"']+)["']""", html):
        for part in value.split(","):
            piece = part.strip().split(" ")[0]
            if piece.startswith("/"):
                refs.add(piece)
    for value in re.findall(r"""url\(\s*['"]?(/[^'")]+)['"]?\s*\)""", html):
        refs.add(value)
    return {r.split("?")[0] for r in refs if not r.startswith("//")}


def exists_locally(path: str) -> bool:
    clean = urllib.parse.unquote(path)
    target = PUBLIC / clean.lstrip("/")
    if clean.endswith("/"):
        return (target / "index.html").exists()
    if target.exists():
        return target.is_file() or (target / "index.html").exists()
    return False


def css_refs() -> dict[str, set[str]]:
    missing = {}
    for css in PUBLIC.rglob("*.css"):
        text = css.read_text(errors="replace")
        for value in re.findall(r"""url\(\s*['"]?([^'")]+)['"]?\s*\)""", text):
            if value.startswith(("data:", "http:", "https:", "#", "//")):
                continue
            target = urllib.parse.urljoin("/" + str(css.relative_to(PUBLIC)), value.split("?")[0].split("#")[0])
            if not exists_locally(target):
                missing.setdefault(target, set()).add(str(css.relative_to(PUBLIC)))
    return missing


def main() -> None:
    sitemap = (PUBLIC / "sitemap.xml").read_text()
    pages = [urllib.parse.urlparse(u).path for u in re.findall(r"<loc>(.*?)</loc>", sitemap)]
    report = []
    missing_assets: dict[str, set[str]] = {}
    for path in pages:
        status, live = fetch(ORIGIN + path)
        local_file = PUBLIC / path.lstrip("/") / "index.html" if path != "/" else PUBLIC / "index.html"
        local = local_file.read_text(errors="replace") if local_file.exists() else ""
        issues = []
        if status != 200:
            issues.append(f"oficial respondeu {status}")
        if not local:
            issues.append("página não existe na cópia")
        for label, pattern in (
            ("title", r"<title>(.*?)</title>"),
            ("description", r'<meta name="description" content="([^"]*)"'),
            ("canonical", r'<link rel="canonical" href="([^"]*)"'),
            ("robots", r'<meta name=["\']robots["\'] content=["\']([^"\']*)["\']'),
        ):
            a, b = first(pattern, live), first(pattern, local)
            if a != b:
                issues.append(f"{label}: oficial={a!r} copia={b!r}")
        if headings(live) != headings(local):
            issues.append(f"títulos internos diferentes: oficial={len(headings(live))} copia={len(headings(local))}")
        if tracking(live) != tracking(local):
            issues.append(f"tags: oficial={sorted(tracking(live))} copia={sorted(tracking(local))}")
        li, lo = links(live), links(local)
        if li - lo:
            issues.append(f"links só no oficial: {sorted(li - lo)[:8]}")
        if lo - li:
            issues.append(f"links só na cópia: {sorted(lo - li)[:8]}")
        ii, io = images(live), images(local)
        if ii - io:
            issues.append(f"imagens só no oficial: {sorted(ii - io)[:8]}")
        ratio = SequenceMatcher(None, visible_text(live), visible_text(local), autojunk=False).ratio()
        if ratio < 0.995:
            issues.append(f"texto visível {ratio:.3f}")
        comparable = re.sub(r'<link rel="canonical"[^>]*>', "", local)
        comparable = re.sub(
            r'<meta\b[^>]*(?:property|name)="(?:og:[^"]+|twitter:[^"]+)"[^>]*>',
            "",
            comparable,
            flags=re.I,
        )
        comparable = re.sub(r'<script type="application/ld\+json"[\s\S]*?</script>', "", comparable, flags=re.I)
        if re.search(rf"https?://(?:www\.)?{re.escape(HOST)}", comparable):
            issues.append("cópia ainda chama o domínio antigo")
        for ref in local_refs(local):
            if not exists_locally(ref):
                missing_assets.setdefault(ref, set()).add(path)
        report.append({"page": path, "issues": issues})
        print(("OK  " if not issues else "DIF ") + path, flush=True)
        for issue in issues:
            print("     - " + issue, flush=True)
    known_404 = ROOT / ".oficial-404.txt"
    if known_404.exists():
        gone = set(known_404.read_text().splitlines())
        missing_assets = {ref: where for ref, where in missing_assets.items() if ref not in gone and "<" not in ref}
    css_missing = css_refs()
    print("\nARQUIVOS REFERENCIADOS NO HTML QUE FALTAM:", len(missing_assets))
    for ref, where in sorted(missing_assets.items()):
        print(f"  {ref}  ({len(where)} páginas)")
    print("\nARQUIVOS REFERENCIADOS NO CSS QUE FALTAM:", len(css_missing))
    for ref, where in sorted(css_missing.items()):
        print(f"  {ref}  <- {sorted(where)[:2]}")
    (ROOT / "audit-report.json").write_text(
        json.dumps(
            {
                "pages": report,
                "missing_html": {k: sorted(v) for k, v in missing_assets.items()},
                "missing_css": {k: sorted(v) for k, v in css_missing.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
