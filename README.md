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
- `/search` - Unified Search (Local/Lore/CSRD with source filters)
- `/library` - Legacy alias to `/search`
- `/compendium-browser` - Legacy alias to `/search`
- `/lore-browser` - Legacy alias to `/search`
- `/prompt-browser` - Legacy alias to `/search`
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

Configuration is layered and loaded at startup:

- Global registry: `config/02_settings.yaml`
- Core shared: `config/core/*.yaml`
- Genre shared: `config/settings/<genre_id>/*.yaml`
- Setting overrides: `config/worlds/<setting_id>/*.yaml`

Current active setting examples:
- `config/core/14_monster_roles.yaml`
- `config/settings/fantasy/11_professions.yaml`
- `config/worlds/lands_of_legends/10_races.yaml`
- `config/worlds/lands_of_legends/12_areas.yaml`
- `config/worlds/lands_of_legends/20_settlements.yaml`
- `config/worlds/lands_of_legends/21_encounters.yaml`
- `config/worlds/lands_of_legends/22_cyphers.yaml`
- `config/worlds/lands_of_legends/24_names.yaml`

After changing YAML files, call `POST /reload` to apply updates without restart.

### AI-Assisted Lore Config Enrichment

Use this to derive new race/place candidates from `lore/entries/*.json` and generate reviewable YAML.

```bash
PYTHONPATH=. .venv/bin/python scripts/build_lore_config_enrichment.py
```

Generated artifacts:
- `docs/lore_config_enrichment_candidates.json` (candidate list + evidence)
- `docs/lore_config_enrichment.generated.yaml` (draft `races`, `areas`, `settlements`, `encounters`)
- `docs/AI_CONFIG_ENRICHMENT_PROMPT.md` (prompt template for AI-assisted refinement)

To write draft additions directly into live config loading (review first):

```bash
PYTHONPATH=. .venv/bin/python scripts/build_lore_config_enrichment.py --yaml-out config/worlds/lands_of_legends/90_lore_enrichment.yaml
```

Then reload config:

```bash
curl -X POST http://localhost:5000/reload
```

## Docker

Build:
```bash
docker build -t legends-gmtools .
```

Run:
```bash
docker run --rm -p 5000:5000 legends-gmtools
```

### Docker Compose (recommended for server deploy)
```bash
docker compose up -d --build
```

This uses `docker-compose.yml` and mounts `storage`, `lore`, `images`, and `config` as persistent host volumes.

## Quick Local-Server Deploy Workflow

### 1. Configure deploy target
```bash
cp .env.deploy.example .env.deploy
```
Set:
- `DEPLOY_USER`
- `DEPLOY_HOST`
- `DEPLOY_PATH`
- optional `DEPLOY_PORT` and `APP_PORT`

### 2. Deploy to server (sync + rebuild + restart)
```bash
bash scripts/deploy_local_server.sh
```

## Automatic Image Upload on Version Commits

This repo includes a post-commit hook that uploads `images/` to your server **only when both**:
- `VERSION` changed in the commit, and
- files under `images/` changed in the same commit.

### 1. Enable hooks
```bash
bash scripts/setup_git_hooks.sh
chmod +x .githooks/post-commit scripts/upload_images_if_version_bumped.sh scripts/deploy_local_server.sh scripts/setup_git_hooks.sh
```

### 2. Use it
- Bump `VERSION`
- Commit image changes and version bump together
- Hook uploads `images/` automatically to `${DEPLOY_PATH}/images`

You can also run it manually:
```bash
bash scripts/upload_images_if_version_bumped.sh
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
