from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lol_api.config_loader import load_config_dir


@dataclass(frozen=True)
class SearchTerm:
    category: str
    value: str


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def unique_terms(values: list[SearchTerm]) -> list[SearchTerm]:
    seen: set[tuple[str, str]] = set()
    out: list[SearchTerm] = []
    for item in values:
        key = (item.category, normalize(item.value))
        if not item.value.strip() or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def collect_terms(config: dict[str, Any]) -> list[SearchTerm]:
    terms: list[SearchTerm] = []

    races = config.get("races", {}) or {}
    for race_key, race_data in races.items():
        terms.append(SearchTerm("race", str(race_key)))
        if isinstance(race_data, dict):
            if race_data.get("name"):
                terms.append(SearchTerm("race", str(race_data["name"])))

    areas = config.get("areas", {}) or config.get("environments", {}) or {}
    for env_key, env_data in areas.items():
        terms.append(SearchTerm("area", str(env_key)))
        if isinstance(env_data, dict):
            env_name = env_data.get("name")
            env_type = str(env_data.get("type", ""))
            if env_name:
                terms.append(SearchTerm("area", str(env_name)))
            if "city" in env_type:
                terms.append(SearchTerm("city", str(env_key)))
                if env_name:
                    terms.append(SearchTerm("city", str(env_name)))

    settlements = config.get("settlements", {}) or {}
    for settlement_key in settlements.keys():
        # Many settlement keys map to city-like domains.
        terms.append(SearchTerm("city", str(settlement_key)))

    return unique_terms(terms)


def filter_terms(terms: list[SearchTerm], ignored_terms: set[str]) -> list[SearchTerm]:
    if not ignored_terms:
        return terms
    out: list[SearchTerm] = []
    for term in terms:
        if normalize(term.value) in ignored_terms:
            continue
        out.append(term)
    return out


def compile_patterns(terms: list[SearchTerm]) -> dict[SearchTerm, re.Pattern[str]]:
    patterns: dict[SearchTerm, re.Pattern[str]] = {}
    for term in terms:
        escaped = re.escape(term.value)
        # Require non-word boundaries only for terms that start/end with alnum.
        prefix = r"(?<![A-Za-z0-9])" if re.match(r"[A-Za-z0-9]", term.value[:1] or "") else ""
        suffix = r"(?![A-Za-z0-9])" if re.match(r".*[A-Za-z0-9]$", term.value or "") else ""
        patterns[term] = re.compile(prefix + escaped + suffix, flags=re.IGNORECASE)
    return patterns


def load_marked_ignores(markdown_path: Path) -> set[str]:
    """
    Reads lines like:
    !- `logseq/pages/Some File.md`: ...
    and returns exact paths to ignore.
    """
    ignored: set[str] = set()
    if not markdown_path.exists():
        return ignored

    pattern = re.compile(r"^!\s*-\s*`([^`]+)`")
    for line in markdown_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        m = pattern.match(line.strip())
        if not m:
            continue
        ignored.add(m.group(1).strip())
    return ignored


def scan_markdown(
    root: Path,
    patterns: dict[SearchTerm, re.Pattern[str]],
    exclude_regexes: list[re.Pattern[str]],
    exclude_paths: set[str],
) -> dict[str, Any]:
    files = sorted(root.rglob("*.md"))
    hits_by_term: dict[str, dict[str, Any]] = {}
    hits_by_file: dict[str, list[dict[str, Any]]] = {}

    for file_path in files:
        rel = str(file_path)
        if rel in exclude_paths:
            continue
        if any(rx.search(rel) for rx in exclude_regexes):
            continue
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        lines = text.splitlines()
        file_hits: list[dict[str, Any]] = []

        for term, pattern in patterns.items():
            line_hits: list[dict[str, Any]] = []
            for idx, line in enumerate(lines, start=1):
                if not pattern.search(line):
                    continue
                line_hits.append({
                    "line": idx,
                    "text": line.strip()[:400],
                })

            if not line_hits:
                continue

            term_key = f"{term.category}:{term.value}"
            if term_key not in hits_by_term:
                hits_by_term[term_key] = {
                    "category": term.category,
                    "term": term.value,
                    "files": [],
                    "total_mentions": 0,
                }
            hits_by_term[term_key]["files"].append({
                "path": rel,
                "mentions": len(line_hits),
                "examples": line_hits[:3],
            })
            hits_by_term[term_key]["total_mentions"] += len(line_hits)
            file_hits.append({
                "category": term.category,
                "term": term.value,
                "mentions": len(line_hits),
            })

        if file_hits:
            hits_by_file[rel] = sorted(
                file_hits,
                key=lambda x: (x["category"], -x["mentions"], x["term"].lower()),
            )

    summary = {
        "files_scanned": len(files),
        "files_with_hits": len(hits_by_file),
        "unique_terms_with_hits": len(hits_by_term),
    }

    return {
        "summary": summary,
        "hits_by_term": dict(sorted(hits_by_term.items(), key=lambda kv: (-kv[1]["total_mentions"], kv[0]))),
        "hits_by_file": hits_by_file,
    }


