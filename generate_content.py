#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import random
import re
from pathlib import Path
from typing import Any

import yaml


def load_yaml_file(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a top-level mapping.")
    return data


def load_config_dir(config_dir: Path) -> dict[str, Any]:
    merged: dict[str, Any] = {}

    for path in sorted(config_dir.glob("*.yaml")):
        data = load_yaml_file(path)
        for key, value in data.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key].update(value)
            elif key in merged:
                raise ValueError(f"Duplicate top-level config key '{key}' in {path}")
            else:
                merged[key] = value

    return merged


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, str]] = []
        for row in reader:
            cleaned = {
                str(k).strip(): (str(v).strip() if v is not None else "")
                for k, v in row.items()
            }
            rows.append(cleaned)
        return rows


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def ensure_period(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    if text[-1] not in ".!?":
        text += "."
    return text


def join_nonempty(parts: list[str], sep: str = ", ") -> str:
    return sep.join(clean_text(p) for p in parts if p and clean_text(p))


def safe_filename(text: str) -> str:
    chars: list[str] = []
    for ch in text.lower():
        if ch.isalnum() or ch in {"-", "_"}:
            chars.append(ch)
        elif ch in {" ", "/"}:
            chars.append("_")
    result = "".join(chars).strip("_")
    return result or "output"


def deterministic_rng(row: dict[str, str], global_seed: str | None = None) -> random.Random:
    explicit_seed = row.get("seed", "").strip()
    if explicit_seed:
        seed_source = explicit_seed
    elif global_seed:
        seed_source = global_seed + "|" + repr(sorted(row.items()))
    else:
        seed_source = repr(sorted(row.items()))

    digest = hashlib.sha256(seed_source.encode("utf-8")).hexdigest()
    seed_int = int(digest[:16], 16)
    return random.Random(seed_int)


def choose_one(value: Any, rng: random.Random) -> str:
    if isinstance(value, list):
        cleaned = [clean_text(str(v)) for v in value if clean_text(str(v))]
        return rng.choice(cleaned) if cleaned else ""
    if value is None:
        return ""
    return clean_text(str(value))


def get_required(mapping: dict[str, Any], key: str, where: str) -> Any:
    if key not in mapping:
        raise KeyError(f"Missing required key '{key}' in {where}")
    return mapping[key]


def get_gender_label(config: dict[str, Any], gender: str) -> str:
    return str(config.get("gender_terms", {}).get(gender.lower(), gender.lower())).strip()


def build_setting_header(config: dict[str, Any]) -> str:
    setting = config.get("setting", {})
    if not setting:
        return ""

    parts: list[str] = []
    name = setting.get("name", "")
    summary = setting.get("summary", "")
    tone_style = setting.get("tone_style", "")

    if name or summary:
        parts.append(ensure_period(f"{name}: {summary}".strip(": ")))
    if tone_style:
        parts.append(ensure_period(f"Tone and style: {tone_style}"))

    truths = setting.get("core_world_truths", [])
    if truths:
        parts.append("Core world truths: " + " ".join(clean_text(str(t)) for t in truths))

    themes = setting.get("cultural_themes", [])
    if themes:
        parts.append("Cultural themes: " + ", ".join(clean_text(str(t)) for t in themes) + ".")

    return " ".join(parts)


def build_race_flavor(race_cfg: dict[str, Any], variant_cfg: dict[str, Any] | None) -> str:
    parts: list[str] = []

    core_truths = race_cfg.get("core_truths", [])
    themes = race_cfg.get("themes", [])
    tone = race_cfg.get("tone", [])
    avoid = race_cfg.get("avoid", [])
    visual_defaults = race_cfg.get("visual_defaults", {})

    if core_truths:
        parts.append("Core truths: " + "; ".join(clean_text(str(x)) for x in core_truths) + ".")
    if themes:
        parts.append("Themes: " + ", ".join(clean_text(str(x)) for x in themes) + ".")
    if tone:
        parts.append("Tone: " + ", ".join(clean_text(str(x)) for x in tone) + ".")

    visual_bits: list[str] = []
    if isinstance(visual_defaults, dict):
        if visual_defaults.get("scale"):
            visual_bits.append(f"scale {clean_text(str(visual_defaults['scale']))}")
        if visual_defaults.get("skin_palette"):
            visual_bits.append(f"skin palette {clean_text(str(visual_defaults['skin_palette']))}")
        sig = visual_defaults.get("signature_features", [])
        if isinstance(sig, list) and sig:
            visual_bits.append("signature features " + ", ".join(clean_text(str(x)) for x in sig))
        elif isinstance(sig, str) and sig.strip():
            visual_bits.append("signature features " + clean_text(sig))

    if visual_bits:
        parts.append("Visual cues: " + "; ".join(visual_bits) + ".")

    if variant_cfg:
        variant_tone = variant_cfg.get("tone", "")
        if variant_tone:
            parts.append("Variant tone: " + clean_text(str(variant_tone)) + ".")

    if avoid:
        parts.append("Avoid: " + ", ".join(clean_text(str(x)) for x in avoid) + ".")

    return " ".join(parts)


def resolve_race_and_variant(config: dict[str, Any], race_key: str, variant_key: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    races = get_required(config, "races", "config")
    race_cfg = get_required(races, race_key, "races")

    variant_cfg = None
    if variant_key:
        variants = race_cfg.get("variants", {})
        if variant_key not in variants:
            raise KeyError(f"Unknown variant '{variant_key}' for race '{race_key}'")
        variant_cfg = variants[variant_key]

    return race_cfg, variant_cfg


def resolve_environment(config: dict[str, Any], env_key: str) -> dict[str, Any]:
    environments = get_required(config, "environments", "config")
    return get_required(environments, env_key, "environments")


def resolve_style_text(config: dict[str, Any], style_key: str | None = None) -> str:
    styles = get_required(config, "styles", "config")
    defaults = config.get("setting", {}).get("generation_defaults", {})
    actual_style_key = style_key or defaults.get("style_block", "legends_style_art")
    style_cfg = get_required(styles, actual_style_key, "styles")
    return clean_text(str(style_cfg.get("prompt_text", "")))


def pick_name_part(value: Any, rng: random.Random) -> str:
    if isinstance(value, list):
        cleaned = [clean_text(str(v)) for v in value if clean_text(str(v))]
        return rng.choice(cleaned) if cleaned else ""
    return clean_text(str(value)) if value else ""


def render_template(template: str, choices: dict[str, str]) -> str:
    result = template
    for key, value in choices.items():
        result = result.replace("{" + key + "}", value)
    return clean_text(result)


def generate_personal_name(config: dict[str, Any], race_key: str, variant_key: str, rng: random.Random) -> str:
    names_cfg = get_required(config, "names", "config")
    personal = get_required(names_cfg, "personal_names", "names.personal_names")
    race_names = get_required(personal, race_key, f"names.personal_names.{race_key}")

    first_pool = race_names.get("first", [])
    surname_pool = race_names.get("surnames", [])
    title_pool: list[str] = []
    clan_pool: list[str] = []

    by_variant = race_names.get("by_variant", {})
    variant_names = by_variant.get(variant_key, {}) if variant_key else {}

    if variant_names:
        if variant_names.get("first"):
            first_pool = variant_names["first"]
        if variant_names.get("surnames"):
            surname_pool = variant_names["surnames"]
        if variant_names.get("titles"):
            title_pool = variant_names["titles"]
        if variant_names.get("clan_names"):
            clan_pool = variant_names["clan_names"]

    first = pick_name_part(first_pool, rng)
    surname = pick_name_part(surname_pool, rng)
    title = pick_name_part(title_pool, rng)
    clan = pick_name_part(clan_pool, rng)

    # Weighted assembly by available parts
    if title and rng.random() < 0.55:
        return clean_text(f"{first} {title}")
    if clan and rng.random() < 0.45:
        return clean_text(f"{first} of the {clan}")
    if surname:
        return clean_text(f"{first} {surname}")
    return first


def generate_templated_name(section: dict[str, Any], rng: random.Random) -> str:
    fixed = section.get("fixed", [])
    if fixed and rng.random() < 0.25:
        return pick_name_part(fixed, rng)

    templates = section.get("templates", ["{prefix}{suffix}"])
    template = pick_name_part(templates, rng)

    choices = {
        "prefix": pick_name_part(section.get("prefixes", []), rng),
        "suffix": pick_name_part(section.get("suffixes", []), rng),
        "noun": pick_name_part(section.get("nouns", []), rng),
        "noun2": pick_name_part(section.get("nouns", []), rng),
        "adjective": pick_name_part(section.get("adjectives", []), rng),
    }

    # ensure noun2 differs if possible
    if choices["noun2"] == choices["noun"]:
        nouns = section.get("nouns", [])
        if isinstance(nouns, list):
            alt = [clean_text(str(n)) for n in nouns if clean_text(str(n)) and clean_text(str(n)) != choices["noun"]]
            if alt:
                choices["noun2"] = rng.choice(alt)

    return render_template(template, choices)


def generate_settlement_name(config: dict[str, Any], environment_key: str, rng: random.Random) -> str:
    names_cfg = get_required(config, "names", "config")
    settlements = get_required(names_cfg, "settlement_names", "names.settlement_names")
    section = settlements.get(environment_key)
    if not section:
        # Fallback
        for fallback in ("fenmir_lowlands", "cirdion"):
            if fallback in settlements:
                return generate_templated_name(settlements[fallback], rng)
        return "Unnamed Settlement"
    return generate_templated_name(section, rng)


def generate_artifact_name(config: dict[str, Any], environment_key: str, rng: random.Random) -> str:
    names_cfg = get_required(config, "names", "config")
    artifacts = get_required(names_cfg, "artifact_names", "names.artifact_names")
    section = artifacts.get(environment_key, artifacts.get("general"))
    if not section:
        return "Unnamed Relic"
    return generate_templated_name(section, rng)


def generate_inn_name(config: dict[str, Any], environment_key: str, rng: random.Random) -> str:
    names_cfg = get_required(config, "names", "config")
    inns = get_required(names_cfg, "inn_names", "names.inn_names")
    section = inns.get(environment_key, inns.get("general"))
    if not section:
        return "The Nameless Inn"
    return generate_templated_name(section, rng)


def generate_character_prompt(row: dict[str, str], config: dict[str, Any], rng: random.Random) -> str:
    gender = row.get("gender", "").lower()
    race_key = row.get("race", "").lower()
    variant_key = row.get("variant", "").lower()
    profession_key = row.get("profession", "").lower()
    environment_key = row.get("environment", "").lower()
    mood = row.get("mood", "").strip()

    if not all([gender, race_key, profession_key, environment_key]):
        raise ValueError("character rows require gender, race, profession, and environment")

    race_cfg, variant_cfg = resolve_race_and_variant(config, race_key, variant_key)
    profession_cfg = get_required(get_required(config, "professions", "config"), profession_key, "professions")
    environment_cfg = resolve_environment(config, environment_key)

    char_name = generate_personal_name(config, race_key, variant_key, rng)
    gender_label = get_gender_label(config, gender)
    role = clean_text(str(profession_cfg.get("role", profession_key)))
    base = clean_text(str(race_cfg.get("character_base", race_cfg.get("name", race_key)))).lower()

    variant_label = clean_text(str(variant_cfg.get("label", ""))) if variant_cfg else ""
    character_line = f"{char_name}, {gender_label} {base} {role}"
    if variant_label:
        character_line += f", {variant_label}"

    race_visual = race_cfg.get("visual_defaults", {})
    appearance_parts = [
        join_nonempty([str(x) for x in race_visual.get("signature_features", [])]) if isinstance(race_visual.get("signature_features"), list) else clean_text(str(race_visual.get("signature_features", ""))),
        join_nonempty([str(x) for x in variant_cfg.get("appearance", [])]) if variant_cfg and isinstance(variant_cfg.get("appearance"), list) else (clean_text(str(variant_cfg.get("appearance", ""))) if variant_cfg else ""),
        clean_text(str(profession_cfg.get("appearance", ""))),
    ]
    appearance = join_nonempty(appearance_parts)

    clothing_parts = [
        clean_text(str(race_visual.get("clothing", ""))),
        clean_text(str(variant_cfg.get("clothing", ""))) if variant_cfg else "",
        clean_text(str(profession_cfg.get("clothing", ""))),
    ]
    clothing = join_nonempty(clothing_parts)

    weapon = choose_one(profession_cfg.get("weapon_options", []), rng)
    gear = choose_one(profession_cfg.get("gear_options", []), rng)
    pose = choose_one(profession_cfg.get("pose_options", []), rng)
    lighting = choose_one(profession_cfg.get("lighting", []), rng)

    if mood:
        appearance = join_nonempty([appearance, f"mood of {mood}"])
        pose = join_nonempty([pose, f"mood of {mood}"])

    prompt_type = clean_text(str(profession_cfg.get("prompt_type", "default_npc")))
    layout = ""
    if prompt_type == "character_sheet":
        layout = "clean full-body presentation with readable equipment and minimal background clutter"

    sections: list[str] = []
    sections.append("Dark fantasy character prompt.")
    setting_header = build_setting_header(config)
    if setting_header:
        sections.extend(["", "Setting:", setting_header])
    sections.extend([
        "",
        "Character:",
        ensure_period(character_line),
        "",
        "Appearance:",
        ensure_period(appearance),
        "",
        "Clothing:",
        ensure_period(clothing),
        "",
        "Weapons / Props:",
        ensure_period(join_nonempty([weapon, gear])),
        "",
        "Pose:",
        ensure_period(pose),
        "",
        "Environment:",
        ensure_period(clean_text(str(environment_cfg.get("description", "")))),
        "",
        "Lighting:",
        ensure_period(lighting),
    ])

    if layout:
        sections.extend(["", "Layout:", ensure_period(layout)])

    race_flavor = build_race_flavor(race_cfg, variant_cfg)
    if race_flavor:
        sections.extend(["", "Race Flavor:", race_flavor])

    style_text = resolve_style_text(config)
    if style_text:
        sections.extend(["", "STYLE:", ensure_period(style_text)])

    return "\n".join(sections).strip() + "\n"


def generate_settlement_prompt(row: dict[str, str], config: dict[str, Any], rng: random.Random) -> str:
    environment_key = row.get("environment", "").lower()
    mood = row.get("mood", "").strip()

    if not environment_key:
        raise ValueError("settlement rows require environment")

    environment_cfg = resolve_environment(config, environment_key)
    settlements = get_required(config, "settlements", "config")
    settlement_cfg = get_required(settlements, environment_key, "settlements")

    settlement_name = generate_settlement_name(config, environment_key, rng)
    inn_name = generate_inn_name(config, environment_key, rng)

    settlement_type = choose_one(settlement_cfg.get("settlement_types", []), rng)
    visual = choose_one(settlement_cfg.get("visual_features", []), rng)
    landmark = choose_one(settlement_cfg.get("landmarks", []), rng)
    economy = choose_one(settlement_cfg.get("economies", []), rng)
    tension = choose_one(settlement_cfg.get("tensions", []), rng)
    atmosphere = choose_one(settlement_cfg.get("atmospheres", []), rng)

    if mood:
        atmosphere = join_nonempty([atmosphere, mood], sep=", ")

    sections = [
        "Dark fantasy settlement prompt.",
    ]

    setting_header = build_setting_header(config)
    if setting_header:
        sections.extend(["", "Setting:", setting_header])

    sections.extend([
        "",
        "Settlement Name:",
        ensure_period(settlement_name),
        "",
        "Settlement Type:",
        ensure_period(settlement_type),
        "",
        "Environment:",
        ensure_period(clean_text(str(environment_cfg.get("description", "")))),
        "",
        "Visual Feature:",
        ensure_period(visual),
        "",
        "Landmark:",
        ensure_period(landmark),
        "",
        "Economy / Survival Basis:",
        ensure_period(economy),
        "",
        "Current Tension:",
        ensure_period(tension),
        "",
        "Atmosphere:",
        ensure_period(atmosphere),
        "",
        "Local Inn or Tavern:",
        ensure_period(inn_name),
        "",
        "STYLE:",
        ensure_period(resolve_style_text(config, "legends_settlement_art")),
    ])

    return "\n".join(sections).strip() + "\n"


def generate_encounter(row: dict[str, str], config: dict[str, Any], rng: random.Random) -> str:
    environment_key = row.get("environment", "").lower()
    if not environment_key:
        raise ValueError("encounter rows require environment")

    environment_cfg = resolve_environment(config, environment_key)
    encounters = get_required(config, "encounters", "config")
    encounter_cfg = get_required(encounters, environment_key, "encounters")

    first_impression = choose_one(encounter_cfg.get("first_impressions", []), rng)
    subject = choose_one(encounter_cfg.get("subjects", []), rng)
    truth = choose_one(encounter_cfg.get("truths", []), rng)
    complication = choose_one(encounter_cfg.get("complications", []), rng)
    hook = choose_one(encounter_cfg.get("hooks", []), rng)

    sections = [
        "Encounter seed.",
        "",
        "Environment:",
        ensure_period(clean_text(str(environment_cfg.get("description", "")))),
        "",
        "What the party first notices:",
        ensure_period(first_impression),
        "",
        "Who or what is involved:",
        ensure_period(subject),
        "",
        "What is actually happening:",
        ensure_period(truth),
        "",
        "Complication:",
        ensure_period(complication),
        "",
        "GM Hook:",
        ensure_period(hook),
        "",
        "STYLE:",
        ensure_period(resolve_style_text(config, "legends_encounter_art")),
    ]

    return "\n".join(sections).strip() + "\n"


def random_cypher_level(rng: random.Random) -> int:
    return rng.randint(1, 6) + 2


def generate_cypher(row: dict[str, str], config: dict[str, Any], rng: random.Random) -> str:
    environment_key = row.get("environment", "").lower()
    if not environment_key:
        raise ValueError("cypher rows require environment")

    cyphers = get_required(config, "cyphers", "config")
    cypher_cfg = get_required(cyphers, environment_key, "cyphers")

    cypher_name = generate_artifact_name(config, environment_key, rng)
    form = choose_one(cypher_cfg.get("forms", []), rng)
    appearance = choose_one(cypher_cfg.get("appearances", []), rng)
    effect = choose_one(cypher_cfg.get("effects", []), rng)
    limit = choose_one(cypher_cfg.get("limits", []), rng)
    quirk = choose_one(cypher_cfg.get("quirks", []), rng)
    level = random_cypher_level(rng)

    sections = [
        "Cypher.",
        "",
        "Name:",
        ensure_period(cypher_name),
        "",
        "Level:",
        str(level),
        "",
        "Manifestation:",
        ensure_period(form),
        "",
        "Appearance:",
        ensure_period(appearance),
        "",
        "Effect:",
        ensure_period(effect),
        "",
        "Limitation / Depletion:",
        ensure_period(limit),
        "",
        "Quirk:",
        ensure_period(quirk),
        "",
        "STYLE:",
        ensure_period(resolve_style_text(config, "legends_cypher_art")),
    ]

    return "\n".join(sections).strip() + "\n"


def generate_inn(row: dict[str, str], config: dict[str, Any], rng: random.Random) -> str:
    environment_key = row.get("environment", "").lower()
    mood = row.get("mood", "").strip()

    if not environment_key:
        raise ValueError("inn rows require environment")

    environment_cfg = resolve_environment(config, environment_key)
    inn_name = generate_inn_name(config, environment_key, rng)

    traits = [
        "crowded common room",
        "weathered beams and smoke-dark rafters",
        "private back room for contracts or secrets",
        "hearthfire and strong local drink",
        "dockside noise and salt-stained shutters",
        "suspicious regulars and tired travelers",
        "unexpected quality hidden behind a rough exterior",
        "old local trophies, banners, or carved charms",
    ]
    tensions = [
        "a deal is being negotiated too quietly",
        "someone important is expected before dawn",
        "a regular has gone missing and no one agrees why",
        "rival patrons are pretending not to recognize each other",
        "the innkeeper knows more than is safe",
        "a locked room upstairs should not be occupied",
    ]

    trait = choose_one(traits, rng)
    tension = choose_one(tensions, rng)

    atmosphere = mood if mood else choose_one(
        ["warm but wary", "loud and dangerous", "smoky secrecy", "travel-stained familiarity"],
        rng,
    )

    sections = [
        "Inn or tavern prompt.",
        "",
        "Name:",
        ensure_period(inn_name),
        "",
        "Environment:",
        ensure_period(clean_text(str(environment_cfg.get("description", "")))),
        "",
        "Defining Trait:",
        ensure_period(trait),
        "",
        "Current Tension:",
        ensure_period(tension),
        "",
        "Atmosphere:",
        ensure_period(atmosphere),
        "",
        "STYLE:",
        ensure_period(resolve_style_text(config, "legends_settlement_art")),
    ]

    return "\n".join(sections).strip() + "\n"


def generate_from_row(row: dict[str, str], config: dict[str, Any], global_seed: str | None) -> tuple[str, str]:
    content_type = row.get("type", "character").strip().lower()
    rng = deterministic_rng(row, global_seed)

    if content_type == "character":
        text = generate_character_prompt(row, config, rng)
    elif content_type == "settlement":
        text = generate_settlement_prompt(row, config, rng)
    elif content_type == "encounter":
        text = generate_encounter(row, config, rng)
    elif content_type == "cypher":
        text = generate_cypher(row, config, rng)
    elif content_type == "inn":
        text = generate_inn(row, config, rng)
    else:
        raise ValueError(f"Unknown type '{content_type}'")

    name_parts = [
        row.get("type", "character"),
        row.get("profession", ""),
        row.get("race", ""),
        row.get("environment", ""),
        row.get("variant", ""),
        row.get("mood", ""),
    ]
    filename = "_".join(safe_filename(part) for part in name_parts if part.strip())
    return filename, text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Lands of Legends content from split YAML config.")
    parser.add_argument("--config-dir", default="config", help="Directory containing YAML config files")
    parser.add_argument("--csv", default="content.csv", help="Input CSV file")
    parser.add_argument("--output-dir", default="generated", help="Output directory")
    parser.add_argument("--seed", default=None, help="Optional global seed string")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config_dir = Path(args.config_dir)
    csv_path = Path(args.csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    config = load_config_dir(config_dir)
    rows = load_csv(csv_path)

    generated: list[tuple[str, str]] = []
    errors: list[str] = []

    for idx, row in enumerate(rows, start=1):
        try:
            name, text = generate_from_row(row, config, args.seed)
            base_name = f"{idx:03d}_{name}"
            out_path = output_dir / f"{base_name}.txt"
            out_path.write_text(text, encoding="utf-8")
            generated.append((base_name, text))
        except Exception as exc:
            errors.append(f"Row {idx}: {exc}")

    combined_path = output_dir / "all_output.txt"
    with combined_path.open("w", encoding="utf-8") as f:
        for name, text in generated:
            f.write("=" * 80 + "\n")
            f.write(name + "\n")
            f.write("=" * 80 + "\n")
            f.write(text + "\n")

        if errors:
            f.write("=" * 80 + "\n")
            f.write("ERRORS\n")
            f.write("=" * 80 + "\n")
            for err in errors:
                f.write(err + "\n")

    print(f"Generated {len(generated)} file(s) in {output_dir.resolve()}")
    print(f"Combined output: {combined_path.resolve()}")
    if errors:
        print(f"{len(errors)} error(s) encountered:")
        for err in errors:
            print(f"  - {err}")


if __name__ == "__main__":
    main()
