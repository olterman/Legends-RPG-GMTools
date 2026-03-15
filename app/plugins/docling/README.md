# Docling Plugin

`docling` remains a plugin in architecture, but it is intended to ship bundled with `GMForge`.

Responsibilities:
- convert addon-owned raw documents into markdown and html
- keep document extraction logic out of `app/core`
- provide a common markdown-first ingestion path for addon parsers
- target addon-local `source/ -> source_markdown/` flows instead of writing to a global extraction folder
- support addon-local `source/ -> source_html/` reading artifacts for browser rulebooks

The expected flow is:
1. addon raw source lives in `app/systems/.../addons/.../source/`
2. `docling` converts that source into addon-owned markdown and html
3. addon parser/importer reads markdown
4. addon site reading surfaces may serve the html artifact
5. addon importer writes canonical records through the core content service

The bundled runner is intentionally thin:
- it resolves addon-owned markdown output locations
- it resolves addon-owned html output locations
- it renders a Docling command template
- it can write a small conversion manifest beside the markdown output
- by default it uses the repo-local `.venv/bin/docling` binary when available
- it requests both `md` and `html` outputs and relocates generated html into the addon `source_html/` folder

Example:

```bash
python -m app.plugins.docling.runner \
  --source app/systems/cypher/addons/csrd/source/Cypher-System-Reference-Document-2025-08-22.docx \
  --dry-run
```
