# Lands of Legends Generator

This project generates four kinds of content from CSV input and YAML config files:

* character prompts
* settlement prompts
* encounter seeds
* cyphers
* inns

The generator is designed for the **Lands of Legends** setting and uses your split YAML config so the world can grow without turning into one huge config file.

## Folder structure

```text
project/
├── config/
│   ├── 00_setting.yaml
│   ├── 01_styles.yaml
│   ├── 10_races.yaml
│   ├── 11_professions.yaml
│   ├── 12_environments.yaml
│   ├── 20_settlements.yaml
│   ├── 21_encounters.yaml
│   ├── 22_cyphers.yaml
│   └── 24_names.yaml
├── generate_content.py
├── content.csv
└── generated/
```

## What each file does

### `generate_content.py`

The main script.

It:

* loads all YAML files from `config/`
* reads rows from `content.csv`
* generates output based on the `type` column
* writes one text file per row into `generated/`
* also writes a combined `all_output.txt`

### `content.csv`

The input file.

Each row tells the generator what to create.

Supported `type` values:

* `character`
* `settlement`
* `encounter`
* `cypher`
* `inn`

### `config/00_setting.yaml`

Global world assumptions and generation defaults.

Use this when you want to change:

* setting summary
* world truths
* cultural themes
* default style block
* general generation defaults

### `config/01_styles.yaml`

Art style blocks.

Use this when you want to change:

* the main visual style prompt text
* character sheet style
* settlement style
* encounter style
* cypher style

### `config/10_races.yaml`

Race definitions.

Use this when you want to add or edit:

* a new race
* race lore themes
* race tone
* visual defaults
* race variants such as subcultures or lineages

Examples already supported:

* Alfirin
* Humans
* Uruk
* Lilim
* Fellic
* Gitz
* Vaettyr
* Duergar
* Velim

### `config/11_professions.yaml`

Character role templates.

Use this when you want to add or edit:

* a new profession
* appearance defaults
* clothing defaults
* weapon options
* gear options
* pose options
* lighting options

Examples already supported:

* rogue
* barbarian
* retired_warrior
* mage
* ranger
* assassin
* poet_warrior
* conqueror
* forge_guard

### `config/12_environments.yaml`

Environment definitions.

Use this when you want to add or edit:

* a new region
* a city-scale environment
* a wilderness region
* a ruin zone
* environmental visual traits
* environmental mood

Important: if an environment is referenced in CSV, it must exist here.

### `config/20_settlements.yaml`

Settlement generator tables by environment.

Use this when you want a given environment to produce:

* villages
* ports
* camps
* enclaves
* small cities
* local landmarks
* economies
* tensions
* atmosphere

Important: if you want `type=settlement` to work for an environment, that environment must also exist here.

### `config/21_encounters.yaml`

Encounter generator tables by environment.

Use this when you want a given environment to produce:

* first impressions
* subjects
* truths
* complications
* GM hooks

Important: if you want `type=encounter` to work for an environment, that environment must also exist here.

### `config/22_cyphers.yaml`

Cypher generator tables by environment.

Use this when you want a given environment to produce:

* cypher forms
* appearances
* effects
* limitations
* quirks

Important: if you want `type=cypher` to work for an environment, that environment must also exist here.

### `config/24_names.yaml`

Name generation tables.

Use this when you want to add or edit:

* character names by race
* variant-specific names
* settlement names by environment
* artifact names
* ship names
* clan names
* inn names

## CSV format

The script supports one CSV for everything.

Recommended columns:

```csv
type,gender,profession,race,environment,variant,mood,seed
```

Not every column is needed for every type.

### Character rows

Use:

* `type=character`
* `gender`
* `profession`
* `race`
* `environment`
* optional `variant`
* optional `mood`
* optional `seed`

Example:

```csv
character,female,mage,alfirin,cirdion,sky_children,calm intellect,105
```

### Settlement rows

Use:

* `type=settlement`
* `environment`
* optional `mood`
* optional `seed`

Example:

