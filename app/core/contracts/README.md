# Core Contracts

Canonical schemas, validation helpers, and shared interfaces live here.

Authored world-manifest schemas now live here too. Current canonical typed schemas cover:

- `top_level_region`
- `subregion`
- `village` / `city` / `settlement`
- `inn`

Legacy generators and importers should adapt into these canonical shapes instead of storing tool-specific JSON variants directly.
