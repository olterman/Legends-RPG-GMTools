# Docling Plugin (Tiny Starter)

This plugin adds a small batch runner that scans source PDFs and calls Docling to produce higher-quality extracted source files.

The runner is intentionally simple so we can iterate quickly as we tune parser quality.

## What it does
- Scans PDF source folders under `PDF_Repository/` (defaults listed below).
- Executes a Docling command template per PDF.
- Writes outputs under:
  - `PDF_Repository/private_compendium/_docling/<pdf_slug>/`
- Writes batch manifest:
  - `PDF_Repository/private_compendium/_docling/batch_manifest.json`
- Writes runner status:
  - `PDF_Repository/private_compendium/_docling/runner_status.json`

## Default source folders
- `PDF_Repository/Genre_Books`
- `PDF_Repository/Setting_Books`
- `PDF_Repository/Core_Rules`

## Usage

Dry run (recommended first):

```bash
python -m Plugins.docling.runner --dry-run
```

Run extraction:

```bash
python -m Plugins.docling.runner
```

Run only one specific PDF:

```bash
python -m Plugins.docling.runner --pdf "PDF_Repository/Genre_Books/Godforsaken.pdf"
```

Prefer CUDA explicitly:

```bash
python -m Plugins.docling.runner --device cuda
```

Show per-file live Docling output:

```bash
python -m Plugins.docling.runner --device cuda --live-output
```

Add timeout + heartbeat (recommended):

```bash
python -m Plugins.docling.runner --device cuda --live-output --timeout-seconds 1200 --heartbeat-seconds 10
```

Optional: limit to first 3 PDFs:

```bash
python -m Plugins.docling.runner --limit 3
```

By default, no limit is applied (`--limit 0`), so the full discovered PDF set is processed.

Resume behavior (default):
- The runner reads the previous batch manifest and skips PDFs that already finished with status `ok`.
- The runner also skips PDFs when markdown output already exists in `_docling/<pdf_slug>/`, even if a prior manifest is missing/incomplete.
- Use `--no-resume` to force reprocessing all discovered PDFs.

```bash
python -m Plugins.docling.runner --device cuda
python -m Plugins.docling.runner --device cuda --no-resume
```

Custom source directories:

```bash
python -m Plugins.docling.runner \
  --source-dir PDF_Repository/Genre_Books \
  --source-dir PDF_Repository/Setting_Books
```

## Docling command template

The runner uses environment variable `DOCLING_CMD_TEMPLATE` and substitutes:
- `{input}` = absolute source PDF path
- `{output_dir}` = absolute output folder for current PDF
- `{output_base}` = absolute batch output root
- `{device}` = selected device (`cpu` or `cuda`)

Default template:

```bash
docling "{input}" --output "{output_dir}"
```

If your Docling CLI syntax differs, override it:

```bash
export DOCLING_CMD_TEMPLATE='docling "{input}" --output "{output_dir}"'
python -m Plugins.docling.runner
```

Example with device placeholder:

```bash
export DOCLING_CMD_TEMPLATE='docling "{input}" --output "{output_dir}" --device {device}'
python -m Plugins.docling.runner --device auto
```

## Notes
- `PDF_Repository/` is gitignored in this project, so outputs stay local/private.
- If `docling` is not installed/available, jobs will fail and the manifest captures stderr tails for diagnosis.
- Batch manifest now includes detected GPU info from `nvidia-smi` and selected execution device.
- Progress logs now include `[current/total]` markers, and `--live-output` streams Docling logs during execution.
- Manifest now also tracks skipped files when resume mode is active.
- Manifest/status now include:
  - skipped via previous manifest
  - skipped via existing markdown output
  - PDFs already detected as chunked in vector DB
- Timeout is disabled by default; set `--timeout-seconds` only if you want forced per-file cutoffs.

## Hybrid Chunking + Vector DB

Build a local vector database from:
- Docling markdown outputs
- Official/sourcebook JSON cards in `PDF_Repository/private_compendium`
- Local library/storage JSON cards in `storage/`

```bash
python -m Plugins.docling.vector_index build
```

Build only one compendium:

```bash
python -m Plugins.docling.vector_index build --compendium-id godforsaken
```

Build only local library cards:

```bash
python -m Plugins.docling.vector_index build --compendium-id local_library
```

Skip official cards or local storage cards when needed:

```bash
python -m Plugins.docling.vector_index build --no-official-cards
python -m Plugins.docling.vector_index build --no-storage-cards
```

Run a semantic query from CLI:

```bash
python -m Plugins.docling.vector_index query --q "necromancer black dog despair" --k 5
```

Show index stats:

```bash
python -m Plugins.docling.vector_index stats
```

Artifacts are written under:
- `PDF_Repository/private_compendium/_vector/vector_index.sqlite`
- `PDF_Repository/private_compendium/_vector/build_manifest.json`
