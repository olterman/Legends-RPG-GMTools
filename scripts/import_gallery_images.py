from __future__ import annotations

import argparse
import csv
import json
import mimetypes
import re
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def normalize_image_ref(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if text.startswith("/images/"):
        text = text[len("/images/"):]
    elif text.startswith("images/"):
        text = text[len("images/"):]
    return text.strip("/")


def load_image_catalog(images_dir: Path) -> dict[str, dict]:
    path = images_dir / "_index.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_image_catalog(images_dir: Path, catalog: dict[str, dict]) -> None:
    path = images_dir / "_index.json"
    path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")


def slugify(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", unescape(str(value or ""))).strip()


def parse_tags(raw_tags: Iterable[str]) -> list[str]:
    values: set[str] = set()
    aliases = {
        "lands_of_legends": "lands_of_legend",
        "land_of_legends": "lands_of_legend",
        "land_of_legend": "lands_of_legend",
        "highland_urukculture": "culture",
        "alfirin": "alfir",
        "alfir_sombra": "duathrim",
        "alfir_sylvani": "galadhrim",
        "alfir_sky_children": "kalaquendi",
        "sky_children": "kalaquendi",
        "alfir_wave_riders": "falthrim",
        "faltrim": "falthrim",
        "race_alfir": "alfir",
        "cyfer": "cypher",
        "cyphers_artifacts": "",
        "human_highlanders": "highland_fenmir",
        "the_other_human_tribes": "",
        "the_dead": "gurthim",
        "dangers_undead": "gurthim",
        "dangers_monsters": "monster",
        "liilim": "lilim",
    }
    for raw in raw_tags:
        for part in str(raw or "").split(","):
            token = slugify(part)
            token = aliases.get(token, token)
            if token:
                values.add(token)
    return sorted(values)


@dataclass
class CandidateImage:
    url: str
    score: int


class GalleryImageParser(HTMLParser):
    def __init__(self, page_url: str) -> None:
        super().__init__()
        self.page_url = page_url
        self.page_title = ""
        self._in_title = False
        self._title_chunks: list[str] = []
        self.candidates: dict[str, int] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {str(k).lower(): str(v or "") for k, v in attrs}
        tag = tag.lower()
        if tag == "title":
            self._in_title = True
            return
        if tag == "meta":
            prop = attrs_map.get("property") or attrs_map.get("name") or ""
            content = attrs_map.get("content") or ""
            prop_lc = prop.strip().lower()
            if prop_lc in {"og:image", "og:image:secure_url", "twitter:image"}:
                self._add_candidate(content, score=12)
            elif prop_lc in {"og:title", "twitter:title"} and content and not self.page_title:
                self.page_title = clean_text(content)
            return
        if tag == "img":
            self._add_candidate(attrs_map.get("src"), score=7)
            self._extract_srcset(attrs_map.get("srcset"), base_score=6)
            return
        if tag == "source":
            self._extract_srcset(attrs_map.get("srcset"), base_score=5)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False
            if self._title_chunks and not self.page_title:
                self.page_title = clean_text("".join(self._title_chunks))

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_chunks.append(data)

    def _extract_srcset(self, srcset: str | None, *, base_score: int) -> None:
        raw = str(srcset or "").strip()
        if not raw:
            return
        for chunk in raw.split(","):
            url = chunk.strip().split(" ")[0].strip()
            self._add_candidate(url, score=base_score)

    def _add_candidate(self, url: str | None, *, score: int) -> None:
        normalized = normalize_candidate_url(self.page_url, url)
        if not normalized:
            return
        self.candidates[normalized] = max(score, self.candidates.get(normalized, 0))


def normalize_candidate_url(page_url: str, url: str | None) -> str:
    raw = clean_text(url or "")
    if not raw:
        return ""
    if raw.startswith("data:"):
        return ""
    normalized = urljoin(page_url, raw)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"}:
        return ""
    path = parsed.path.lower()
    if any(path.endswith(ext) for ext in IMAGE_SUFFIXES):
        return normalized
    if "pinimg.com" in parsed.netloc.lower():
        return normalized
    if re.search(r"/originals?/|/236x/|/474x/|/564x/|/736x/", normalized.lower()):
        return normalized
    return normalized


def extract_candidate_images(page_url: str, html: str) -> tuple[str, list[CandidateImage]]:
    parser = GalleryImageParser(page_url)
    parser.feed(html)

    candidates = dict(parser.candidates)
    for match in re.finditer(r"https?://[^\"'\\\s<>]+", html, flags=re.IGNORECASE):
        url = normalize_candidate_url(page_url, match.group(0))
        if not url:
            continue
        score = 11 if "pinimg.com" in urlparse(url).netloc.lower() else 4
        candidates[url] = max(score, candidates.get(url, 0))

    ranked = [
        CandidateImage(url=url, score=score + score_candidate_url(url))
        for url, score in candidates.items()
    ]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return parser.page_title, ranked


def score_candidate_url(url: str) -> int:
    text = url.lower()
    score = 0
    if "pinimg.com" in text:
        score += 10
    if "/originals/" in text:
        score += 8
    if any(token in text for token in ["/736x/", "/564x/", "/474x/"]):
        score += 5
    if any(token in text for token in ["avatar", "profile", "favicon", "logo", "sprite"]):
        score -= 8
    return score


def fetch_url_text(url: str, *, timeout: int = 20) -> str:
    req = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def gallery_dl_available() -> bool:
    return bool(shutil.which("gallery-dl"))


def extract_candidate_images_with_gallery_dl(page_url: str) -> tuple[str, list[CandidateImage]]:
    exe = shutil.which("gallery-dl")
    if not exe:
        raise RuntimeError("gallery-dl is not installed")

    proc = subprocess.run(
        [exe, "-g", page_url],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        stderr = clean_text(proc.stderr or "")
        raise RuntimeError(stderr or "gallery-dl failed to extract image URLs")

    candidates: dict[str, int] = {}
    for line in (proc.stdout or "").splitlines():
        url = normalize_candidate_url(page_url, line.strip())
        if not url:
            continue
        score = 18 if "pinimg.com" in urlparse(url).netloc.lower() else 10
        candidates[url] = max(score + score_candidate_url(url), candidates.get(url, 0))
    ranked = [CandidateImage(url=url, score=score) for url, score in candidates.items()]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return "", ranked


def fetch_image_bytes(url: str, *, timeout: int = 25) -> tuple[str, bytes]:
    req = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT, "Referer": url})
    with urlopen(req, timeout=timeout) as resp:
        mime_type = str(resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        payload = resp.read()
    if not payload:
        raise ValueError("empty image response")
    return mime_type, payload


def image_suffix(mime_type: str, url: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return ".jpg" if suffix == ".jpe" else suffix
    guessed = str(mimetypes.guess_extension(mime_type or "") or "").lower()
    if guessed == ".jpe":
        guessed = ".jpg"
    return guessed if guessed in IMAGE_SUFFIXES else ".jpg"


def import_page(
    *,
    page_url: str,
    images_dir: Path,
    upload_subdir: str,
    tags: list[str],
    friendly_prefix: str,
    description: str,
    limit: int,
    dry_run: bool,
    extractor: str,
) -> list[dict]:
    html_page_title = ""
    candidates: list[CandidateImage] = []
    if extractor in {"auto", "gallery-dl"} and gallery_dl_available():
        try:
            page_title, candidates = extract_candidate_images_with_gallery_dl(page_url)
        except Exception:
            if extractor == "gallery-dl":
                raise
            page_title = ""
        else:
            html_page_title = page_title
    if not candidates:
        html = fetch_url_text(page_url)
        html_page_title, candidates = extract_candidate_images(page_url, html)
    page_title = html_page_title
    if not candidates:
        return []

    upload_dir = images_dir / upload_subdir
    upload_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_image_catalog(images_dir)
    imported: list[dict] = []
    seen_urls: set[str] = set()

    effective_desc = clean_text(description) or f"Imported from {page_title or page_url}"
    page_slug = slugify(page_title or Path(urlparse(page_url).path).stem or "gallery")

    count = 0
    for candidate in candidates:
        if candidate.url in seen_urls:
            continue
        seen_urls.add(candidate.url)
        if count >= limit:
            break
        mime_type, payload = fetch_image_bytes(candidate.url)
        suffix = image_suffix(mime_type, candidate.url)
        stem = slugify(friendly_prefix or page_title or "gallery_image") or "gallery_image"
        final_name = f"{stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:8]}{suffix}"
        rel = f"{upload_subdir.strip('/').replace('\\', '/')}/{final_name}"
        item = {
            "path": rel,
            "friendly_name": f"{friendly_prefix} {count + 1}".strip() if friendly_prefix else clean_text(page_title or page_slug or final_name),
            "tags": sorted(set(tags + parse_tags([page_slug]))),
            "description": effective_desc,
            "source_url": candidate.url,
            "page_url": page_url,
            "score": candidate.score,
        }
        imported.append(item)
        count += 1
        if dry_run:
            continue
        path = images_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        catalog[rel] = {
            "friendly_name": item["friendly_name"],
            "tags": item["tags"],
            "description": item["description"],
            "attached_to": [],
        }

    if not dry_run and imported:
        save_image_catalog(images_dir, catalog)
    return imported


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="One-time importer for public inspiration/gallery pages into the local image browser catalog."
    )
    parser.add_argument("--page-url", action="append", default=[], help="Public page URL to scan for images. Repeatable.")
    parser.add_argument("--page-url-file", help="Text file with one page URL per line.")
    parser.add_argument("--csv-file", help="CSV manifest with columns: url, tags, friendly_prefix")
    parser.add_argument("--images-dir", default="images", help="Target images directory. Defaults to ./images")
    parser.add_argument("--upload-subdir", default="uploads/gallery_imports", help="Subdirectory under images/ for imported files.")
    parser.add_argument("--tags", action="append", default=[], help="Comma-separated tags to add to every imported image.")
    parser.add_argument("--friendly-prefix", default="", help="Prefix for friendly names, e.g. 'Fox Fellic'.")
    parser.add_argument("--description", default="", help="Description to apply to imported images.")
    parser.add_argument("--limit", type=int, default=24, help="Max images to import per page URL.")
    parser.add_argument(
        "--extractor",
        choices=["auto", "gallery-dl", "html"],
        default="auto",
        help="How to extract image URLs. 'auto' prefers gallery-dl when installed, then falls back to HTML parsing.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview candidate imports without downloading files.")
    return parser


def load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: list[dict[str, str]] = []
        for raw in reader:
            if not isinstance(raw, dict):
                continue
            url = str(raw.get("url") or "").strip()
            if not url:
                continue
            rows.append({
                "url": url,
                "tags": str(raw.get("tags") or "").strip(),
                "friendly_prefix": str(raw.get("friendly_prefix") or raw.get("friendly-prefix") or "").strip(),
            })
        return rows


def main() -> int:
    args = build_parser().parse_args()
    page_urls = [str(url).strip() for url in (args.page_url or []) if str(url).strip()]
    if args.page_url_file:
        path = Path(args.page_url_file)
        if not path.exists():
            raise SystemExit(f"URL file not found: {path}")
        page_urls.extend(
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    jobs: list[dict[str, str]] = [
        {
            "url": url,
            "tags": ",".join(args.tags or []),
            "friendly_prefix": str(args.friendly_prefix or "").strip(),
        }
        for url in page_urls
    ]
    if args.csv_file:
        path = Path(args.csv_file)
        if not path.exists():
            raise SystemExit(f"CSV file not found: {path}")
        jobs.extend(load_csv_rows(path))
    deduped_jobs: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for job in jobs:
        marker = (
            str(job.get("url") or "").strip(),
            str(job.get("tags") or "").strip(),
            str(job.get("friendly_prefix") or "").strip(),
        )
        if not marker[0] or marker in seen:
            continue
        seen.add(marker)
        deduped_jobs.append(job)
    if not deduped_jobs:
        raise SystemExit("Provide at least one --page-url, --page-url-file, or --csv-file")

    images_dir = Path(args.images_dir).resolve()
    images_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    for job in deduped_jobs:
        page_url = str(job.get("url") or "").strip()
        row_tags = parse_tags([str(job.get("tags") or "")])
        merged_tags = sorted(set(parse_tags(args.tags) + row_tags))
        friendly_prefix = str(job.get("friendly_prefix") or args.friendly_prefix or "").strip()
        print(f"\nScanning: {page_url}")
        try:
            imported = import_page(
                page_url=page_url,
                images_dir=images_dir,
                upload_subdir=args.upload_subdir,
                tags=merged_tags,
                friendly_prefix=friendly_prefix,
                description=str(args.description or "").strip(),
                limit=max(1, int(args.limit or 1)),
                dry_run=bool(args.dry_run),
                extractor=str(args.extractor or "auto").strip().lower(),
            )
        except Exception as exc:
            print(f"  ERROR: {exc}")
            continue
        if not imported:
            print("  No candidate images found.")
            continue
        for item in imported:
            print(f"  {'PLAN' if args.dry_run else 'IMPORTED'} {item['path']} <- {item['source_url']}")
        total += len(imported)

    print(f"\nDone. {'Planned' if args.dry_run else 'Imported'} {total} image(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
