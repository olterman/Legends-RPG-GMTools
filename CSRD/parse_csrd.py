from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path
from typing import Any

from docx import Document
import yaml


BASE_DIR = Path(__file__).resolve().parent
DOCX_PATH = BASE_DIR / "Cypher-System-Reference-Document-2025-08-22.docx"
OUT_DIR = BASE_DIR / "compendium"
SETTINGS_OVERRIDES_PATH = BASE_DIR / "settings_overrides.yaml"


CREATURE_FIELD_ORDER = [
    "Motive",
    "Environment",
    "Health",
    "Damage Inflicted",
    "Armor",
    "Movement",
    "Modifications",
    "Combat",
    "Interaction",
    "Use",
    "Loot",
    "GM intrusion",
    "GM intrusions",
]

CYPHER_FIELD_ORDER = [
    "Level",
    "Form",
    "Effect",
    "Depletion",
]

CATEGORY_HEADINGS = {
    "ALIEN CYPHERS",
    "BODY HORROR CYPHERS",
    "CLASSIC MONSTER CYPHERS",
    "DARK MAGIC AND OCCULT CYPHERS",
    "FANTASY CYPHERS",
    "HORROR CYPHERS",
}

CATEGORY_SETTING_TAGS = {
    "ALIEN CYPHERS": ["science_fiction"],
    "BODY HORROR CYPHERS": ["horror"],
    "CLASSIC MONSTER CYPHERS": ["fantasy", "horror"],
    "DARK MAGIC AND OCCULT CYPHERS": ["fantasy", "horror"],
    "FANTASY CYPHERS": ["fantasy"],
    "HORROR CYPHERS": ["horror"],
}

GLOBAL_CSRD_SETTINGS = ["csrd_core"]

SETTING_KEYWORDS = {
    "fantasy": [
        "dragon", "demon", "angel", "faerie", "elf", "dwarf", "orc", "goblin",
        "wizard", "sorcer", "necromancer", "paladin", "lich", "undead", "wyrm",
        "troll", "minotaur", "satyr", "sphinx", "wyvern", "manticore",
    ],
    "science_fiction": [
        "alien", "android", "robot", "cyber", "nanite", "nanotech", "starship",
        "space", "posthuman", "synthetic", "machine", "drone", "interstellar",
        "galactic", "quantum",
    ],
    "horror": [
        "horror", "ghost", "wraith", "zombie", "vampire", "ghoul", "nightmare",
        "eldritch", "abomination", "curse", "cursed", "haunt", "dread", "terror",
    ],
}


SOURCE_LABEL = "Cypher System Reference Document 2025-08-22"
TYPE_HEADERS = ["WARRIOR", "ADEPT", "EXPLORER", "SPEAKER"]
TIER_WORD_TO_NUMBER = {
    "FIRST": 1,
    "SECOND": 2,
    "THIRD": 3,
    "FOURTH": 4,
    "FIFTH": 5,
    "SIXTH": 6,
}

SKILL_LEVEL_KEYS = ("inability", "practiced", "trained", "expert")


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def read_docx_paragraphs(path: Path) -> list[str]:
    doc = Document(path)
    lines: list[str] = []
    for p in doc.paragraphs:
        text = clean(p.text)
        if text:
            lines.append(text)
    return lines


def is_creature_heading(line: str) -> bool:
    # Example: CYCLOPS 7 (21)
    return bool(re.match(r"^[A-Z][A-Z' \-]+?\s+\d+\s+\(\d+\)$", line.strip()))


def parse_creature_heading(line: str) -> tuple[str, int, int]:
    m = re.match(r"^([A-Z][A-Z' \-]+?)\s+(\d+)\s+\((\d+)\)$", line.strip())
    if not m:
        raise ValueError(f"Not a creature heading: {line}")
    name = clean(m.group(1)).title()
    level = int(m.group(2))
    target_number = int(m.group(3))
    return name, level, target_number


def is_possible_cypher_name(line: str) -> bool:
    # Heuristic: all caps, not a category heading, not a creature heading, not a labeled field
    if ":" in line:
        return False
    if line in CATEGORY_HEADINGS:
        return False
    if is_creature_heading(line):
        return False
    if not re.match(r"^[A-Z0-9][A-Z0-9' \-]+$", line):
        return False
    words = line.split()
    return 1 <= len(words) <= 6


def parse_field_line(line: str) -> tuple[str, str] | None:
    if ":" not in line:
        return None
    left, right = line.split(":", 1)
    key = clean(left)
    value = clean(right)
    return key, value


