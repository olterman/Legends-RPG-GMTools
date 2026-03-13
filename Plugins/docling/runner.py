from __future__ import annotations

import argparse
import json
import os
import selectors
import sqlite3
import subprocess
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


DEFAULT_SOURCE_DIRS = (
    "PDF_Repository/Genre_Books",
    "PDF_Repository/Setting_Books",
    "PDF_Repository/Core_Rules",
)
DEFAULT_OUTPUT_DIR = "PDF_Repository/private_compendium/_docling"
DEFAULT_MANIFEST_NAME = "batch_manifest.json"
DEFAULT_STATUS_NAME = "runner_status.json"


@dataclass
class DoclingJobResult:
    source_pdf: str
    output_dir: str
    status: str
    command: str
    return_code: int | None
    stderr_tail: str
    stdout_tail: str
    duration_seconds: float
    timed_out: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_dirs(paths: Iterable[str], *, root: Path) -> list[Path]:
    dirs: list[Path] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text)
        resolved = path if path.is_absolute() else (root / path)
        resolved = resolved.resolve()
        if resolved.exists() and resolved.is_dir():
            dirs.append(resolved)
    # Stable uniqueness
    unique: list[Path] = []
    seen: set[str] = set()
    for path in dirs:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def discover_pdfs(source_dirs: Iterable[Path]) -> list[Path]:
    items: list[Path] = []
    for source_dir in source_dirs:
        for path in sorted(source_dir.rglob("*.pdf")):
            if path.is_file():
                items.append(path)
    return items


def _normalize_pdfs(paths: Iterable[str], *, root: Path) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        text = str(raw or "").strip()
        if not text:
            continue
        path = Path(text)
        resolved = path if path.is_absolute() else (root / path)
        resolved = resolved.resolve()
        if resolved.exists() and resolved.is_file() and resolved.suffix.lower() == ".pdf":
            files.append(resolved)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in files:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _safe_slug(value: str) -> str:
    clean = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or ""))
    while "__" in clean:
        clean = clean.replace("__", "_")
    return clean.strip("_") or "unknown"


def _has_markdown_output(output_dir: Path) -> bool:
    if not output_dir.exists() or not output_dir.is_dir():
        return False
    for path in output_dir.glob("*.md"):
        if path.is_file():
            return True
    return False


def _vector_db_path(*, root: Path) -> Path:
    return (root / "PDF_Repository" / "private_compendium" / "_vector" / "vector_index.sqlite").resolve()


def _is_pdf_chunked(*, root: Path, pdf_path: Path) -> bool:
    db_path = _vector_db_path(root=root)
    if not db_path.exists():
        return False
    cid = _safe_slug(pdf_path.stem)
    try:
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE compendium_id = ?",
            (cid,),
        ).fetchone()
        conn.close()
        return bool(row and int(row[0] or 0) > 0)
    except Exception:
        return False


def _docling_command_template() -> str:
    return str(
        os.getenv(
            "DOCLING_CMD_TEMPLATE",
            'docling "{input}" --output "{output_dir}"',
        )
    ).strip()


def _render_command(template: str, *, input_pdf: Path, output_dir: Path) -> str:
    # Template placeholders:
    # - {input}: absolute PDF path
    # - {output_dir}: absolute output folder for this PDF
    # - {output_base}: absolute output folder root for the batch
    return template.format(
        input=str(input_pdf),
        output_dir=str(output_dir),
        output_base=str(output_dir.parent),
        device="{device}",
    )


def detect_nvidia_gpu() -> dict:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return {"available": False, "gpus": []}
    if proc.returncode != 0:
        return {"available": False, "gpus": [], "error": (proc.stderr or "").strip()}
    gpus = []
    for line in (proc.stdout or "").splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 3:
            continue
        gpus.append(
            {
                "name": parts[0],
                "driver_version": parts[1],
                "memory_total_mib": parts[2],
            }
        )
    return {"available": bool(gpus), "gpus": gpus}


def resolve_device(preferred: str, gpu_info: dict) -> str:
    value = str(preferred or "auto").strip().lower()
    if value in {"cpu", "cuda"}:
        return value
    if gpu_info.get("available"):
        return "cuda"
    return "cpu"


