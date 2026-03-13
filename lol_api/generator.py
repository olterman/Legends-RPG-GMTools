from __future__ import annotations

import hashlib
import random
import re
from typing import Any

from .names import (
    generate_artifact_name,
    generate_inn_name,
    generate_personal_name,
    generate_settlement_name,
    generate_templated_name,
)

DEFAULT_ARTIFACT_DEPLETION_TABLE = [
    "depletion: 1 in 1d6",
    "depletion: 1 in 1d10",
    "depletion: 1 in 1d20",
    "depletion: 1 in 1d100",
]


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


def nonempty_sections(**kwargs: str) -> dict[str, str]:
    return {k: v for k, v in kwargs.items() if clean_text(v)}


def title_from_text(text: str, max_words: int = 6) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    words = cleaned.split()
    return " ".join(words[:max_words]).title()


def _snake_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    key = re.sub(r"_+", "_", key).strip("_")
    return key


def _extract_first_int(value: str) -> int | None:
    m = re.search(r"\d+", str(value or ""))
    if not m:
        return None
    try:
        return int(m.group(0))
    except Exception:
        return None


def parse_raw_text_entry(payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    item_type = str(payload.get("type") or "").strip().lower()
    raw_text = str(payload.get("raw_text") or payload.get("text") or "").strip()
    if not raw_text:
        raise ValueError("raw_text is required")

    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        raise ValueError("raw_text is empty")

    explicit_name = clean_text(str(payload.get("name") or ""))
    inferred_name = clean_text(lines[0])
    name = explicit_name or inferred_name or "Unnamed Entry"

    field_aliases = {
        "form": "manifestation",
        "appearance": "appearance",
        "effect": "effect",
        "limitation": "limitation",
        "depletion": "depletion",
        "level": "level",
        "description": "description",
        "gm intrusion": "gm_intrusion",
        "combat": "combat",
        "motive": "motive",
        "use": "use",
        "loot": "loot",
    }
    compact_statline_re = re.compile(r"^\s*(\d+)\s*\(\s*(\d+)\s*\)\s*$")

    parsed_fields: dict[str, str] = {}
    current_key: str | None = None
    after_name = lines[1:] if inferred_name else lines
    for line in after_name:
        s = line.strip()
        if not s:
            current_key = None
            continue
        compact = compact_statline_re.match(s)
        if compact:
            # Common NPC/creature heading form: "6 (18)" == level + target number.
            parsed_fields.setdefault("level", compact.group(1))
            parsed_fields.setdefault("target_number", compact.group(2))
            current_key = None
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9 /'’\-\(\)]{1,40}):\s*(.*)$", s)
        if m:
            raw_key = clean_text(m.group(1))
            key = field_aliases.get(raw_key.lower(), _snake_key(raw_key))
            value = clean_text(m.group(2))
            parsed_fields[key] = value
            current_key = key
            continue
        if current_key:
            merged = join_nonempty([parsed_fields.get(current_key, ""), s], sep=" ")
            parsed_fields[current_key] = merged
        else:
            parsed_fields["description"] = join_nonempty([parsed_fields.get("description", ""), s], sep=" ")

    if item_type in {"", "auto"}:
        if parsed_fields.get("depletion"):
            item_type = "artifact"
        elif parsed_fields.get("effect") or parsed_fields.get("manifestation") or parsed_fields.get("limitation"):
            item_type = "cypher"
        elif parsed_fields.get("combat") or parsed_fields.get("motive") or parsed_fields.get("gm_intrusion"):
            item_type = "npc"
        else:
            item_type = "lore"

    # Reasonable default descriptions for cards/search snippets.
    description = clean_text(
        parsed_fields.get("description")
        or parsed_fields.get("effect")
        or parsed_fields.get("use")
        or ""
    )
    if not description:
        remaining = "\n".join(after_name).strip()
        description = clean_text(remaining[:400]) if remaining else ""

    sections = {}
    if item_type in {"cypher", "artifact"}:
        sections = nonempty_sections(
            name=name,
            level=parsed_fields.get("level", ""),
            manifestation=parsed_fields.get("manifestation", ""),
            appearance=parsed_fields.get("appearance", ""),
            effect=parsed_fields.get("effect", ""),
            limitation=parsed_fields.get("limitation", ""),
            depletion=parsed_fields.get("depletion", ""),
            quirk=parsed_fields.get("quirk", ""),
        )
    else:
        sections = nonempty_sections(**parsed_fields)

    metadata: dict[str, Any] = {
        "origin": "raw_text_parser",
    }
    sourcebook = str(payload.get("sourcebook") or payload.get("book") or "").strip()
    pages = str(payload.get("pages") or payload.get("page") or "").strip()
    if sourcebook:
        metadata["sourcebook"] = sourcebook
        metadata["book"] = sourcebook
    if pages:
        metadata["pages"] = pages
    if payload.get("area") or payload.get("environment"):
        metadata["area"] = str(payload.get("area") or payload.get("environment") or "").strip()
        metadata["environment"] = metadata["area"]
    if payload.get("location"):
        metadata["location"] = str(payload.get("location") or "").strip()
    if parsed_fields.get("level"):
        metadata["level"] = parsed_fields.get("level")
    if item_type == "cypher":
        metadata["item_class"] = "one_shot"
    if item_type == "artifact":
        metadata["item_class"] = "persistent"
        if parsed_fields.get("depletion"):
            metadata["depletion"] = parsed_fields.get("depletion")

    result = {
        "type": item_type,
        "name": name,
        "description": description,
        "sections": sections,
        "text": raw_text,
        "metadata": metadata,
    }

    level_value = parsed_fields.get("level", "")
    if item_type in {"cypher", "artifact"} and level_value:
        numeric_level = _extract_first_int(level_value)
        result["level"] = numeric_level if numeric_level is not None else level_value

    return result


def parse_raw_text_entries(payload: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_text = str(payload.get("raw_text") or payload.get("text") or "").replace("\r\n", "\n")
    if not raw_text.strip():
        raise ValueError("raw_text is required")

    # Split into blocks at lines that look like item starts.
    # We intentionally keep this conservative to avoid treating prose lines as titles.
    lines = raw_text.split("\n")
    starts: list[int] = []
    marker_re = re.compile(r"^\s*(level|form|effect|depletion|limitation|motive|combat|gm intrusion)\s*:", re.I)
    compact_statline_re = re.compile(r"^\s*\d+\s*\(\s*\d+\s*\)\s*$")

    def looks_like_title_line(value: str) -> bool:
        text = str(value or "").strip()
        if not text:
            return False
        if ":" in text:
            return False
        if text.endswith("."):
            return False
        if len(text) > 80:
            return False
        words = re.findall(r"[A-Za-z0-9'’\-]+", text)
        if not words or len(words) > 12:
            return False
        # Accept obvious all-caps headers (BLACK DOG) and normal title-like names.
        alpha_chars = [c for c in text if c.isalpha()]
        upper_ratio = (
            sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
            if alpha_chars else 0.0
        )
        if upper_ratio >= 0.7:
            return True
        titled_words = sum(1 for w in words if w[:1].isupper())
        if titled_words >= max(1, int(len(words) * 0.7)):
            return True
        return False

    # First non-empty line is always a valid start for single-entry text.
    for i, line in enumerate(lines):
        if line.strip():
            starts.append(i)
            break

    for i in range(0, len(lines) - 1):
        title = lines[i].strip()
        nxt = lines[i + 1].strip()
        if not looks_like_title_line(title):
            continue
        if marker_re.match(nxt):
            starts.append(i)
            continue
        # Also support entries that put compact statline right under the title (e.g. "6 (18)")
        # and introduce keyed sections shortly after.
        if compact_statline_re.match(nxt):
            lookahead = "\n".join(lines[i + 2 : i + 10])
            if marker_re.search(lookahead):
                starts.append(i)

    chunks: list[str] = []
    if not starts:
        chunks = [raw_text.strip()]
    else:
        starts = sorted(set(starts))
        for idx, start in enumerate(starts):
            end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
            chunk = "\n".join(lines[start:end]).strip()
            if chunk:
                chunks.append(chunk)

    items: list[dict[str, Any]] = []
    for chunk in chunks:
        entry_payload = dict(payload)
        entry_payload["raw_text"] = chunk
        items.append(parse_raw_text_entry(entry_payload, config))
    return items


def deterministic_rng(payload: dict[str, Any], global_seed: str | None = None) -> random.Random:
    explicit_seed = str(payload.get("seed", "")).strip()

    if explicit_seed:
        seed_source = explicit_seed
    elif global_seed:
        seed_source = global_seed + "|" + repr(sorted(payload.items()))
    else:
        return random.Random()

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


def get_gender_label(config: dict[str, Any], gender: str) -> str:
    return str(config.get("gender_terms", {}).get(gender.lower(), gender.lower())).strip()


def pick_npc_role_config(config: dict[str, Any], profession_key: str) -> dict[str, Any]:
    npc_roles = config.get("npc_roles", {})
    if profession_key not in npc_roles:
        raise KeyError(f"No npc_roles entry for profession '{profession_key}'")
    return npc_roles[profession_key]


def render_stat_lines(lines: list[str], damage: int) -> list[str]:
    rendered = []
    for line in lines:
        rendered.append(clean_text(str(line)).replace("{damage}", str(damage)))
    return rendered


def generate_npc_stat_block(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    profession_key = str(payload.get("profession", "")).lower()
    role_cfg = pick_npc_role_config(config, profession_key)

    min_level, max_level = role_cfg.get("level_range", [2, 4])
    level = rng.randint(int(min_level), int(max_level))
    target_number = level * 3
    health_multiplier = int(role_cfg.get("health_multiplier", 2))
    health = (level * health_multiplier) + rng.randint(0, 2)
    armor = int(role_cfg.get("armor", 0))
    damage = int(role_cfg.get("damage", max(2, level)))
    movement = clean_text(str(role_cfg.get("movement", "short")))

    modifications = render_stat_lines(role_cfg.get("modifications") or [], damage)
    combat = render_stat_lines(role_cfg.get("combat") or [], damage)
    interaction = render_stat_lines(role_cfg.get("interaction") or [], damage)

    loot_pool = role_cfg.get("loot") or []
    loot_count = min(len(loot_pool), 2)
    loot = rng.sample(loot_pool, k=loot_count) if loot_count > 0 else []

    return {
        "level": level,
        "target_number": target_number,
        "health": health,
        "armor": armor,
        "damage": damage,
        "movement": movement,
        "modifications": modifications,
        "combat": combat,
        "interaction": interaction,
        "loot": loot,
    }


def format_npc_stat_block_text(name: str, role: str, stats: dict[str, Any]) -> str:
    lines = [
        f"{name} — {role}",
        f"Level {stats['level']} (target number {stats['target_number']})",
        f"Health: {stats['health']}",
        f"Armor: {stats['armor']}",
        f"Damage: {stats['damage']}",
        f"Movement: {stats['movement']}",
    ]

    if stats.get("modifications"):
        lines.append("Modifications:")
        lines.extend(f"- {line}" for line in stats["modifications"])

    if stats.get("combat"):
        lines.append("Combat:")
        lines.extend(f"- {line}" for line in stats["combat"])

    if stats.get("interaction"):
        lines.append("Interaction:")
        lines.extend(f"- {line}" for line in stats["interaction"])

    if stats.get("loot"):
        lines.append("Loot:")
        lines.extend(f"- {line}" for line in stats["loot"])

    return "\n".join(lines)

def pick_monster_role_config(config: dict[str, Any], role_key: str) -> dict[str, Any]:
    monster_roles = config.get("monster_roles", {})
    if role_key not in monster_roles:
        raise KeyError(f"No monster_roles entry for role '{role_key}'")
    return monster_roles[role_key]


def pick_monster_environment_traits(config: dict[str, Any], environment_key: str) -> dict[str, Any]:
    monster_traits = config.get("monster_traits", {})
    environments = monster_traits.get("areas", {}) or monster_traits.get("environments", {})
    if environment_key not in environments:
        raise KeyError(f"No monster_traits area entry for '{environment_key}'")
    return environments[environment_key]


def pick_monster_family_concept(config: dict[str, Any], family_key: str, rng: random.Random) -> str:
    monster_traits = config.get("monster_traits", {})
    families = monster_traits.get("families", {})
    if family_key not in families:
        raise KeyError(f"No monster_traits family entry for '{family_key}'")
    return choose_one(families[family_key].get("concept", []), rng)


def pick_monster_name(config: dict[str, Any], environment_key: str, family_key: str, rng: random.Random) -> str:
    monster_names = config.get("monster_names", {})
    env_section = (monster_names.get("areas", {}) or monster_names.get("environments", {})).get(environment_key)
    family_section = monster_names.get("families", {}).get(family_key)
    generic_section = monster_names.get("generic")

    if env_section:
        return generate_templated_name(env_section, rng)
    if family_section:
        return generate_templated_name(family_section, rng)
    if generic_section:
        return generate_templated_name(generic_section, rng)
    return "Unnamed Monster"


def generate_monster_stat_block(role_key: str, config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    role_cfg = pick_monster_role_config(config, role_key)

    min_level, max_level = role_cfg.get("level_range", [2, 4])
    level = rng.randint(int(min_level), int(max_level))
    target_number = level * 3
    health_multiplier = int(role_cfg.get("health_multiplier", 3))
    health = (level * health_multiplier) + rng.randint(0, 3)
    armor = int(role_cfg.get("armor", 0))
    damage = int(role_cfg.get("damage", max(2, level)))
    movement = clean_text(str(role_cfg.get("movement", "short")))

    modifications = render_stat_lines(role_cfg.get("modifications", []), damage)
    combat = render_stat_lines(role_cfg.get("combat", []), damage)
    interaction = render_stat_lines(role_cfg.get("interaction", []), damage)

    loot_text = choose_one(role_cfg.get("loot", []), rng)
    loot = [loot_text] if loot_text else []

    return {
        "level": level,
        "target_number": target_number,
        "health": health,
        "armor": armor,
        "damage": damage,
        "movement": movement,
        "modifications": modifications,
        "combat": combat,
        "interaction": interaction,
        "loot": loot,
    }


def format_monster_stat_block_text(name: str, role: str, family: str, stats: dict[str, Any]) -> str:
    lines = [
        f"{name} — {family} {role}",
        f"Level {stats['level']} (target number {stats['target_number']})",
        f"Health: {stats['health']}",
        f"Armor: {stats['armor']}",
        f"Damage: {stats['damage']}",
        f"Movement: {stats['movement']}",
    ]

    if stats.get("modifications"):
        lines.append("Modifications:")
        lines.extend(f"- {line}" for line in stats["modifications"])

    if stats.get("combat"):
        lines.append("Combat:")
        lines.extend(f"- {line}" for line in stats["combat"])

    if stats.get("interaction"):
        lines.append("Interaction:")
        lines.extend(f"- {line}" for line in stats["interaction"])

    if stats.get("loot"):
        lines.append("Loot:")
        lines.extend(f"- {line}" for line in stats["loot"])

    return "\n".join(lines)

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
    race_cfg = config["races"][race_key]
    variant_cfg = None
    if variant_key:
        variants = race_cfg.get("variants", {})
        if variant_key not in variants:
            raise KeyError(f"Unknown variant '{variant_key}' for race '{race_key}'")
        variant_cfg = variants[variant_key]
    return race_cfg, variant_cfg


def resolve_environment(config: dict[str, Any], env_key: str) -> dict[str, Any]:
    areas = config.get("areas", {})
    if env_key in areas:
        return areas[env_key]
    return config["environments"][env_key]


def payload_area_key(payload: dict[str, Any]) -> str:
    return str(payload.get("area", "") or payload.get("environment", "")).lower()


def resolve_style_text(config: dict[str, Any], style_key: str | None = None) -> str:
    defaults = config.get("setting", {}).get("generation_defaults", {})
    actual_style_key = style_key or defaults.get("style_block", "legends_style_art")
    return clean_text(str(config["styles"][actual_style_key].get("prompt_text", "")))


def artifact_depletion_table(config: dict[str, Any]) -> list[str]:
    cypher_system = (config.get("setting", {}) or {}).get("cypher_system", {}) or {}
    configured = cypher_system.get("artifact_depletion_table", [])
    values = [clean_text(str(x)) for x in configured if clean_text(str(x))]
    return values or DEFAULT_ARTIFACT_DEPLETION_TABLE


def generate_character(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    gender = str(payload.get("gender", "")).lower()
    race_key = str(payload.get("race", "")).lower()
    variant_key = str(payload.get("variant", "")).lower()
    profession_key = str(payload.get("profession", "")).lower()
    area_key = payload_area_key(payload)
    mood = str(payload.get("mood", "")).strip()

    if not all([gender, race_key, profession_key, area_key]):
        raise ValueError("character requires gender, race, profession, and area")

    race_cfg, variant_cfg = resolve_race_and_variant(config, race_key, variant_key)
    profession_cfg = config["professions"][profession_key]
    environment_cfg = resolve_environment(config, area_key)

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
        join_nonempty([str(x) for x in race_visual.get("signature_features", [])])
        if isinstance(race_visual.get("signature_features"), list)
        else clean_text(str(race_visual.get("signature_features", ""))),
        join_nonempty([str(x) for x in variant_cfg.get("appearance", [])])
        if variant_cfg and isinstance(variant_cfg.get("appearance"), list)
        else (clean_text(str(variant_cfg.get("appearance", ""))) if variant_cfg else ""),
        clean_text(str(profession_cfg.get("appearance", ""))),
    ]
    appearance = join_nonempty(appearance_parts)

    clothing = join_nonempty([
        clean_text(str(race_visual.get("clothing", ""))),
        clean_text(str(variant_cfg.get("clothing", ""))) if variant_cfg else "",
        clean_text(str(profession_cfg.get("clothing", ""))),
    ])

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

    setting_header = build_setting_header(config)
    race_flavor = build_race_flavor(race_cfg, variant_cfg)
    style_text = resolve_style_text(config)

    sections_dict = nonempty_sections(
        setting=setting_header,
        character=character_line,
        appearance=appearance,
        clothing=clothing,
        weapons_props=join_nonempty([weapon, gear]),
        pose=pose,
        environment=clean_text(str(environment_cfg.get("description", ""))),
        lighting=lighting,
        layout=layout,
        race_flavor=race_flavor,
        style=style_text,
    )

    text_sections: list[str] = ["Dark fantasy character prompt."]
    for label, value in [
        ("Setting", sections_dict.get("setting", "")),
        ("Character", sections_dict.get("character", "")),
        ("Appearance", sections_dict.get("appearance", "")),
        ("Clothing", sections_dict.get("clothing", "")),
        ("Weapons / Props", sections_dict.get("weapons_props", "")),
        ("Pose", sections_dict.get("pose", "")),
        ("Environment", sections_dict.get("environment", "")),
        ("Lighting", sections_dict.get("lighting", "")),
        ("Layout", sections_dict.get("layout", "")),
        ("Race Flavor", sections_dict.get("race_flavor", "")),
        ("STYLE", sections_dict.get("style", "")),
    ]:
        if value:
            text_sections.extend(["", f"{label}:", ensure_period(value)])

    return {
        "type": "character",
        "name": char_name,
        "sections": sections_dict,
        "text": "\n".join(text_sections).strip() + "\n",
        "metadata": {
            "race": race_key,
            "variant": variant_key or None,
            "profession": profession_key,
            "area": area_key,
            "environment": area_key,
        },
    }


def generate_npc(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    character_result = generate_character(payload, config, rng)
    profession_key = str(payload.get("profession", "")).lower()
    role = clean_text(str(config["professions"][profession_key].get("role", profession_key)))

    stat_block = generate_npc_stat_block(payload, config, rng)
    stat_block_text = format_npc_stat_block_text(character_result["name"], role, stat_block)

    return {
        "type": "npc",
        "name": character_result["name"],
        "sections": character_result["sections"],
        "prompt_text": character_result["text"],
        "stat_block": stat_block,
        "stat_block_text": stat_block_text,
        "text": character_result["text"] + "\n---\n\n" + stat_block_text + "\n",
        "metadata": character_result["metadata"],
    }

def generate_monster(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    environment_key = payload_area_key(payload)
    mood = str(payload.get("mood", "")).strip()
    family_key = str(payload.get("family", "")).lower()
    role_key = str(payload.get("role", "")).lower()

    if not environment_key:
        raise ValueError("monster requires area")

    environment_cfg = resolve_environment(config, environment_key)
    env_traits = pick_monster_environment_traits(config, environment_key)

    if not family_key:
        family_key = choose_one(env_traits.get("families", []), rng).lower()
    if not role_key:
        role_key = choose_one(list(config.get("monster_roles", {}).keys()), rng).lower()

    if not family_key:
        raise ValueError("monster could not determine family")
    if not role_key:
        raise ValueError("monster could not determine role")

    concept = pick_monster_family_concept(config, family_key, rng)
    appearance_general = choose_one(
        config.get("monster_traits", {}).get("appearance_traits", {}).get("general", []),
        rng,
    )
    appearance_env = choose_one(env_traits.get("appearance_traits", []), rng)
    behavior_general = choose_one(
        config.get("monster_traits", {}).get("behavior_traits", {}).get("general", []),
        rng,
    )
    behavior_env = choose_one(env_traits.get("behavior_traits", []), rng)
    special_general = choose_one(
        config.get("monster_traits", {}).get("special_traits", {}).get("general", []),
        rng,
    )
    special_env = choose_one(env_traits.get("special_traits", []), rng)

    monster_name = pick_monster_name(config, environment_key, family_key, rng)
    role_display = clean_text(role_key.replace("_", " "))
    family_display = clean_text(family_key.replace("_", " "))

    appearance = join_nonempty([appearance_general, appearance_env])
    behavior = join_nonempty([behavior_general, behavior_env])
    special = join_nonempty([special_general, special_env])

    if mood:
        behavior = join_nonempty([behavior, f"mood of {mood}"])

    style_text = resolve_style_text(config, "legends_encounter_art")
    stat_block = generate_monster_stat_block(role_key, config, rng)
    stat_block_text = format_monster_stat_block_text(monster_name, role_display, family_display, stat_block)

    sections_dict = nonempty_sections(
        name=monster_name,
        concept=concept,
        family=family_display,
        role=role_display,
        environment=clean_text(str(environment_cfg.get("description", ""))),
        appearance=appearance,
        behavior=behavior,
        special=special,
        style=style_text,
    )

    text_sections = ["Monster prompt."]
    for label, key in [
        ("Name", "name"),
        ("Concept", "concept"),
        ("Family", "family"),
        ("Role", "role"),
        ("Environment", "environment"),
        ("Appearance", "appearance"),
        ("Behavior", "behavior"),
        ("Special", "special"),
        ("STYLE", "style"),
    ]:
        if sections_dict.get(key):
            text_sections.extend(["", f"{label}:", ensure_period(sections_dict[key])])

    return {
        "type": "monster",
        "name": monster_name,
        "sections": sections_dict,
        "stat_block": stat_block,
        "stat_block_text": stat_block_text,
        "text": "\n".join(text_sections).strip() + "\n\n---\n\n" + stat_block_text + "\n",
        "metadata": {
            "area": environment_key,
            "environment": environment_key,
            "family": family_key,
            "role": role_key,
        },
    }

def generate_settlement(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    environment_key = payload_area_key(payload)
    mood = str(payload.get("mood", "")).strip()
    if not environment_key:
        raise ValueError("settlement requires area")

    environment_cfg = resolve_environment(config, environment_key)
    settlement_cfg = config["settlements"][environment_key]

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

    setting_header = build_setting_header(config)
    style_text = resolve_style_text(config, "legends_settlement_art")

    sections_dict = nonempty_sections(
        setting=setting_header,
        settlement_name=settlement_name,
        settlement_type=settlement_type,
        environment=clean_text(str(environment_cfg.get("description", ""))),
        visual_feature=visual,
        landmark=landmark,
        economy=economy,
        tension=tension,
        atmosphere=atmosphere,
        inn_name=inn_name,
        style=style_text,
    )

    text_sections = ["Dark fantasy settlement prompt."]
    for label, key in [
        ("Setting", "setting"),
        ("Settlement Name", "settlement_name"),
        ("Settlement Type", "settlement_type"),
        ("Environment", "environment"),
        ("Visual Feature", "visual_feature"),
        ("Landmark", "landmark"),
        ("Economy / Survival Basis", "economy"),
        ("Current Tension", "tension"),
        ("Atmosphere", "atmosphere"),
        ("Local Inn or Tavern", "inn_name"),
        ("STYLE", "style"),
    ]:
        if sections_dict.get(key):
            text_sections.extend(["", f"{label}:", ensure_period(sections_dict[key])])

    return {
        "type": "settlement",
        "name": settlement_name,
        "inn_name": inn_name,
        "sections": sections_dict,
        "text": "\n".join(text_sections).strip() + "\n",
        "metadata": {
            "area": environment_key,
            "environment": environment_key,
            "location": settlement_name,
            "location_type": "settlement",
        },
    }


def generate_encounter(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    environment_key = payload_area_key(payload)
    if not environment_key:
        raise ValueError("encounter requires area")

    environment_cfg = resolve_environment(config, environment_key)
    encounter_cfg = config["encounters"][environment_key]

    first_impression = choose_one(encounter_cfg.get("first_impressions", []), rng)
    subject = choose_one(encounter_cfg.get("subjects", []), rng)
    truth = choose_one(encounter_cfg.get("truths", []), rng)
    complication = choose_one(encounter_cfg.get("complications", []), rng)
    hook = choose_one(encounter_cfg.get("hooks", []), rng)
    title_base = title_from_text(subject) or title_from_text(first_impression)
    environment_title = clean_text(environment_key.replace("_", " ")).title()
    encounter_name = title_base or f"Encounter in {environment_title}"

    sections_dict = nonempty_sections(
        subject=subject,
        environment=clean_text(str(environment_cfg.get("description", ""))),
        first_notice=first_impression,
        hook=hook,
        complication=complication,
        truth=truth,
    )

    text_sections = ["Encounter seed."]
    for label, key in [
        ("Subject", "subject"),
        ("Environment", "environment"),
        ("First Notice", "first_notice"),
        ("Hook", "hook"),
        ("Complication", "complication"),
        ("Truth", "truth"),
    ]:
        if sections_dict.get(key):
            text_sections.extend(["", f"{label}:", ensure_period(sections_dict[key])])

    return {
        "type": "encounter",
        "name": encounter_name,
        "sections": sections_dict,
        "text": "\n".join(text_sections).strip() + "\n",
        "metadata": {
            "area": environment_key,
            "environment": environment_key,
            "location": encounter_name,
            "first_impression": first_impression,
            "subject": subject,
            "truth": truth,
            "complication": complication,
            "hook": hook,
        },
    }


def generate_cypher(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    environment_key = payload_area_key(payload)
    if not environment_key:
        raise ValueError("cypher requires area")

    cypher_cfg = config["cyphers"][environment_key]

    cypher_name = generate_artifact_name(config, environment_key, rng)
    form = choose_one(cypher_cfg.get("forms", []), rng)
    appearance = choose_one(cypher_cfg.get("appearances", []), rng)
    effect = choose_one(cypher_cfg.get("effects", []), rng)
    limits = [clean_text(str(x)) for x in (cypher_cfg.get("limits", []) or []) if clean_text(str(x))]
    one_shot_limits = [x for x in limits if "depletion" not in x.lower()]
    limit = choose_one(one_shot_limits or limits, rng)
    quirk = choose_one(cypher_cfg.get("quirks", []), rng)
    level = rng.randint(1, 6) + 2
    style_text = resolve_style_text(config, "legends_cypher_art")

    sections_dict = nonempty_sections(
        name=cypher_name,
        level=str(level),
        manifestation=form,
        appearance=appearance,
        effect=effect,
        limitation=limit,
        quirk=quirk,
        style=style_text,
    )

    text_sections = ["Cypher."]
    for label, key in [
        ("Name", "name"),
        ("Level", "level"),
        ("Manifestation", "manifestation"),
        ("Appearance", "appearance"),
        ("Effect", "effect"),
        ("Limitation / Depletion", "limitation"),
        ("Quirk", "quirk"),
        ("STYLE", "style"),
    ]:
        if sections_dict.get(key):
            value = sections_dict[key]
            text_sections.extend(["", f"{label}:", value if key == "level" else ensure_period(value)])

    return {
        "type": "cypher",
        "name": cypher_name,
        "level": level,
        "sections": sections_dict,
        "text": "\n".join(text_sections).strip() + "\n",
        "metadata": {
            "area": environment_key,
            "environment": environment_key,
            "level": level,
            "item_class": "one_shot",
        },
    }


def generate_artifact(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    environment_key = payload_area_key(payload)
    if not environment_key:
        raise ValueError("artifact requires area")

    cypher_cfg = config["cyphers"][environment_key]

    artifact_name = generate_artifact_name(config, environment_key, rng)
    form = choose_one(cypher_cfg.get("forms", []), rng)
    appearance = choose_one(cypher_cfg.get("appearances", []), rng)
    effect = choose_one(cypher_cfg.get("effects", []), rng)
    quirk = choose_one(cypher_cfg.get("quirks", []), rng)
    level = rng.randint(1, 6) + 2
    depletion = choose_one(artifact_depletion_table(config), rng)
    style_text = resolve_style_text(config, "legends_cypher_art")

    sections_dict = nonempty_sections(
        name=artifact_name,
        level=str(level),
        manifestation=form,
        appearance=appearance,
        effect=effect,
        depletion=depletion,
        quirk=quirk,
        style=style_text,
    )

    text_sections = ["Artifact."]
    for label, key in [
        ("Name", "name"),
        ("Level", "level"),
        ("Manifestation", "manifestation"),
        ("Appearance", "appearance"),
        ("Effect", "effect"),
        ("Depletion", "depletion"),
        ("Quirk", "quirk"),
        ("STYLE", "style"),
    ]:
        if sections_dict.get(key):
            value = sections_dict[key]
            text_sections.extend(["", f"{label}:", value if key == "level" else ensure_period(value)])

    return {
        "type": "artifact",
        "name": artifact_name,
        "level": level,
        "sections": sections_dict,
        "text": "\n".join(text_sections).strip() + "\n",
        "metadata": {
            "area": environment_key,
            "environment": environment_key,
            "level": level,
            "depletion": depletion,
            "item_class": "persistent",
        },
    }


def generate_inn(payload: dict[str, Any], config: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    environment_key = payload_area_key(payload)
    mood = str(payload.get("mood", "")).strip()
    if not environment_key:
        raise ValueError("inn requires area")

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
    atmosphere = mood if mood else choose_one(
        ["warm but wary", "loud and dangerous", "smoky secrecy", "travel-stained familiarity"],
        rng,
    )

    trait = choose_one(traits, rng)
    tension = choose_one(tensions, rng)
    style_text = resolve_style_text(config, "legends_settlement_art")

    sections_dict = nonempty_sections(
        name=inn_name,
        environment=clean_text(str(environment_cfg.get("description", ""))),
        defining_trait=trait,
        current_tension=tension,
        atmosphere=atmosphere,
        style=style_text,
    )

    text_sections = ["Inn or tavern prompt."]
    for label, key in [
        ("Name", "name"),
        ("Environment", "environment"),
        ("Defining Trait", "defining_trait"),
        ("Current Tension", "current_tension"),
        ("Atmosphere", "atmosphere"),
        ("STYLE", "style"),
    ]:
        if sections_dict.get(key):
            text_sections.extend(["", f"{label}:", ensure_period(sections_dict[key])])

    return {
        "type": "inn",
        "name": inn_name,
        "sections": sections_dict,
        "text": "\n".join(text_sections).strip() + "\n",
        "metadata": {
            "area": environment_key,
            "environment": environment_key,
            "location": inn_name,
            "location_type": "inn",
        },
    }