```csv
settlement,,,,fenmir_highlands,,weathered,201
```

### Encounter rows

Use:

* `type=encounter`
* `environment`
* optional `seed`

Example:

```csv
encounter,,,,gate_ruins,,,301
```

### Cypher rows

Use:

* `type=cypher`
* `environment`
* optional `seed`

Example:

```csv
cypher,,,,almadir,,,401
```

### Inn rows

Use:

* `type=inn`
* `environment`
* optional `mood`
* optional `seed`

Example:

```csv
inn,,,,fenmir_free_cities,,rowdy and dangerous,602
```

## How generation works

### Characters

A character row pulls from:

* `10_races.yaml`
* `11_professions.yaml`
* `12_environments.yaml`
* `24_names.yaml`
* `01_styles.yaml`
* `00_setting.yaml`

### Settlements

A settlement row pulls from:

* `12_environments.yaml`
* `20_settlements.yaml`
* `24_names.yaml`
* `01_styles.yaml`
* `00_setting.yaml`

### Encounters

An encounter row pulls from:

* `12_environments.yaml`
* `21_encounters.yaml`
* `01_styles.yaml`

### Cyphers

A cypher row pulls from:

* `22_cyphers.yaml`
* `24_names.yaml`
* `01_styles.yaml`

### Inns

An inn row pulls from:

* `12_environments.yaml`
* `24_names.yaml`
* `01_styles.yaml`

## How to add a new race

To add a new race:

1. Open `config/10_races.yaml`
2. Add a new entry under `races:`
3. Define at minimum:

   * `name`
   * `group`
   * `character_base`
   * `core_truths`
   * `themes`
   * `tone`
   * `avoid`
   * `visual_defaults`
4. Add `variants` if the race has subcultures
5. Open `config/24_names.yaml`
6. Add personal naming support for the new race under `names.personal_names`

If you want the race to appear in CSV character rows, that is enough.

If the race also needs special home regions, then add those in `12_environments.yaml`.

## How to add a new race variant

To add a variant such as a subculture:

1. Open `config/10_races.yaml`
2. Find the race
3. Add a new entry under `variants:`
4. Define at minimum:

   * `label`
   * `appearance`
   * optional `clothing`
   * optional `tone`
5. Open `config/24_names.yaml`
6. Add variant-specific names if needed under `by_variant`

Then use that variant in CSV through the `variant` column.

## How to add a new profession

1. Open `config/11_professions.yaml`
2. Add a new entry under `professions:`
3. Define at minimum:

   * `prompt_type`
   * `role`
   * `appearance`
   * `clothing`
   * `weapon_options`
   * `gear_options`
   * `pose_options`
   * `lighting`

Once saved, the profession can be used in character CSV rows.

## How to add a new environment

To add a new environment properly, you usually need to update more than one file.

### Minimum required

1. Open `config/12_environments.yaml`
2. Add a new entry under `environments:`
3. Define at minimum:

   * `name`
   * `type`
   * `culture`
   * `description`
   * `visual_traits`
   * `mood`

That is enough for:

* characters
* inns

### If you also want settlements there

Add the same environment key to:

* `config/20_settlements.yaml`

### If you also want encounters there

Add the same environment key to:

* `config/21_encounters.yaml`

### If you also want cyphers there

Add the same environment key to:

* `config/22_cyphers.yaml`

### If you want generated place names there

Add the same environment key to:

* `config/24_names.yaml` under `settlement_names`
* optionally under `inn_names`
* optionally under `artifact_names`

## How to add a new settlement generator table

1. Open `config/20_settlements.yaml`
2. Add a block matching an existing environment key
3. Define:

   * `settlement_types`
   * `visual_features`
   * `landmarks`
   * `economies`
   * `tensions`
   * `atmospheres`

If the environment key does not exist in `12_environments.yaml`, generation will fail.

## How to add a new encounter table

1. Open `config/21_encounters.yaml`
2. Add a block matching an existing environment key
3. Define:

   * `first_impressions`
   * `subjects`
   * `truths`
   * `complications`
   * `hooks`