def write_markdown_report(report: dict[str, Any], output_path: Path) -> None:
    lines: list[str] = []
    summary = report.get("summary", {})
    lines.append("# Logseq Config Term Scan")
    lines.append("")
    lines.append(f"- Files scanned: {summary.get('files_scanned', 0)}")
    lines.append(f"- Files with hits: {summary.get('files_with_hits', 0)}")
    lines.append(f"- Unique terms with hits: {summary.get('unique_terms_with_hits', 0)}")
    lines.append("")
    lines.append("## Top Terms")
    lines.append("")

    top_terms = list(report.get("hits_by_term", {}).values())[:40]
    if not top_terms:
        lines.append("_No matches found._")
    else:
        for item in top_terms:
            lines.append(
                f"- `{item['category']}` **{item['term']}**: "
                f"{item['total_mentions']} mentions in {len(item['files'])} files"
            )
    lines.append("")
    lines.append("## Top Files")
    lines.append("")

    top_files = sorted(
        report.get("hits_by_file", {}).items(),
        key=lambda kv: -sum(entry["mentions"] for entry in kv[1]),
    )[:40]
    if not top_files:
        lines.append("_No matches found._")
    else:
        for path, entries in top_files:
            total = sum(entry["mentions"] for entry in entries)
            top = ", ".join(
                f"{entry['term']} ({entry['mentions']})"
                for entry in entries[:5]
            )
            lines.append(f"- `{path}`: {total} mentions; top terms: {top}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scan Logseq markdown for config term mentions.")
    parser.add_argument("--config-dir", default="config", help="Path to config directory")
    parser.add_argument("--logseq-dir", default="logseq", help="Path to logseq directory")
    parser.add_argument(
        "--json-out",
        default="docs/logseq_config_term_hits.json",
        help="Where to write machine-readable report",
    )
    parser.add_argument(
        "--md-out",
        default="docs/LOGSEQ_CONFIG_TERM_SCAN.md",
        help="Where to write markdown summary",
    )
    parser.add_argument(
        "--exclude-regex",
        action="append",
        default=[r"/logseq/bak/", r"/\.git/"],
        help="Regex path filters to exclude files (can be repeated)",
    )
    parser.add_argument(
        "--ignore-term",
        action="append",
        default=["human", "humans"],
        help="Exact term values to ignore (case-insensitive); can be repeated",
    )
    parser.add_argument(
        "--ignore-marked-md",
        default="docs/LOGSEQ_CONFIG_TERM_SCAN.md",
        help="Markdown file where lines starting with '!-' mark exact file paths to ignore",
    )
    args = parser.parse_args()

    config_dir = Path(args.config_dir)
    logseq_dir = Path(args.logseq_dir)
    json_out = Path(args.json_out)
    md_out = Path(args.md_out)

    if not config_dir.exists():
        raise FileNotFoundError(f"Config directory not found: {config_dir}")
    if not logseq_dir.exists():
        raise FileNotFoundError(f"Logseq directory not found: {logseq_dir}")

    config = load_config_dir(config_dir)
    terms = collect_terms(config)
    ignored_terms = {normalize(v) for v in args.ignore_term}
    terms = filter_terms(terms, ignored_terms)
    patterns = compile_patterns(terms)
    exclude_regexes = [re.compile(x) for x in args.exclude_regex]
    ignore_marked_md = Path(args.ignore_marked_md)
    exclude_paths = load_marked_ignores(ignore_marked_md)
    report = scan_markdown(logseq_dir, patterns, exclude_regexes, exclude_paths)

    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown_report(report, md_out)

    summary = report.get("summary", {})
    print(f"Files scanned: {summary.get('files_scanned', 0)}")
    print(f"Files with hits: {summary.get('files_with_hits', 0)}")
    print(f"Unique terms with hits: {summary.get('unique_terms_with_hits', 0)}")
    print(f"JSON report: {json_out}")
    print(f"Markdown report: {md_out}")


if __name__ == "__main__":
    main()
