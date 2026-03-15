from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_CMD_TEMPLATE = '{docling_cmd} "{input}" --to md --to html --output "{output_dir}" --device {device}'
MANIFEST_NAME = "docling_manifest.json"


@dataclass
class DoclingConversionPlan:
    source_path: str
    markdown_output_dir: str
    html_output_dir: str
    expected_markdown_path: str
    expected_html_path: str
    command: str
    device: str
    dry_run: bool


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def resolve_markdown_dir(source_path: Path) -> Path:
    resolved = source_path.resolve()
    if resolved.parent.name != "source":
        raise ValueError("source_path must live inside an addon-owned 'source/' folder")
    return resolved.parent.parent / "source_markdown"


def resolve_html_dir(source_path: Path) -> Path:
    resolved = source_path.resolve()
    if resolved.parent.name != "source":
        raise ValueError("source_path must live inside an addon-owned 'source/' folder")
    return resolved.parent.parent / "source_html"


def expected_markdown_path(source_path: Path) -> Path:
    return resolve_markdown_dir(source_path) / f"{source_path.stem}.md"


def expected_html_path(source_path: Path) -> Path:
    return resolve_html_dir(source_path) / f"{source_path.stem}.html"


def command_template() -> str:
    return str(os.getenv("DOCLING_CMD_TEMPLATE", DEFAULT_CMD_TEMPLATE)).strip()


def default_docling_command() -> str:
    venv_docling = (_repo_root() / ".venv" / "bin" / "docling").resolve()
    if venv_docling.exists():
        return str(venv_docling)
    return "docling"


def render_command(*, source_path: Path, output_dir: Path, device: str) -> str:
    template = command_template()
    return template.format(
        docling_cmd=default_docling_command(),
        input=str(source_path.resolve()),
        output_dir=str(output_dir.resolve()),
        output_base=str(output_dir.parent.resolve()),
        device=device,
    )


def build_conversion_plan(source_path: Path, *, device: str = "auto", dry_run: bool = False) -> DoclingConversionPlan:
    resolved_source = source_path.resolve()
    markdown_dir = resolve_markdown_dir(resolved_source)
    html_dir = resolve_html_dir(resolved_source)
    return DoclingConversionPlan(
        source_path=str(resolved_source),
        markdown_output_dir=str(markdown_dir),
        html_output_dir=str(html_dir),
        expected_markdown_path=str(expected_markdown_path(resolved_source)),
        expected_html_path=str(expected_html_path(resolved_source)),
        command=render_command(source_path=resolved_source, output_dir=markdown_dir, device=device),
        device=device,
        dry_run=dry_run,
    )


def write_manifest(
    plan: DoclingConversionPlan,
    *,
    status: str,
    stderr: str = "",
    stdout: str = "",
    markdown_exists: bool | None = None,
    html_exists: bool | None = None,
) -> Path:
    markdown_output_dir = Path(plan.markdown_output_dir)
    markdown_output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = markdown_output_dir / MANIFEST_NAME
    payload = {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan": asdict(plan),
        "artifacts": {
            "markdown_exists": markdown_exists,
            "html_exists": html_exists,
        },
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return manifest_path


def run_conversion(
    source_path: Path,
    *,
    device: str = "auto",
    dry_run: bool = False,
    require_html: bool = False,
) -> DoclingConversionPlan:
    plan = build_conversion_plan(source_path, device=device, dry_run=dry_run)
    if dry_run:
        write_manifest(plan, status="dry_run", markdown_exists=False, html_exists=False)
        return plan

    markdown_output_dir = Path(plan.markdown_output_dir)
    html_output_dir = Path(plan.html_output_dir)
    markdown_output_dir.mkdir(parents=True, exist_ok=True)
    html_output_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(  # noqa: S602 - command template is intentionally configurable
        plan.command,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
        cwd=str(_repo_root()),
    )
    generated_html_in_markdown_dir = markdown_output_dir / Path(plan.expected_html_path).name
    if generated_html_in_markdown_dir.exists() and generated_html_in_markdown_dir.is_file():
        shutil.move(str(generated_html_in_markdown_dir), str(html_output_dir / generated_html_in_markdown_dir.name))
    markdown_path = Path(plan.expected_markdown_path)
    html_path = Path(plan.expected_html_path)
    markdown_exists = markdown_path.exists() and markdown_path.is_file()
    html_exists = html_path.exists() and html_path.is_file()
    conversion_ok = proc.returncode == 0 and markdown_exists and (html_exists or not require_html)
    status = "ok" if conversion_ok else "failed"
    write_manifest(
        plan,
        status=status,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        markdown_exists=markdown_exists,
        html_exists=html_exists,
    )
    if not conversion_ok:
        raise RuntimeError(f"docling conversion failed for {source_path}")
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.plugins.docling.runner")
    parser.add_argument("--source", required=True, help="Addon-owned source document inside a 'source/' folder.")
    parser.add_argument("--device", default="auto", help="Device hint passed into the Docling command template.")
    parser.add_argument("--dry-run", action="store_true", help="Render the plan and write a dry-run manifest only.")
    parser.add_argument("--require-html", action="store_true", help="Fail if the expected html artifact is not produced.")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    source_path = Path(str(args.source)).resolve()
    if not source_path.exists() or not source_path.is_file():
        raise SystemExit(f"source file not found: {source_path}")
    plan = run_conversion(
        source_path,
        device=str(args.device),
        dry_run=bool(args.dry_run),
        require_html=bool(args.require_html),
    )
    print(json.dumps(asdict(plan), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
