# AI Config Enrichment Prompt

Use `docs/lore_config_enrichment_candidates.json` as source material.

Goal:
- Expand `config/worlds/lands_of_legends/10_races.yaml`, `config/worlds/lands_of_legends/12_areas.yaml`, `config/worlds/lands_of_legends/20_settlements.yaml`, and `config/worlds/lands_of_legends/21_encounters.yaml`.
- Keep compatibility with existing schema.
- Prioritize high-confidence candidates first.

Rules:
- Do not change existing keys unless needed for typo fix or aliasing.
- Keep new keys snake_case and stable.
- For each added area, also add matching `settlements` and `encounters` blocks.
- Write hooks/truths/complications in the same style as existing encounter config.
- Use evidence lines and source titles to keep additions lore-faithful.

Review checklist:
1. No duplicate semantic entries (`the_sands` vs `sands`).
2. No generic placeholders left in final YAML.
3. Added entries are grounded in lore evidence.
4. `POST /reload` works and generation endpoints still return results.