def _run_single_docling(
    *,
    template: str,
    input_pdf: Path,
    output_dir: Path,
    dry_run: bool,
    device: str,
    live_output: bool,
    progress_prefix: str = "",
    timeout_seconds: int = 1800,
    heartbeat_seconds: int = 15,
) -> DoclingJobResult:
    command = _render_command(template, input_pdf=input_pdf, output_dir=output_dir).replace("{device}", device)
    if dry_run:
        return DoclingJobResult(
            source_pdf=str(input_pdf),
            output_dir=str(output_dir),
            status="dry_run",
            command=command,
            return_code=None,
            stderr_tail="",
            stdout_tail="",
            duration_seconds=0.0,
            timed_out=False,
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "DOCLING_DEVICE": device,
        "TORCH_DEVICE": device,
    }

    started = time.monotonic()

    if live_output:
        proc = subprocess.Popen(  # noqa: S602 - command template is user-controlled by design
            command,
            shell=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
        )
        merged_lines: list[str] = []
        timed_out = False
        last_output_at = started
        selector = selectors.DefaultSelector()
        if proc.stdout is not None:
            selector.register(proc.stdout, selectors.EVENT_READ)

        while True:
            now = time.monotonic()
            elapsed = now - started
            if timeout_seconds > 0 and elapsed > timeout_seconds:
                timed_out = True
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()
                break

            events = selector.select(timeout=1.0)
            if events:
                for key, _ in events:
                    stream = key.fileobj
                    raw_line = stream.readline()
                    if raw_line == "":
                        continue
                    line = str(raw_line or "").rstrip("\n")
                    if line:
                        merged_lines.append(line)
                        if len(merged_lines) > 60:
                            merged_lines = merged_lines[-60:]
                        last_output_at = now
                        if progress_prefix:
                            print(f"{progress_prefix} {line}")
                        else:
                            print(line)
            else:
                if heartbeat_seconds > 0 and (now - last_output_at) >= heartbeat_seconds:
                    elapsed_int = int(elapsed)
                    if progress_prefix:
                        print(f"{progress_prefix} ...still running ({elapsed_int}s elapsed)")
                    else:
                        print(f"...still running ({elapsed_int}s elapsed)")
                    last_output_at = now

            if proc.poll() is not None:
                break

        duration = time.monotonic() - started
        stdout_tail = "\n".join(merged_lines[-20:])
        stderr_tail = "Timed out." if timed_out else ""
        return DoclingJobResult(
            source_pdf=str(input_pdf),
            output_dir=str(output_dir),
            status="timed_out" if timed_out else ("ok" if proc.returncode == 0 else "failed"),
            command=command,
            return_code=proc.returncode,
            stderr_tail=stderr_tail,
            stdout_tail=stdout_tail,
            duration_seconds=duration,
            timed_out=timed_out,
        )

    timed_out = False
    try:
        proc = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            check=False,
            env=env,
            timeout=timeout_seconds if timeout_seconds > 0 else None,
        )
        stderr_tail = "\n".join((proc.stderr or "").strip().splitlines()[-20:])
        stdout_tail = "\n".join((proc.stdout or "").strip().splitlines()[-20:])
        status = "ok" if proc.returncode == 0 else "failed"
        return_code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout_tail = "\n".join(str(exc.stdout or "").splitlines()[-20:])
        stderr_tail = "\n".join((str(exc.stderr or "").splitlines() + ["Timed out."])[-20:])
        status = "timed_out"
        return_code = None
    duration = time.monotonic() - started
    return DoclingJobResult(
        source_pdf=str(input_pdf),
        output_dir=str(output_dir),
        status=status,
        command=command,
        return_code=return_code,
        stderr_tail=stderr_tail,
        stdout_tail=stdout_tail,
        duration_seconds=duration,
        timed_out=timed_out,
    )