def save_json(folder: Path, title: str, data: dict[str, Any], *, dedupe_slug: bool = False) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    filename_slug = data.get("slug") or slugify(title)
    normalized_slug = slugify(str(filename_slug))
    if len(normalized_slug) > 110:
        digest = hashlib.sha1(normalized_slug.encode("utf-8")).hexdigest()[:10]
        normalized_slug = f"{normalized_slug[:99]}_{digest}"
    slug = normalized_slug
    path = folder / f"{slug}.json"
    if dedupe_slug:
        suffix = 2
        while path.exists():
            slug = f"{normalized_slug}_{suffix}"
            path = folder / f"{slug}.json"
            suffix += 1
    payload = dict(data)
    payload["slug"] = slug
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_json_files(folder: Path) -> None:
    if not folder.exists():
        return
    for path in folder.glob("*.json"):
        path.unlink()


def parse_creatures(lines: list[str]) -> list[dict[str, Any]]:
    creatures: list[dict[str, Any]] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        if not is_creature_heading(line):
            i += 1
            continue

        title, level, target_number = parse_creature_heading(line)
        i += 1

        description_parts: list[str] = []
        fields: dict[str, str] = {}

        # collect description until first labeled field
        while i < len(lines):
            maybe = parse_field_line(lines[i])
            if maybe and maybe[0] in CREATURE_FIELD_ORDER:
                break
            if is_creature_heading(lines[i]):
                break
            description_parts.append(lines[i])
            i += 1

        # parse labeled sections
        current_key: str | None = None
        current_val: list[str] = []

        def flush_current():
            nonlocal current_key, current_val
            if current_key:
                text = clean(" ".join(current_val))
                if text:
                    fields[current_key] = text
            current_key = None
            current_val = []

        while i < len(lines):
            if is_creature_heading(lines[i]):
                break

            parsed = parse_field_line(lines[i])
            if parsed and parsed[0] in CREATURE_FIELD_ORDER:
                flush_current()
                current_key = parsed[0]
                current_val = [parsed[1]] if parsed[1] else []
            else:
                if current_key:
                    current_val.append(lines[i])
                else:
                    # stray content before next heading
                    description_parts.append(lines[i])
            i += 1

        flush_current()

        creature = {
            "type": "creature",
            "source": "Cypher System Reference Document 2025-08-22",
            "title": title,
            "slug": slugify(title),
            "level": level,
            "target_number": target_number,
            "description": clean(" ".join(description_parts)),
            "motive": fields.get("Motive"),
            "environment": fields.get("Environment"),
            "health": fields.get("Health"),
            "damage_inflicted": fields.get("Damage Inflicted"),
            "armor": fields.get("Armor"),
            "movement": fields.get("Movement"),
            "modifications": fields.get("Modifications"),
            "combat": fields.get("Combat"),
            "interaction": fields.get("Interaction"),
            "use": fields.get("Use"),
            "loot": fields.get("Loot"),
            "gm_intrusion": fields.get("GM intrusion") or fields.get("GM intrusions"),
        }
        creature_settings = infer_settings_from_text(
            " ".join([
                title,
                fields.get("Environment") or "",
                fields.get("Motive") or "",
                fields.get("Combat") or "",
                clean(" ".join(description_parts)),
            ])
        )
        creature["settings"] = creature_settings
        creature["setting"] = creature_settings[0]
        creatures.append(creature)

    return creatures


def infer_settings_from_text(text: str) -> list[str]:
    normalized = clean(text).lower()
    settings = list(GLOBAL_CSRD_SETTINGS)
    for setting, keywords in SETTING_KEYWORDS.items():
        if any(re.search(rf"\b{re.escape(keyword)}\w*\b", normalized) for keyword in keywords):
            settings.append(setting)
    deduped: list[str] = []
    for token in settings:
        if token not in deduped:
            deduped.append(token)
    return deduped


