from __future__ import annotations

import random
from typing import Any


def clean_text(text: str) -> str:
    return " ".join(text.strip().split())


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

    if choices["noun2"] == choices["noun"]:
        nouns = section.get("nouns", [])
        if isinstance(nouns, list):
            alt = [
                clean_text(str(n))
                for n in nouns
                if clean_text(str(n)) and clean_text(str(n)) != choices["noun"]
            ]
            if alt:
                choices["noun2"] = rng.choice(alt)

    return render_template(template, choices)


def generate_personal_name(config: dict[str, Any], race_key: str, variant_key: str, rng: random.Random) -> str:
    names_cfg = config["names"]["personal_names"]
    race_names = names_cfg[race_key]

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

    if title and rng.random() < 0.55:
        return clean_text(f"{first} {title}")
    if clan and rng.random() < 0.45:
        return clean_text(f"{first} of the {clan}")
    if surname:
        return clean_text(f"{first} {surname}")
    return first


def generate_settlement_name(config: dict[str, Any], environment_key: str, rng: random.Random) -> str:
    section = config["names"]["settlement_names"].get(environment_key)
    if not section:
        return "Unnamed Settlement"
    return generate_templated_name(section, rng)


def generate_artifact_name(config: dict[str, Any], environment_key: str, rng: random.Random) -> str:
    artifacts = config["names"]["artifact_names"]
    section = artifacts.get(environment_key, artifacts.get("general"))
    if not section:
        return "Unnamed Relic"
    return generate_templated_name(section, rng)


def generate_inn_name(config: dict[str, Any], environment_key: str, rng: random.Random) -> str:
    inns = config["names"]["inn_names"]
    section = inns.get(environment_key, inns.get("general"))
    if not section:
        return "The Nameless Inn"
    return generate_templated_name(section, rng)