def run_docling_batch(
    *,
    source_dirs: Iterable[str] | None = None,
    source_pdfs: Iterable[str] | None = None,
    output_root: str = DEFAULT_OUTPUT_DIR,
    dry_run: bool = False,
    limit: int = 0,
    verbose: bool = True,
    device: str = "auto",
    live_output: bool = False,
    resume: bool = True,
    timeout_seconds: int = 1800,
    heartbeat_seconds: int = 15,
) -> dict:
    root = _repo_root()
    source_dir_values = list(source_dirs or DEFAULT_SOURCE_DIRS)
    source_paths = _normalize_dirs(source_dir_values, root=root)
    explicit_pdfs = _normalize_pdfs(list(source_pdfs or []), root=root)
    out_root = (root / output_root).resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / DEFAULT_MANIFEST_NAME
    status_path = out_root / DEFAULT_STATUS_NAME
    cmd_template = _docling_command_template()
    gpu_info = detect_nvidia_gpu()
    selected_device = resolve_device(device, gpu_info)

    pdfs = explicit_pdfs or discover_pdfs(source_paths)
    if limit > 0:
        pdfs = pdfs[:limit]

    successful_from_previous: set[str] = set()
    if resume and manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            for row in previous.get("results") or []:
                if not isinstance(row, dict):
                    continue
                if str(row.get("status") or "").strip().lower() != "ok":
                    continue
                source_pdf = str(row.get("source_pdf") or "").strip()
                if source_pdf:
                    successful_from_previous.add(source_pdf)
        except Exception:
            successful_from_previous = set()

    results: list[DoclingJobResult] = []
    skipped_from_manifest: list[str] = []
    skipped_from_existing_output: list[str] = []
    pending_pdfs: list[Path] = []
    for pdf_path in pdfs:
        out_dir = out_root / _safe_slug(pdf_path.stem)
        if str(pdf_path) in successful_from_previous:
            skipped_from_manifest.append(str(pdf_path))
            continue
        if resume and _has_markdown_output(out_dir):
            skipped_from_existing_output.append(str(pdf_path))
            if verbose:
                rel = pdf_path.relative_to(root) if str(pdf_path).startswith(str(root)) else pdf_path
                print(f"[docling] SKIP    {rel} (markdown already exists)")
            continue
        pending_pdfs.append(pdf_path)
    skipped = skipped_from_manifest + skipped_from_existing_output

    preexisting_chunked: list[str] = []
    for pdf_path in pdfs:
        if _is_pdf_chunked(root=root, pdf_path=pdf_path):
            preexisting_chunked.append(str(pdf_path))

    def write_status(payload: dict) -> None:
        status_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    started_at = datetime.now(timezone.utc).isoformat()
    write_status({
        "state": "running",
        "started_at": started_at,
        "pid": os.getpid(),
        "repo_root": str(root),
        "output_root": str(out_root),
        "manifest_path": str(manifest_path),
        "source_dirs": [str(p) for p in source_paths],
        "source_pdfs": [str(p) for p in explicit_pdfs],
        "selected_device": selected_device,
        "total": len(pending_pdfs),
        "completed": 0,
        "skipped": len(skipped),
        "skipped_manifest": len(skipped_from_manifest),
        "skipped_existing_markdown": len(skipped_from_existing_output),
        "chunked_detected": len(preexisting_chunked),
        "current_pdf": "",
        "updated_at": started_at,
    })

    total = len(pending_pdfs)
    for idx, pdf_path in enumerate(pdfs, start=1):
        out_dir = out_root / _safe_slug(pdf_path.stem)
        if str(pdf_path) in successful_from_previous:
            if verbose:
                rel = pdf_path.relative_to(root) if str(pdf_path).startswith(str(root)) else pdf_path
                print(f"[docling] SKIP    {rel} (already ok in previous manifest)")
            continue
        if resume and _has_markdown_output(out_dir):
            continue
        rel = pdf_path.relative_to(root) if str(pdf_path).startswith(str(root)) else pdf_path
        output_dir = out_dir
        run_idx = len(results) + 1
        progress_prefix = f"[docling {run_idx}/{total}]"
        write_status({
            "state": "running",
            "started_at": started_at,
            "pid": os.getpid(),
            "repo_root": str(root),
            "output_root": str(out_root),
            "manifest_path": str(manifest_path),
            "source_dirs": [str(p) for p in source_paths],
            "source_pdfs": [str(p) for p in explicit_pdfs],
            "selected_device": selected_device,
            "total": len(pending_pdfs),
            "completed": len(results),
            "skipped": len(skipped),
            "current_pdf": str(pdf_path),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if verbose:
            percent = int((run_idx / total) * 100) if total else 100
            print(f"{progress_prefix} START {rel} ({selected_device}, {percent}%)")
        result = _run_single_docling(
            template=cmd_template,
            input_pdf=pdf_path,
            output_dir=output_dir,
            dry_run=dry_run,
            device=selected_device,
            live_output=live_output,
            progress_prefix=progress_prefix if live_output else "",
            timeout_seconds=max(0, int(timeout_seconds or 0)),
            heartbeat_seconds=max(0, int(heartbeat_seconds or 0)),
        )
        results.append(result)
        if verbose:
            dur = int(result.duration_seconds)
            print(f"{progress_prefix} {result.status.upper():9} {rel} ({selected_device}, {dur}s)")

    summary = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "repo_root": str(root),
        "source_dirs": [str(p) for p in source_paths],
        "output_root": str(out_root),
        "docling_command_template": cmd_template,
        "selected_device": selected_device,
        "gpu_info": gpu_info,
        "dry_run": dry_run,
        "resume": resume,
        "total": len(results),
        "ok": sum(1 for r in results if r.status == "ok"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "timed_out": sum(1 for r in results if r.status == "timed_out"),
        "dry_run_count": sum(1 for r in results if r.status == "dry_run"),
        "skipped_count": len(skipped),
        "skipped_manifest_count": len(skipped_from_manifest),
        "skipped_existing_markdown_count": len(skipped_from_existing_output),
        "chunked_detected_count": len(preexisting_chunked),
        "skipped": skipped,
        "skipped_manifest": skipped_from_manifest,
        "skipped_existing_markdown": skipped_from_existing_output,
        "chunked_detected": preexisting_chunked,
        "results": [asdict(r) for r in results],
    }
    manifest_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    write_status({
        "state": "completed",
        "started_at": started_at,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "pid": os.getpid(),
        "repo_root": str(root),
        "output_root": str(out_root),
        "manifest_path": str(manifest_path),
        "source_dirs": [str(p) for p in source_paths],
        "source_pdfs": [str(p) for p in explicit_pdfs],
        "selected_device": selected_device,
        "total": len(pending_pdfs),
        "completed": len(results),
        "skipped": len(skipped),
        "skipped_manifest": len(skipped_from_manifest),
        "skipped_existing_markdown": len(skipped_from_existing_output),
        "chunked_detected": len(preexisting_chunked),
        "current_pdf": "",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ok": summary["ok"],
        "failed": summary["failed"],
        "timed_out": summary["timed_out"],
    })
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m Plugins.docling.runner",
        description="Run Docling extraction batch across source PDFs and write a manifest.",
    )
    parser.add_argument(
        "--source-dir",
        action="append",
        default=[],
        help="Source directory to scan for PDFs. Can be provided multiple times.",
    )
    parser.add_argument(
        "--pdf",
        action="append",
        default=[],
        help="Specific PDF path to process. Can be provided multiple times.",
    )
    parser.add_argument(
        "--output-root",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output root for extracted files (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Process only the first N PDFs (0 = all).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not execute Docling, only write planned commands to manifest.",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda"],
        default="auto",
        help="Execution device hint. Passed through env and template placeholder {device}.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file progress logs.",
    )
    parser.add_argument(
        "--live-output",
        action="store_true",
        help="Stream Docling output line-by-line while each PDF is processed.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore previous manifest and reprocess all discovered PDFs.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=0,
        help="Per-file timeout. 0 disables timeout (default: disabled).",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=int,
        default=15,
        help="When --live-output is enabled, print heartbeat when no new lines arrive (default: 15).",
    )
    parser.add_argument(
        "--print-example-template",
        action="store_true",
        help="Print a command-template example and exit.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.print_example_template:
        example = 'DOCLING_CMD_TEMPLATE=\'docling "{input}" --output "{output_dir}"\''
        print(example)
        return 0

    chosen_sources = args.source_dir if args.source_dir else list(DEFAULT_SOURCE_DIRS)
    summary = run_docling_batch(
        source_dirs=chosen_sources,
        source_pdfs=args.pdf or [],
        output_root=args.output_root,
        dry_run=bool(args.dry_run),
        limit=max(0, int(args.limit or 0)),
        verbose=not bool(args.quiet),
        device=str(args.device or "auto"),
        live_output=bool(args.live_output),
        resume=not bool(args.no_resume),
        timeout_seconds=max(0, int(args.timeout_seconds or 0)),
        heartbeat_seconds=max(0, int(args.heartbeat_seconds or 0)),
    )
    print(
        "[docling] total={total} ok={ok} failed={failed} timed_out={timed_out} dry_run={dry_run_count} skipped={skipped_count} chunked_seen={chunked_detected_count}".format(
            **summary
        )
    )
    print(f"[docling] manifest={summary['output_root']}/{DEFAULT_MANIFEST_NAME}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