def parse_cyphers(lines: list[str]) -> list[dict[str, Any]]:
    cyphers: list[dict[str, Any]] = []
    i = 0
    current_category: str | None = None

    while i < len(lines):
        line = lines[i]

        if line in CATEGORY_HEADINGS:
            current_category = line.title()
            i += 1
            continue

        if not is_possible_cypher_name(line):
            i += 1
            continue

        # Cypher names are usually followed by Level/Form/Effect
        if i + 1 >= len(lines):
            i += 1
            continue

        next_field = parse_field_line(lines[i + 1])
        if not next_field or next_field[0] != "Level":
            i += 1
            continue

        title = clean(line.title())
        i += 1

        fields: dict[str, str] = {}
        current_key: str | None = None
        current_val: list[str] = []

        def flush_current():
            nonlocal current_key, current_val
            if current_key:
                text = clean(" ".join(current_val))
                if text:
                    fields[current_key] = text
            current_key = None
            current_val = []

        while i < len(lines):
            if lines[i] in CATEGORY_HEADINGS:
                break
            if is_creature_heading(lines[i]):
                break
            if is_possible_cypher_name(lines[i]):
                # another likely cypher entry starts
                maybe_next = lines[i + 1] if i + 1 < len(lines) else ""
                parsed_next = parse_field_line(maybe_next)
                if parsed_next and parsed_next[0] == "Level":
                    break

            parsed = parse_field_line(lines[i])
            if parsed and parsed[0] in CYPHER_FIELD_ORDER:
                flush_current()
                current_key = parsed[0]
                current_val = [parsed[1]] if parsed[1] else []
            else:
                if current_key:
                    current_val.append(lines[i])
            i += 1

        flush_current()

        if "Level" in fields and "Effect" in fields:
            settings = list(GLOBAL_CSRD_SETTINGS)
            for token in CATEGORY_SETTING_TAGS.get(str(current_category or "").upper(), []):
                if token not in settings:
                    settings.append(token)
            cypher = {
                "type": "cypher",
                "source": "Cypher System Reference Document 2025-08-22",
                "title": title,
                "slug": slugify(title),
                "category": current_category,
                "level": fields.get("Level"),
                "form": fields.get("Form"),
                "effect": fields.get("Effect"),
                "depletion": fields.get("Depletion"),
                "settings": settings,
                "setting": settings[0],
            }
            cyphers.append(cypher)

    return cyphers


def cypher_is_artifact(cypher: dict[str, Any]) -> bool:
    depletion = clean(str(cypher.get("depletion") or ""))
    if not depletion:
        return False
    normalized = depletion.lower()
    if normalized in {"-", "—", "n/a", "na", "none"}:
        return False
    return bool(re.search(r"\d", normalized))


