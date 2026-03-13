# Roadmap: Vector Database from World Files

## Objective
Build a local vector database pipeline that indexes world/genre content for semantic retrieval in:
- Search assistance
- Generation context enrichment
- Lore authoring workflows

Sources should include:
- `config/worlds/*`
- `config/settings/*`
- `config/core/*`
- `lore/entries/*`
- optional private compendium content (`PDF_Repository/private_compendium/*`)

## Principles
- Keep legal/private materials local only.
- Preserve source traceability for every chunk.
- Make indexing deterministic and repeatable.
- Allow filtering by `genre`, `setting`, `area`, `type`, and `source`.

## Phase 1: Data Model and Contracts
- Define canonical `VectorDoc` schema:
  - `id`
  - `text`
  - `source_path`
  - `source_kind` (`config`, `lore`, `official_compendium`, `csrd`, `storage`)
  - `type`
  - `genre`
  - `setting`
  - `settings[]`
  - `area`
  - `location`
  - `book`
  - `pages`
  - `updated_at`
- Define chunking strategy:
  - YAML section-level chunks
  - lore heading/paragraph chunks
  - compendium field-aware chunks
- Define embedding contract:
  - provider abstraction
  - model/version stamp
  - max token length

Done when:
- Schema is documented and versioned.
- Chunking rules are tested on sample files.

## Phase 2: Index Builder CLI
- Add `scripts/build_vector_index.py` with commands:
  - `scan`
  - `embed`
  - `build`
  - `verify`
- Add stable content hashing:
  - chunk hash for incremental rebuilds
  - skip unchanged chunks
- Write artifacts under local ignored path:
  - `storage/vector_index/`

Done when:
- Full build runs end-to-end locally.
- Incremental rebuild skips unchanged chunks.

## Phase 3: Storage Engine
- Start with a local, simple backend (SQLite + vectors or local vector store).
- Add backend abstraction so we can swap later (FAISS/Chroma/pgvector/etc.).
- Store:
  - embeddings
  - metadata
  - source snippet preview
  - chunk hash

Done when:
- Top-k retrieval works with metadata filters.
- Rebuild does not duplicate entries.

## Phase 4: Retrieval API
- Add endpoints:
  - `POST /vector/query`
  - `POST /vector/reindex`
  - `GET /vector/stats`
- Query supports:
  - `q`
  - `k`
  - `genre`
  - `setting`
  - `type`
  - `source_kind`
  - `area`
- Return citations:
  - `source_path`
  - title/section label
  - similarity score

Done when:
- Queries return relevant chunks + source references.
- Filters correctly narrow result sets.

## Phase 5: UI Integration
- Add optional “Semantic Search” mode in Search page.
- Add “Use as Context” action for generation forms.
- Add source chips on retrieved chunks:
  - `Genre`
  - `Setting`
  - `Source`
  - `Book/Page` (if applicable)

Done when:
- User can run semantic query and open source record directly.
- Generation can inject selected retrieval snippets.

## Phase 6: Authoring and QA Workflows
- Add “Find similar lore” helper in lore editor.
- Add duplicate/conflict detection:
  - semantically similar entries across files
- Add nightly/commanded integrity checks.

Done when:
- Lore editing shows semantic neighbors.
- Duplicate candidates are surfaced with confidence scores.

## Phase 7: Performance and Quality
- Add benchmark fixtures:
  - query latency
  - indexing time
  - memory/storage footprint
- Tune chunking + overlap + embedding model.
- Add relevance evaluation set (golden queries).

Done when:
- Retrieval latency stays within target on local hardware.
- Relevance meets agreed quality threshold.

## Security and Privacy
- Keep private compendium chunks local and excluded from git sync.
- Add config flag for including/excluding official private sources.
- Log index builds and query access for debugging only (no sensitive payload dumps).

## Migration and Versioning
- Add index schema version (`vector_schema_version`).
- Add embedding model version (`embedding_model_version`).
- Provide safe rebuild path on version mismatch.

## Initial Deliverables (Recommended Sprint Slice)
1. `VectorDoc` schema + docs.
2. CLI index builder for config + lore only.
3. Local vector storage and query endpoint.
4. Basic semantic search UI card in Search page.

## Risks
- Embedding model/provider changes break comparability.
- Over-chunking causes noisy retrieval.
- Large private corpora increase index build time.

## Mitigations
- Version-stamp embeddings and force rebuild when needed.
- Start conservative chunking, then tune with eval queries.
- Support incremental indexing and source scoping.
