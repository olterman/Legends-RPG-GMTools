# CSRD Markdown Source

This folder is reserved for markdown derived from the addon-owned raw source in:
- `../source/`

For `GMForge`, markdown is the canonical parsing substrate for sourcebook ingestion.

The intended flow is:
1. raw CSRD source document lives in `source/`
2. bundled `docling` converts the source into markdown here
3. CSRD addon parsers/importers read markdown from this folder

This folder is intentionally empty until the CSRD docling pass is run.