def split_cyphers_and_artifacts(cyphers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed_cyphers: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    for item in cyphers:
        if cypher_is_artifact(item):
            artifact = dict(item)
            artifact["type"] = "artifact"
            artifacts.append(artifact)
        else:
            parsed_cyphers.append(item)
    return parsed_cyphers, artifacts


def attach_global_csrd_settings(items: list[dict[str, Any]]) -> None:
    for item in items:
        settings = [str(x).strip() for x in (item.get("settings") or []) if str(x).strip()]
        for token in GLOBAL_CSRD_SETTINGS:
            if token not in settings:
                settings.append(token)
        if settings:
            item["settings"] = settings
            item["setting"] = settings[0]


def load_settings_overrides(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _override_bucket_name(item_type: str) -> str:
    if item_type.endswith("y"):
        return f"{item_type[:-1]}ies"
    if item_type.endswith("s"):
        return item_type
    return f"{item_type}s"


def _normalize_settings_list(raw: Any) -> list[str]:
    values: list[str] = []
    if isinstance(raw, str):
        raw_values = [raw]
    elif isinstance(raw, (list, tuple, set)):
        raw_values = list(raw)
    else:
        raw_values = []
    for value in raw_values:
        token = slugify(str(value))
        if token and token not in values:
            values.append(token)
    return values


def apply_settings_overrides(
    items: list[dict[str, Any]],
    *,
    item_type: str,
    overrides: dict[str, Any],
) -> None:
    singular_bucket = overrides.get(item_type, {})
    plural_bucket = overrides.get(_override_bucket_name(item_type), {})
    candidates = [singular_bucket, plural_bucket]

    for item in items:
        slug = str(item.get("slug") or "").strip()
        if not slug:
            continue

        item_override: dict[str, Any] = {}
        for bucket in candidates:
            if isinstance(bucket, dict) and isinstance(bucket.get(slug), dict):
                item_override = bucket.get(slug) or {}
                break
        if not item_override:
            continue

        settings = _normalize_settings_list(item.get("settings"))
        if not settings:
            settings = _normalize_settings_list(item.get("setting"))
        if not settings:
            settings = list(GLOBAL_CSRD_SETTINGS)

        replace = item_override.get("replace")
        if replace is not None:
            settings = _normalize_settings_list(replace)

        for token in _normalize_settings_list(item_override.get("add")):
            if token not in settings:
                settings.append(token)

        remove_set = set(_normalize_settings_list(item_override.get("remove")))
        settings = [token for token in settings if token not in remove_set]

        if not settings:
            settings = list(GLOBAL_CSRD_SETTINGS)

        preferred = _normalize_settings_list(item_override.get("setting"))
        if preferred:
            chosen = preferred[0]
            settings = [chosen] + [token for token in settings if token != chosen]

        item["settings"] = settings
        item["setting"] = settings[0]


def is_all_caps_heading(line: str) -> bool:
    if not line:
        return False
    has_alpha = any(ch.isalpha() for ch in line)
    if not has_alpha:
        return False
    return line == line.upper()


def find_line_index(lines: list[str], target: str, start: int = 0) -> int:
    target_norm = target.strip().lower()
    for i in range(start, len(lines)):
        if lines[i].strip().lower() == target_norm:
            return i
    return -1


def parse_descriptors(lines: list[str]) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []

    start = find_line_index(lines, "DESCRIPTORS")
    if start < 0:
        return descriptors

    end = find_line_index(lines, "CUSTOMIZING DESCRIPTORS", start + 1)
    if end < 0:
        return descriptors

    descriptor_names: list[str] = []
    i = start + 1
    while i < end:
        line = lines[i]
        if is_all_caps_heading(line):
            break
        if line and not line.startswith("•"):
            descriptor_names.append(line)
        i += 1

    descriptor_name_set = {name.upper() for name in descriptor_names}

    current_name: str | None = None
    current_text: list[str] = []

    def flush_current() -> None:
        nonlocal current_name, current_text
        if not current_name:
            return

        descriptor = {
            "type": "descriptor",
            "source": SOURCE_LABEL,
            "title": current_name.title(),
            "slug": slugify(current_name),
            "summary": current_text[0] if current_text else "",
            "text": clean(" ".join(current_text)),
            "details": current_text,
        }
        descriptors.append(descriptor)
        current_name = None
        current_text = []

    for i in range(start + 1, end):
        line = lines[i]
        upper_line = line.upper()
        if upper_line in descriptor_name_set:
            flush_current()
            current_name = line
            continue

        if current_name:
            current_text.append(line)

    flush_current()
    return descriptors


def parse_character_types(lines: list[str]) -> list[dict[str, Any]]:
    types: list[dict[str, Any]] = []

    start = find_line_index(lines, "Type")
    if start < 0:
        return types

    end = find_line_index(lines, "Flavor", start + 1)
    if end < 0:
        return types

    header_points: list[tuple[str, int]] = []
    for i in range(start + 1, end):
        upper = lines[i].upper()
        if upper in TYPE_HEADERS:
            header_points.append((upper, i))

    if not header_points:
        return types

    for idx, (header, section_start) in enumerate(header_points):
        section_end = header_points[idx + 1][1] if idx + 1 < len(header_points) else end

        i = section_start + 1
        aliases: dict[str, list[str]] = {}
        while i < section_end and ":" in lines[i]:
            key, value = lines[i].split(":", 1)
            key = clean(key)
            value = clean(value)
            if not key or not value:
                break
            aliases[key] = [clean(x) for x in value.split(",") if clean(x)]
            i += 1

        summary = ""
        for j in range(i, section_end):
            if lines[j].startswith("You"):
                summary = lines[j]
                break

        role_lines: dict[str, str] = {}
        for line in lines[i:section_end]:
            if ":" not in line:
                continue
            left, right = line.split(":", 1)
            left = clean(left)
            if left in {"Individual Role", "Group Role", "Societal Role"} or left.startswith("Advanced"):
                role_lines[left] = clean(right)

        player_intrusions: list[str] = []
        intrusions_start = find_line_index(lines, f"{header} PLAYER INTRUSIONS", section_start)
        stat_pool_heading = find_line_index(lines, f"{header} STAT POOLS", section_start)
        if intrusions_start >= 0 and stat_pool_heading > intrusions_start:
            for line in lines[intrusions_start + 1:stat_pool_heading]:
                if ":" in line and not line.startswith("When playing"):
                    player_intrusions.append(line)

        stat_pools = ""
        if stat_pool_heading >= 0 and stat_pool_heading + 1 < section_end:
            stat_pools = lines[stat_pool_heading + 1]

        tier_abilities: dict[str, list[str]] = {}
        tier_header_re = re.compile(
            rf"^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)-TIER {header}$",
            flags=re.IGNORECASE,
        )

        j = section_start
        while j < section_end:
            m = tier_header_re.match(lines[j])
            if not m:
                j += 1
                continue

            tier_word = m.group(1).upper()
            tier_key = f"tier_{TIER_WORD_TO_NUMBER[tier_word]}"
            abilities: list[str] = []
            j += 1

            while j < section_end:
                current = lines[j]
                if tier_header_re.match(current):
                    break
                if current.upper() in TYPE_HEADERS:
                    break
                if current.startswith("Boxed text:") or current.startswith(f"{header} EXAMPLE"):
                    break
                if ":" not in current and not current.startswith("("):
                    # Ability names in this section are unlabelled lines.
                    if current.startswith("Choose "):
                        j += 1
                        continue
                    if not current.endswith(f"{header.lower()} abilities:"):
                        abilities.append(current)
                j += 1

            tier_abilities[tier_key] = abilities

        body = lines[i:section_end]
        types.append({
            "type": "character_type",
            "source": SOURCE_LABEL,
            "title": header.title(),
            "slug": slugify(header),
            "summary": summary,
            "aliases": aliases,
            "roles": role_lines,
            "player_intrusions": player_intrusions,
            "stat_pools": stat_pools,
            "tier_abilities": tier_abilities,
            "text": clean(" ".join(body)),
            "details": body,
        })

    return types


def parse_flavors(lines: list[str]) -> list[dict[str, Any]]:
    flavors: list[dict[str, Any]] = []

    start = find_line_index(lines, "Flavor")
    if start < 0:
        return flavors

    end = find_line_index(lines, "Descriptor", start + 1)
    if end < 0:
        return flavors

    flavor_points: list[int] = []
    for i in range(start + 1, end):
        if lines[i].upper().endswith(" FLAVOR"):
            flavor_points.append(i)

    if not flavor_points:
        return flavors

    tier_re = re.compile(r"^(FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH)-TIER .* ABILITIES$", flags=re.IGNORECASE)

    for idx, section_start in enumerate(flavor_points):
        section_end = flavor_points[idx + 1] if idx + 1 < len(flavor_points) else end
        heading = lines[section_start]
        title = clean(heading.title())
        body = lines[section_start + 1:section_end]

        summary = ""
        for line in body:
            if line and not tier_re.match(line):
                summary = line
                break

        tier_abilities: dict[str, list[str]] = {}
        j = section_start + 1
        current_tier_key: str | None = None

        while j < section_end:
            line = lines[j]
            match = tier_re.match(line)
            if match:
                tier_word = match.group(1).upper()
                current_tier_key = f"tier_{TIER_WORD_TO_NUMBER[tier_word]}"
                tier_abilities[current_tier_key] = []
                j += 1
                continue

            if current_tier_key:
                if line and ":" not in line:
                    tier_abilities[current_tier_key].append(line)
            j += 1

        flavors.append({
            "type": "flavor",
            "source": SOURCE_LABEL,
            "title": title,
            "slug": slugify(title.replace(" Flavor", "")),
            "summary": summary,
            "tier_abilities": tier_abilities,
            "text": clean(" ".join(body)),
            "details": body,
        })

    return flavors


def parse_foci(lines: list[str]) -> list[dict[str, Any]]:
    foci: list[dict[str, Any]] = []

    start = find_line_index(lines, "FOCI")
    if start < 0:
        return foci

    end = find_line_index(lines, "CREATING NEW FOCI", start + 1)
    if end < 0:
        return foci

    def is_focus_start(idx: int) -> bool:
        if idx + 1 >= end:
            return False
        line = lines[idx]

        if not line:
            return False
        if is_all_caps_heading(line):
            return False
        if line.startswith("Tier "):
            return False
        if line.startswith("GM Intrusions:"):
            return False
        if line.startswith("Type Swap Option:"):
            return False
        if line.startswith("Focus Connection"):
            return False
        if ":" in line:
            return False
        if not is_title_like_phrase(line):
            return False
        # Focus entries are followed quickly by tier lines.
        scan_end = min(end, idx + 8)
        for j in range(idx + 1, scan_end):
            if lines[j].startswith("Tier 1:"):
                return True
            if is_all_caps_heading(lines[j]):
                break
        return False

    i = start + 1
    while i < end:
        if not is_focus_start(i):
            i += 1
            continue

        title = lines[i]
        i += 1
        summary = ""
        tier_lines: list[str] = []
        gm_intrusions = ""
        body: list[str] = []

        if i < end:
            summary = lines[i]
            body.append(lines[i])
            i += 1

        while i < end:
            if is_focus_start(i):
                break

            line = lines[i]
            if line.startswith("Tier "):
                tier_lines.append(line)
            elif line.startswith("GM Intrusions:"):
                gm_intrusions = clean(line.split(":", 1)[1])
            else:
                body.append(line)
            i += 1

        foci.append({
            "type": "focus",
            "source": SOURCE_LABEL,
            "title": title,
            "slug": slugify(title),
            "summary": summary,
            "tiers": tier_lines,
            "gm_intrusions": gm_intrusions,
            "text": clean(" ".join(body)),
            "details": body,
        })

    return foci


ABILITY_SECTION_STOP_HEADINGS = {
    "FOCUS",
    "DESCRIPTORS",
}


ABILITY_NON_ENTRY_PREFIXES = (
    "Low Tier:",
    "Mid Tier:",
    "High Tier:",
    "Tier ",
)


ABILITY_NON_ENTRY_NAMES = {
    "Cost",
    "Action",
    "Enabler",
}


_LOWERCASE_CONNECTORS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "if", "in", "into", "is",
    "of", "on", "or", "out", "the", "to", "with", "without",
}


def is_title_like_phrase(text: str) -> bool:
    words = re.split(r"\s+", text.strip())
    if not words:
        return False
    if len(words) > 9:
        return False

    for i, word in enumerate(words):
        token = re.sub(r"^[^A-Za-z0-9'\"]+|[^A-Za-z0-9'\"]+$", "", word)
        if not token:
            continue
        lower = token.lower()
        if i > 0 and lower in _LOWERCASE_CONNECTORS:
            continue
        if token[0].isdigit():
            continue
        if not token[0].isupper():
            return False
    return True


def parse_ability_name_and_cost(raw_name: str) -> tuple[str, str | None]:
    raw_name = clean(raw_name)
    m = re.match(r"^(.*?)\s*\(([^()]+)\)$", raw_name)
    if not m:
        return raw_name, None
    return clean(m.group(1)), clean(m.group(2))


def is_ability_entry_line(line: str) -> bool:
    if ":" not in line:
        return False
    if line.startswith(ABILITY_NON_ENTRY_PREFIXES):
        return False

    left, _ = line.split(":", 1)
    left = clean(left)
    if not left:
        return False
    if left in ABILITY_NON_ENTRY_NAMES:
        return False
    if len(left) > 90:
        return False
    if any(ch in left for ch in ".!?"):
        return False
    if left.startswith("Abilities—"):
        return False
    if left.startswith("GM Intrusion"):
        return False
    if left.startswith("Initial Link"):
        return False
    if left.startswith("Type Swap Option"):
        return False
    if left.startswith("CATEGORY"):
        return False
    if left.isupper():
        return False
    if left[0].isdigit():
        return False
    if not (left[0].isalpha() or left[0] in {'"', "'"}):
        return False
    if not is_title_like_phrase(left):
        return False
    return True


def parse_abilities(lines: list[str]) -> list[dict[str, Any]]:
    abilities: list[dict[str, Any]] = []

    start = find_line_index(lines, "Abilities")
    if start < 0:
        return abilities

    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].strip().upper() in ABILITY_SECTION_STOP_HEADINGS:
            end = idx
            break

    current_letter = ""
    first_letter_heading = -1
    for idx in range(start + 1, end):
        if lines[idx].startswith("Abilities—"):
            first_letter_heading = idx
            break
    if first_letter_heading < 0:
        return abilities

    i = first_letter_heading
    while i < end:
        line = lines[i]

        if line.startswith("Abilities—"):
            current_letter = line.split("—", 1)[1].strip()
            i += 1
            continue

        if not is_ability_entry_line(line):
            i += 1
            continue

        raw_name, first_text = line.split(":", 1)
        raw_name = clean(raw_name)
        name, cost = parse_ability_name_and_cost(raw_name)
        detail_lines = [clean(first_text)]
        i += 1

        while i < end:
            nxt = lines[i]
            if nxt.startswith("Abilities—"):
                break
            if is_ability_entry_line(nxt):
                break
            if is_all_caps_heading(nxt):
                break
            detail_lines.append(nxt)
            i += 1

        abilities.append({
            "type": "ability",
            "source": SOURCE_LABEL,
            "title": name,
            "slug": slugify(name),
            "cost": cost,
            "alpha_section": current_letter,
            "effect": clean(" ".join(detail_lines)),
            "details": detail_lines,
        })

    return abilities