## How to add a new cypher table

1. Open `config/22_cyphers.yaml`
2. Add a block matching an existing environment key
3. Define:

   * `forms`
   * `appearances`
   * `effects`
   * `limits`
   * `quirks`

Optional but recommended:

* add artifact naming support in `24_names.yaml`

## How to add new names

### Character names

Edit:

* `config/24_names.yaml` → `names.personal_names`

### Settlement names

Edit:

* `config/24_names.yaml` → `names.settlement_names`

### Artifact or cypher names

Edit:

* `config/24_names.yaml` → `names.artifact_names`

### Ship names

Edit:

* `config/24_names.yaml` → `names.ship_names`

### Clan names

Edit:

* `config/24_names.yaml` → `names.clan_names`

### Inn names

Edit:

* `config/24_names.yaml` → `names.inn_names`

## Name template rules

Most generated names use:

* `prefixes`
* `suffixes`
* `adjectives`
* `nouns`
* `templates`

Example:

```yaml
fenmir_highlands:
  prefixes:
    - Rowan
    - Cairn
  suffixes:
    - hearth
    - stead
  templates:
    - "{prefix}{suffix}"
    - "{prefix}{suffix} Stead"
```

## Running the generator

Install dependency:

```bash
pip install pyyaml
```

Run:

```bash
python3 generate_content.py --config-dir config --csv content.csv --output-dir generated
```

With a global seed:

```bash
python3 generate_content.py --config-dir config --csv content.csv --output-dir generated --seed legends
```

## Output

The script writes:

* one `.txt` file per CSV row into `generated/`
* one combined `generated/all_output.txt`

## Common failure causes

### Unknown race

The race key in CSV is missing from `10_races.yaml`.

### Unknown variant

The variant key in CSV is not defined under that race in `10_races.yaml`.

### Unknown profession

The profession key in CSV is missing from `11_professions.yaml`.

### Unknown environment

The environment key in CSV is missing from `12_environments.yaml`.

### Settlement generation fails

The environment exists in `12_environments.yaml` but is missing from `20_settlements.yaml`.

### Encounter generation fails

The environment exists in `12_environments.yaml` but is missing from `21_encounters.yaml`.

### Cypher generation fails

The environment exists in `12_environments.yaml` but is missing from `22_cyphers.yaml`.

### Names are missing or too generic

The relevant entry is missing from `24_names.yaml`.

## Recommended workflow when adding new content

### New race

Update:

* `10_races.yaml`
* `24_names.yaml`

### New profession

Update:

* `11_professions.yaml`

### New environment

Update:

* `12_environments.yaml`
* `20_settlements.yaml` if settlements needed
* `21_encounters.yaml` if encounters needed
* `22_cyphers.yaml` if cyphers needed
* `24_names.yaml` for settlement, inn, or artifact naming

### New settlement flavor only

Update:

* `20_settlements.yaml`

### New encounter flavor only

Update:

* `21_encounters.yaml`

### New cypher flavor only

Update:

* `22_cyphers.yaml`
* optionally `24_names.yaml`

### New inn naming style

Update:

* `24_names.yaml`

## Suggested future files

You may later want to add:

* `23_artifacts.yaml` for persistent relics
* `25_ships.yaml` if ships become mechanically important
* `26_factions.yaml` for procedural faction content

## Sanity check before using new keys

Before adding a new CSV row, check:

* is the race key valid?
* is the variant valid for that race?
* is the profession key valid?
* is the environment key valid?
* if using settlement/encounter/cypher, is that environment also in the matching generator YAML?

## Example CSV

```csv
type,gender,profession,race,environment,variant,mood,seed
character,male,rogue,lilim,fenmir_free_cities,,dangerous charm,101
character,female,mage,alfirin,cirdion,sky_children,calm intellect,105
settlement,,,,fenmir_highlands,,weathered,201
encounter,,,,gate_ruins,,,301
cypher,,,,almadir,,,401
inn,,,,fenmir_free_cities,,rowdy and dangerous,602
```
