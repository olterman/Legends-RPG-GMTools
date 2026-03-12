# Lands of Legends GM-Tools

Flask-based GM utilities for the **Lands of Legends** setting.

## What It Does

- Generate `character`, `npc`, `monster`, `settlement`, `encounter`, `cypher`, and `inn` content
- Save generated outputs automatically to local JSON records
- Browse saved outputs in a library UI
- Browse parsed Cypher System creatures, cyphers, character types, flavors, descriptors, foci, and abilities in a compendium UI

## Quick Start

### 1. Install
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run
```bash
python run.py
```

Open: `http://localhost:5000`

### 3. Main Routes

- `/` - Main generator
- `/map-tools` - Settlement/encounter/cypher/inn tools
- `/library` - Saved generated results
- `/compendium-browser` - Compendium browser
- `/lore-browser` - Lore browser (prompt-stripped lore text)
- `/prompt-browser` - Prompt browser (lore/art prompts)
- `/config-enrichment` - Curated lore-to-config review/apply UI

## API Docs

Detailed endpoint and payload docs live here:
- [API Reference](/home/olterman/Projects/Legends-RPG-GMTools/docs/API.md)

## Contributor Notes

### Core files

- App entrypoint: [`run.py`](/home/olterman/Projects/Legends-RPG-GMTools/run.py)
- App factory: [`lol_api/app.py`](/home/olterman/Projects/Legends-RPG-GMTools/lol_api/app.py)
- Routes: [`lol_api/api.py`](/home/olterman/Projects/Legends-RPG-GMTools/lol_api/api.py)
- Generators: [`lol_api/generator.py`](/home/olterman/Projects/Legends-RPG-GMTools/lol_api/generator.py)
- Config loader: [`lol_api/config_loader.py`](/home/olterman/Projects/Legends-RPG-GMTools/lol_api/config_loader.py)
- Storage: [`lol_api/storage.py`](/home/olterman/Projects/Legends-RPG-GMTools/lol_api/storage.py)
- Compendium access: [`lol_api/compendium.py`](/home/olterman/Projects/Legends-RPG-GMTools/lol_api/compendium.py)

### Config files

Configuration is split across `config/*.yaml` and loaded at startup.

- `00_setting.yaml`
- `01_styles.yaml`
- `10_races.yaml`
- `11_professions.yaml`
- `12_environments.yaml`
- `13_npc_roles.yaml`
- `14_monster_roles.yaml`
- `15_monster_traits.yaml`
- `16_monster_names.yaml`
- `20_settlements.yaml`
- `21_encounters.yaml`
- `22.cyphers.yaml`
- `24_names.yaml`

After changing YAML files, call `POST /reload` to apply updates without restart.

### AI-Assisted Lore Config Enrichment

Use this to derive new race/place candidates from `lore/entries/*.json` and generate reviewable YAML.

```bash
PYTHONPATH=. .venv/bin/python scripts/build_lore_config_enrichment.py
```

Generated artifacts:
- `docs/lore_config_enrichment_candidates.json` (candidate list + evidence)
- `docs/lore_config_enrichment.generated.yaml` (draft `races`, `environments`, `settlements`, `encounters`)
- `docs/AI_CONFIG_ENRICHMENT_PROMPT.md` (prompt template for AI-assisted refinement)

To write draft additions directly into live config loading (review first):

```bash
PYTHONPATH=. .venv/bin/python scripts/build_lore_config_enrichment.py --yaml-out config/90_lore_enrichment.yaml
```

Then reload config:

```bash
curl -X POST http://localhost:5000/reload
```

### Legacy script

[`generate_content.py`](/home/olterman/Projects/Legends-RPG-GMTools/generate_content.py) remains available for CSV-driven text generation, but the primary workflow is the Flask app.

## Docker

Build:
```bash
docker build -t legends-gmtools .
```

Run:
```bash
docker run --rm -p 5000:5000 legends-gmtools
```

## Project Layout

```text
.
├── config/
├── docs/
│   └── API.md
├── lol_api/
├── CSRD/
├── storage/
├── generate_content.py
├── run.py
├── Dockerfile
└── requirements.txt
```