def normalize_skill_name(text: str) -> str:
    value = clean(text)
    # Drop trailing explanatory clauses early.
    value = re.split(r"\b(?:if|when|because|provided that|unless)\b", value, maxsplit=1, flags=re.IGNORECASE)[0]
    value = re.sub(r"^[\"'“”‘’\(\)\[\]\-–—\s]+", "", value)
    value = re.sub(r"[\"'“”‘’\(\)\[\]\-–—\s]+$", "", value)
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" .,:;")
    if not value:
        return ""

    # Trim common lead-ins.
    value = re.sub(
        r"^(?:the|your|all|any)\s+(?:task|tasks|action|actions)\s+(?:that\s+involves?|that\s+involve|involving|with|for|related\s+to)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"^(?:task|tasks|action|actions)\s+(?:that\s+involves?|that\s+involve|involving|with|for|related\s+to)\s+",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"^(?:the|your|all|any)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\b(?:you|your|youre|you're)\b", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s+", " ", value).strip(" .,:;")
    # Canonicalize common Cypher skill phrasings.
    low = value.lower()
    if "initiative actions" in low or low == "initiative":
        return "initiative"
    m = re.search(r"\b(might|speed|intellect)\s+defense\b", low)
    if m:
        return f"{m.group(1)} defense"
    m = re.search(r"\b(physical|mental)\s+defense\b", low)
    if m:
        return f"{m.group(1)} defense"
    m = re.search(r"\b(perception|stealth|initiative|deception|persuasion|intimidation)\b", low)
    if m and len(low.split()) > 8:
        return m.group(1)

    value = re.sub(r"\s*\([^)]*$", "", value)  # unmatched opening parenthesis
    value = value.strip(" .,:;")
    return value


def title_case_skill(value: str) -> str:
    words = value.split()
    out: list[str] = []
    for i, word in enumerate(words):
        lower = word.lower()
        if i > 0 and lower in _LOWERCASE_CONNECTORS:
            out.append(lower)
        else:
            out.append(word[:1].upper() + word[1:])
    return " ".join(out)


def extract_skills(
    descriptors: list[dict[str, Any]],
    character_types: list[dict[str, Any]],
    flavors: list[dict[str, Any]],
    foci: list[dict[str, Any]],
    abilities: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    skill_map: dict[str, dict[str, Any]] = {}

    pattern_specs: list[tuple[str, re.Pattern[str]]] = [
        ("inability", re.compile(r"\binability in ([^.;]+)", flags=re.IGNORECASE)),
        ("inability", re.compile(r"\binability with ([^.;]+)", flags=re.IGNORECASE)),
        ("inability", re.compile(r"\btasks? (?:that involve|involving) ([^.;]+?) (?:is|are) hindered", flags=re.IGNORECASE)),
        ("inability", re.compile(r"\b([^.;]+?) attacks are hindered", flags=re.IGNORECASE)),
        ("practiced", re.compile(r"\bpracticed with ([^.;]+)", flags=re.IGNORECASE)),
        ("practiced", re.compile(r"\bpracticed in ([^.;]+)", flags=re.IGNORECASE)),
        ("trained", re.compile(r"\btrained in ([^.;]+)", flags=re.IGNORECASE)),
        ("trained", re.compile(r"\btrained with ([^.;]+)", flags=re.IGNORECASE)),
        ("trained", re.compile(r"\btrained without ([^.;]+)", flags=re.IGNORECASE)),
        ("expert", re.compile(r"\bspecialized in ([^.;]+)", flags=re.IGNORECASE)),
        ("expert", re.compile(r"\bspecialized with ([^.;]+)", flags=re.IGNORECASE)),
        ("expert", re.compile(r"\ban expert in ([^.;]+)", flags=re.IGNORECASE)),
        ("expert", re.compile(r"\bexpert in ([^.;]+)", flags=re.IGNORECASE)),
    ]

    def add_skill(raw_name: str, level: str, source_ref: str, context_line: str) -> None:
        normalized = normalize_skill_name(raw_name)
        if not normalized:
            return
        if len(normalized) < 3:
            return
        if len(normalized) > 120:
            return
        if len(normalized.split()) > 16:
            return
        if (
            len(normalized.split()) > 6
            and re.search(r"\b(?:you|your|were|would|could|should|can|can't|character|pcs)\b", normalized, flags=re.IGNORECASE)
        ):
            return
        if re.search(r"\b(ability|cypher|tier|costs?\s+\d+|points?)\b", normalized, flags=re.IGNORECASE) and len(normalized) > 45:
            return
        if normalized.lower() in {"tasks", "attacks", "actions"}:
            return

        key = normalized.lower()
        if key not in skill_map:
            skill_map[key] = {
                "type": "skill",
                "source": SOURCE_LABEL,
                "title": title_case_skill(normalized),
                "slug": slugify(normalized),
                "progression": {k: [] for k in SKILL_LEVEL_KEYS},
            }

        bucket = skill_map[key]["progression"][level]
        evidence = {
            "from": source_ref,
            "line": clean(context_line),
        }
        if evidence not in bucket:
            bucket.append(evidence)

    def scan_texts(texts: list[str], source_ref: str) -> None:
        for line in texts:
            if not line:
                continue
            for level, pattern in pattern_specs:
                for match in pattern.finditer(line):
                    captured = clean(match.group(1))
                    if captured:
                        add_skill(captured, level, source_ref, line)

    for item in descriptors:
        scan_texts(item.get("details", []), f"descriptor:{item.get('slug')}")

    for item in character_types:
        scan_texts(item.get("details", []), f"character_type:{item.get('slug')}")

    for item in flavors:
        scan_texts(item.get("details", []), f"flavor:{item.get('slug')}")

    for item in foci:
        focus_lines = []
        focus_lines.extend(item.get("details", []))
        focus_lines.extend(item.get("tiers", []))
        if item.get("gm_intrusions"):
            focus_lines.append(item["gm_intrusions"])
        scan_texts(focus_lines, f"focus:{item.get('slug')}")

    for item in abilities:
        ability_lines = []
        ability_lines.extend(item.get("details", []))
        if item.get("effect"):
            ability_lines.append(item["effect"])
        scan_texts(ability_lines, f"ability:{item.get('slug')}")

    skills = list(skill_map.values())
    for skill in skills:
        progression = skill["progression"]
        skill["levels"] = [k for k in SKILL_LEVEL_KEYS if progression.get(k)]
        skill["summary"] = ", ".join(skill["levels"]) if skill["levels"] else ""

    skills.sort(key=lambda x: x.get("title", ""))
    return skills


def main() -> None:
    if not DOCX_PATH.exists():
        raise FileNotFoundError(f"Missing DOCX: {DOCX_PATH}")

    lines = read_docx_paragraphs(DOCX_PATH)
    overrides = load_settings_overrides(SETTINGS_OVERRIDES_PATH)

    parsed_cyphers = parse_cyphers(lines)
    cyphers, artifacts = split_cyphers_and_artifacts(parsed_cyphers)
    creatures = parse_creatures(lines)
    character_types = parse_character_types(lines)
    flavors = parse_flavors(lines)
    descriptors = parse_descriptors(lines)
    foci = parse_foci(lines)
    abilities = parse_abilities(lines)
    skills = extract_skills(descriptors, character_types, flavors, foci, abilities)

    attach_global_csrd_settings(cyphers)
    attach_global_csrd_settings(artifacts)
    apply_settings_overrides(cyphers, item_type="cypher", overrides=overrides)
    apply_settings_overrides(artifacts, item_type="artifact", overrides=overrides)
    apply_settings_overrides(creatures, item_type="creature", overrides=overrides)

    cypher_dir = OUT_DIR / "cyphers"
    artifact_dir = OUT_DIR / "artifacts"
    creature_dir = OUT_DIR / "creatures"
    type_dir = OUT_DIR / "types"
    flavor_dir = OUT_DIR / "flavors"
    descriptor_dir = OUT_DIR / "descriptors"
    focus_dir = OUT_DIR / "foci"
    ability_dir = OUT_DIR / "abilities"
    skill_dir = OUT_DIR / "skills"

    for folder in [cypher_dir, artifact_dir, creature_dir, type_dir, flavor_dir, descriptor_dir, focus_dir, ability_dir, skill_dir]:
        clear_json_files(folder)

    for item in cyphers:
        save_json(cypher_dir, item["title"], item, dedupe_slug=True)

    for item in artifacts:
        save_json(artifact_dir, item["title"], item, dedupe_slug=True)

    for item in creatures:
        save_json(creature_dir, item["title"], item)

    for item in character_types:
        save_json(type_dir, item["title"], item)

    for item in flavors:
        save_json(flavor_dir, item["title"], item)

    for item in descriptors:
        save_json(descriptor_dir, item["title"], item)

    for item in foci:
        save_json(focus_dir, item["title"], item)

    for item in abilities:
        save_json(ability_dir, item["title"], item)

    for item in skills:
        save_json(skill_dir, item["title"], item)

    index = {
        "cyphers": len(cyphers),
        "artifacts": len(artifacts),
        "creatures": len(creatures),
        "types": len(character_types),
        "flavors": len(flavors),
        "descriptors": len(descriptors),
        "foci": len(foci),
        "abilities": len(abilities),
        "skills": len(skills),
    }
    (OUT_DIR / "index.json").write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Parsed {len(cyphers)} cyphers")
    print(f"Parsed {len(artifacts)} artifacts")
    print(f"Parsed {len(creatures)} creatures")
    print(f"Parsed {len(character_types)} types")
    print(f"Parsed {len(flavors)} flavors")
    print(f"Parsed {len(descriptors)} descriptors")
    print(f"Parsed {len(foci)} foci")
    print(f"Parsed {len(abilities)} abilities")
    print(f"Parsed {len(skills)} skills")
    print(f"Output written to: {OUT_DIR}")


if __name__ == "__main__":
    main()
