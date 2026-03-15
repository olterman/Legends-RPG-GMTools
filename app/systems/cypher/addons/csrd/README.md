# CSRD

First real addon shell for `cypher`.

This addon is intended to host imported and normalized content from the Cypher System Reference Document.

Addon-owned source material lives in:
- `source/`

Addon-owned markdown output lives in:
- `source_markdown/`

Addon-owned html output lives in:
- `source_html/`

Parsing rule:
- raw documents stay addon-owned
- bundled `docling` converts raw source to markdown and html
- CSRD addon parsers consume markdown
- CSRD browser rulebook reading should prefer html when available
- canonical records are written through core services

Readable rulebook surface:
- `rulebook.json` declares the addon-owned markdown rulebook
- the core can generate heading anchors and a table of contents for site rendering
- html is a presentation artifact only, not the parser source of truth
