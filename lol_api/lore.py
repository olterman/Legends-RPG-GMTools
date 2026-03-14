from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .config_loader import load_config_dir
from .settings import normalize_settings_values

LORE_ENTRY_SCHEMA_VERSION = "1.0"
LOCATION_CATEGORY_TYPES = {
    "city",
    "forest",
    "mountain",
    "lake",
    "inn",
    "settlement",
    "cave",
    "dungeon",
    "landmark",
}
LOCATION_CATEGORY_PRIORITY = [
    "city",
    "settlement",
    "inn",
    "landmark",
    "dungeon",
    "cave",
    "mountain",
    "forest",
    "lake",
]


def _normalize_image_refs(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    refs: list[str] = []
    for value in values:
        text = str(value or "").strip().replace("\\", "/")
        if text.startswith("/images/"):
            text = text[len("/images/"):]
        if text.startswith("images/"):
            text = text[len("images/"):]
        text = text.strip("/")
        if not text:
            continue
        if text not in refs:
            refs.append(text)
    return refs


def _normalized_categories(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for value in values:
        key = str(value or "").strip().lower().replace(" ", "_")
        if key:
            out.append(key)
    return sorted(set(out))


def _pick_location_type(categories: list[str]) -> str:
    for key in LOCATION_CATEGORY_PRIORITY:
        if key in categories:
            return key
    return ""


def _is_location_entry(categories: list[str]) -> bool:
    return any(category in LOCATION_CATEGORY_TYPES for category in categories)


def _normalize_lore_item(item: dict[str, Any], default_settings: list[str] | None = None) -> dict[str, Any]:
    normalized = dict(item)
    categories = _normalized_categories(normalized.get("categories"))
    if categories:
        normalized["categories"] = categories

    if normalized.get("environment") and not normalized.get("area"):
        normalized["area"] = normalized.get("environment")
    if normalized.get("area") and not normalized.get("environment"):
        normalized["environment"] = normalized.get("area")

    if _is_location_entry(categories):
        normalized.setdefault("location", normalized.get("title") or normalized.get("slug") or "Unnamed Location")
        location_type = _pick_location_type(categories)
        if location_type:
            normalized["location_type"] = location_type
        if "location" not in categories:
            normalized["categories"] = sorted(set(categories + ["location"]))

    settings = normalize_settings_values(normalized.get("settings"))
    if not settings:
        settings = normalize_settings_values(normalized.get("setting"))
    if not settings:
        settings = normalize_settings_values(default_settings or [])
    if settings:
        normalized["settings"] = settings
        normalized["setting"] = normalized.get("setting") or settings[0]
    description = str(normalized.get("description") or "").strip()
    if not description:
        description = str(normalized.get("excerpt") or "").strip()
    if description:
        normalized["description"] = description
        normalized.setdefault("excerpt", description)
    normalized["images"] = _normalize_image_refs(normalized.get("images"))
    return normalized


def load_lore_index(
    lore_dir: Path,
    *,
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    path = lore_dir / "index.json"
    if not path.exists():
        return {"count": 0, "items": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else []
    if isinstance(items, list):
        data["items"] = [
            _normalize_lore_item(item, default_settings=default_settings)
            for item in items
            if isinstance(item, dict)
        ]
        data["count"] = len(data["items"])
    return data


def list_lore_items(
    lore_dir: Path,
    *,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    data = load_lore_index(lore_dir, default_settings=default_settings)
    return data.get("items", []) or []


def load_lore_item(
    lore_dir: Path,
    slug: str,
    *,
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    path = lore_dir / "entries" / f"{slug}.json"
    if not path.exists():
        raise FileNotFoundError(f"No lore entry named '{slug}'")
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data.setdefault("schema_version", LORE_ENTRY_SCHEMA_VERSION)
        return _normalize_lore_item(data, default_settings=default_settings)
    return data


def search_lore(
    lore_dir: Path,
    query: str | None = None,
    *,
    setting: str | None = None,
    location: str | None = None,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    query_lc = (query or "").strip().lower()
    setting_lc = (setting or "").strip().lower()
    location_lc = (location or "").strip().lower()
    results: list[dict[str, Any]] = []
    for item in list_lore_items(lore_dir, default_settings=default_settings):
        item_settings = [
            str(value or "").strip().lower()
            for value in (item.get("settings") or [])
            if str(value or "").strip()
        ]
        if setting_lc and setting_lc not in item_settings:
            continue
        item_location = str(item.get("location") or item.get("title") or "").strip().lower()
        if location_lc and location_lc not in item_location:
            continue
        if not query_lc:
            results.append(item)
            continue
        hay = " ".join([
            str(item.get("title", "")),
            str(item.get("description", "")),
            str(item.get("excerpt", "")),
            " ".join(item.get("categories", []) or []),
            " ".join(item.get("settings", []) or []),
            str(item.get("location", "")),
            str(item.get("location_type", "")),
            str(item.get("area", "")),
            str(item.get("source_path", "")),
        ]).lower()
        if query_lc in hay:
            results.append(item)
    return results


def _safe_slug(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _clean_text_block(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _active_ai_lore_setting(
    *,
    setting: str | None = None,
    default_settings: list[str] | None = None,
) -> str:
    options = normalize_settings_values(setting) + normalize_settings_values(default_settings or [])
    for token in options:
        if token not in {"fantasy", "science_fiction", "cyberpunk", "modern", "all_settings"}:
            return token
    return options[0] if options else ""


def _matching_lore_entries_for_race(
    lore_dir: Path,
    *,
    race_id: str,
    race_cfg: dict[str, Any],
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    race_slug = _safe_slug(race_id)
    tokens = {
        _safe_slug(race_id),
        _safe_slug(race_cfg.get("name")),
        _safe_slug(race_cfg.get("character_base")),
    }
    variant_tokens: set[str] = set()
    for variant_id in (race_cfg.get("variants") or {}).keys():
        variant_tokens.add(_safe_slug(variant_id))
        variant_cfg = race_cfg.get("variants", {}).get(variant_id) or {}
        variant_tokens.add(_safe_slug(variant_cfg.get("label")))
    # Human variants in this setting are often regional/cultural labels rather than
    # stable race names, so matching them too aggressively causes Fenmir/Xanthir area
    # lore to bleed into the generic human guide.
    if race_slug != "human":
        tokens.update(variant_tokens)
    tokens = {token for token in tokens if token}
    for item in list_lore_items(lore_dir, default_settings=default_settings):
        if not isinstance(item, dict):
            continue
        hay_parts = [
            str(item.get("slug") or ""),
            str(item.get("title") or ""),
            str(item.get("description") or ""),
            str(item.get("excerpt") or ""),
            " ".join(item.get("categories", []) or []),
            " ".join(item.get("terms", []) or []),
        ]
        hay = " ".join(hay_parts).lower()
        score = 0
        for token in tokens:
            if token and token in _safe_slug(hay):
                score += 3 if token in _safe_slug(item.get("title")) else 1
        if race_slug != "human":
            for token in variant_tokens:
                if token and token in _safe_slug(hay):
                    score += 3 if token in _safe_slug(item.get("title")) else 1
        if score > 0:
            candidates.append((score, item))
    candidates.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in candidates[:3]]


def _extract_name_examples(
    names_cfg: dict[str, Any],
    race_id: str,
    variant_id: str = "",
) -> tuple[list[str], list[str]]:
    personal_names = names_cfg.get("personal_names") if isinstance(names_cfg.get("personal_names"), dict) else {}
    race_names = personal_names.get(race_id) if isinstance(personal_names.get(race_id), dict) else {}
    first_names = race_names.get("first") if isinstance(race_names.get("first"), list) else []
    surnames = race_names.get("surnames") if isinstance(race_names.get("surnames"), list) else []
    if variant_id:
        by_variant = race_names.get("by_variant") if isinstance(race_names.get("by_variant"), dict) else {}
        variant_names = by_variant.get(variant_id) if isinstance(by_variant.get(variant_id), dict) else {}
        if isinstance(variant_names.get("first"), list):
            first_names = variant_names.get("first") or first_names
        if isinstance(variant_names.get("surnames"), list):
            surnames = variant_names.get("surnames") or surnames
        elif isinstance(variant_names.get("clan_names"), list):
            surnames = variant_names.get("clan_names") or surnames
        elif isinstance(variant_names.get("titles"), list):
            surnames = variant_names.get("titles") or surnames
    return [str(x).strip() for x in first_names[:6] if str(x).strip()], [str(x).strip() for x in surnames[:6] if str(x).strip()]


def _matching_area_names_for_cultures(config: dict[str, Any], culture_tokens: set[str]) -> list[str]:
    areas_obj = config.get("areas") if isinstance(config.get("areas"), dict) else {}
    matches: list[str] = []
    for area_id, area_value in areas_obj.items():
        if not isinstance(area_value, dict):
            continue
        culture = _safe_slug(area_value.get("culture"))
        if culture and culture in culture_tokens:
            label = str(area_value.get("name") or area_id).strip()
            if label and label not in matches:
                matches.append(label)
    return matches[:8]


def _trim_markdown_excerpt(value: str, *, max_chars: int = 1000) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars - 3].rstrip()}..."


def _infer_recognition_profile(race_id: str, race_cfg: dict[str, Any], variants_obj: dict[str, Any]) -> dict[str, Any]:
    race_slug = _safe_slug(race_id)
    visual_defaults = race_cfg.get("visual_defaults") if isinstance(race_cfg.get("visual_defaults"), dict) else {}
    signature_features = [str(x).strip() for x in (visual_defaults.get("signature_features") or []) if str(x).strip()]
    all_appearance = " ".join(signature_features).lower()
    for variant_cfg_raw in variants_obj.values():
        variant_cfg = variant_cfg_raw if isinstance(variant_cfg_raw, dict) else {}
        all_appearance += " " + " ".join(str(x).strip().lower() for x in (variant_cfg.get("appearance") or []) if str(x).strip())

    def yn(value: bool) -> str:
        return "yes" if value else "no"

    size = _clean_text_block(visual_defaults.get("scale")) or "unknown"
    animal_traits = yn(race_slug == "fellic" or any(word in all_appearance for word in ["tail", "muzzle", "fur", "tusk", "animal", "beak"]))
    pointed_ears = yn(race_slug == "alfirin" or "pointed ears" in all_appearance)
    wings = yn(any(word in all_appearance for word in ["wing", "wings"]))
    horns = yn(race_slug == "lilim" or any(word in all_appearance for word in ["horn", "horned"]))
    tusks = yn(race_slug == "uruk" or "tusk" in all_appearance)
    tiny = yn(any(word in size for word in ["tiny", "small", "small compact"]))
    humanoid = "yes"
    if race_slug in {"fellic"}:
        humanoid = "mostly_humanoid_with_animal_aspects"
    elif race_slug in {"velim"}:
        humanoid = "small_humanoid"
    skin_palette = _clean_text_block(visual_defaults.get("skin_palette")) or "varied or unspecified"

    return {
        "humanoid": humanoid,
        "size": size,
        "pointed_ears": pointed_ears,
        "animal_traits": animal_traits,
        "wings": wings,
        "horns": horns,
        "tusks": tusks,
        "skin_palette": skin_palette,
        "common_visual_cues": signature_features[:6],
        "triage_keywords": sorted({
            race_slug,
            *(token for token in re.findall(r"[a-z0-9]+", all_appearance) if len(token) >= 4),
        })[:24],
        "likely_branch_order": [str(key).strip() for key in variants_obj.keys() if str(key).strip()],
        "is_small": tiny,
    }


def _build_disambiguation_rules(race_id: str, race_cfg: dict[str, Any], variants_obj: dict[str, Any]) -> list[str]:
    race_slug = _safe_slug(race_id)
    rules: list[str] = []
    if race_slug == "alfirin":
        rules.extend([
            "If the portrait shows pointed ears without obvious animal traits, consider alfirin before generic elf labels.",
            "If the portrait shows white hair, pale or violet skin, and dark layered dress, check duathrim first.",
            "Do not classify as alfirin when animal muzzle, tail, or other strong beast traits dominate the face or silhouette.",
        ])
    elif race_slug == "fellic":
        rules.extend([
            "If the subject is humanoid but clearly animal-aspected, consider fellic before human or alfirin.",
            "Use the animal aspect to narrow the branch: fox for sly diplomatic cues, dog for oath-bound guardians, bear for elder memory-keepers.",
            "Do not reduce fellic to cute mascots or generic beastfolk without aspect-specific flavor.",
        ])
    elif race_slug == "lhainim":
        rules.extend([
            "If the figure is very small and fey-coded, check lhainim before treating it as a child-sized human or alfirin.",
            "Wings, luminous motion, or threshold-trickster cues usually matter more than conventional mortal ancestry markers.",
        ])
    elif race_slug == "human":
        rules.extend([
            "If the portrait lacks strong elder-race or beast-aspect markers, human remains a valid answer.",
            "Use variant cues like xanthir, fenmir, or caldoran to refine culture rather than inventing a separate race.",
            "Keep Highland Fenmir and Lowland Fenmir distinct: Highland Fenmir are mountain highlanders marked by ritual tattoos, clan memory, and shamanic culture.",
            "Lowland Fenmir should read as embattled farmers, villagers, militias, and survivors shaped by repeated Lowland Uruk raids rather than highland tribal tattoo culture.",
        ])
    elif race_slug == "uruk":
        rules.extend([
            "If the subject has tusks, immense build, and a powerful jaw, check uruk before generic orc or giant labels.",
            "Use skin color and dress cues to separate highland and lowland uruk branches.",
        ])
    elif race_slug == "lilim":
        rules.extend([
            "If the portrait has horned or infernal traits without demonic villain context, check lilim.",
            "Treat magical wanderer and ritual-language cues as stronger than outsider demon stereotypes.",
        ])
    elif race_slug == "velim":
        rules.extend([
            "If the being is tiny, luminous, and marked by threshold symbolism or translucent otherworldly features, check velim before lhainim.",
            "Do not add wings to velim unless a specific source explicitly says this individual has them.",
        ])

    for variant_id, variant_cfg_raw in variants_obj.items():
        variant_cfg = variant_cfg_raw if isinstance(variant_cfg_raw, dict) else {}
        appearance = [str(x).strip() for x in (variant_cfg.get("appearance") or []) if str(x).strip()]
        if appearance:
            rules.append(
                f"If classifying {race_id}, use {variant_id} when these cues dominate: {', '.join(appearance[:4])}."
            )
    return rules[:12]


def _matching_lore_entries_for_area(
    lore_dir: Path,
    *,
    area_id: str,
    area_cfg: dict[str, Any],
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    tokens = {
        _safe_slug(area_id),
        _safe_slug(area_cfg.get("name")),
        _safe_slug(area_cfg.get("culture")),
        _safe_slug(area_cfg.get("type")),
    }
    tokens = {token for token in tokens if token}
    for item in list_lore_items(lore_dir, default_settings=default_settings):
        if not isinstance(item, dict):
            continue
        hay_parts = [
            str(item.get("slug") or ""),
            str(item.get("title") or ""),
            str(item.get("description") or ""),
            str(item.get("excerpt") or ""),
            str(item.get("content_markdown") or "")[:1800],
            " ".join(item.get("categories", []) or []),
            " ".join(item.get("terms", []) or []),
        ]
        hay = _safe_slug(" ".join(hay_parts))
        score = 0
        for token in tokens:
            if token and token in hay:
                score += 3 if token in _safe_slug(item.get("title")) else 1
        if score > 0:
            candidates.append((score, item))
    candidates.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in candidates[:4]]


def _infer_area_recognition_profile(area_id: str, area_cfg: dict[str, Any]) -> dict[str, Any]:
    visual_traits = [str(x).strip() for x in (area_cfg.get("visual_traits") or []) if str(x).strip()]
    mood = [str(x).strip() for x in (area_cfg.get("mood") or []) if str(x).strip()]
    area_type = _clean_text_block(area_cfg.get("type")) or "region"
    description = _clean_text_block(area_cfg.get("description"))
    triage_blob = " ".join([area_id, area_type, description, *visual_traits, *mood]).lower()

    def yn(words: list[str]) -> str:
        return "yes" if any(word in triage_blob for word in words) else "no"

    return {
        "region_type": area_type,
        "coastal_or_sea": yn(["coast", "sea", "harbor", "dock", "ocean"]),
        "mountain_or_highland": yn(["mountain", "highland", "ridge", "cliff", "peak"]),
        "forest_or_wild": yn(["forest", "grove", "wild", "wood", "tree", "root"]),
        "urban_or_fortified": yn(["city", "fort", "fortified", "plaza", "harbor", "dock"]),
        "religious_or_ritual": yn(["ritual", "sacred", "temple", "stone circle", "ancestral"]),
        "common_visual_cues": visual_traits[:8],
        "mood_cues": mood[:6],
        "triage_keywords": sorted({
            token for token in re.findall(r"[a-z0-9]+", triage_blob) if len(token) >= 4
        })[:28],
    }


def _build_area_disambiguation_rules(area_id: str, area_cfg: dict[str, Any], lore_matches: list[dict[str, Any]]) -> list[str]:
    area_name = str(area_cfg.get("name") or area_id).strip()
    culture = str(area_cfg.get("culture") or "").strip()
    visual_traits = [str(x).strip() for x in (area_cfg.get("visual_traits") or []) if str(x).strip()]
    rules: list[str] = []
    if culture:
        rules.append(f"If a portrait or place cue points strongly to {culture}, consider {area_name} among the likely homelands or current regions.")
    if visual_traits:
        rules.append(f"If these cues dominate, check {area_name}: {', '.join(visual_traits[:4])}.")
    for item in lore_matches:
        title = str(item.get("title") or "").strip()
        excerpt = _clean_text_block(item.get("excerpt") or item.get("description"))
        if title and excerpt:
            rules.append(f"If the brief mentions {title}, use it to refine {area_name} flavor: {excerpt[:140]}.")
    return rules[:10]


def _extract_belief_cues(lore_dir: Path, lore_matches: list[dict[str, Any]], default_settings: list[str] | None = None) -> list[str]:
    cues: list[str] = []
    keywords = [
        "red god", "faith", "ritual", "sacrifice", "old gods", "lilith", "daelgast",
        "synod", "doctrine", "heresy", "priest", "temple", "ancestral", "breath of the world",
    ]
    for item in lore_matches:
        slug = str(item.get("slug") or "").strip()
        title = str(item.get("title") or slug or "Lore").strip()
        full_item = item
        if slug:
            try:
                loaded = load_lore_item(lore_dir, slug, default_settings=default_settings)
                if isinstance(loaded, dict):
                    full_item = loaded
            except Exception:
                full_item = item
        body = str(full_item.get("content_markdown") or full_item.get("description") or "").lower()
        matched = [kw for kw in keywords if kw in body]
        if matched:
            cues.append(f"{title}: {', '.join(matched[:6])}")
    return cues[:8]


def _build_ai_area_lore_item(
    lore_dir: Path,
    *,
    area_id: str,
    area_cfg: dict[str, Any],
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    area_name = str(area_cfg.get("name") or area_id).strip() or area_id
    lore_matches = _matching_lore_entries_for_area(
        lore_dir,
        area_id=area_id,
        area_cfg=area_cfg,
        default_settings=default_settings,
    )
    visual_traits = [str(x).strip() for x in (area_cfg.get("visual_traits") or []) if str(x).strip()]
    mood = [str(x).strip() for x in (area_cfg.get("mood") or []) if str(x).strip()]
    area_type = _clean_text_block(area_cfg.get("type")) or "region"
    culture = str(area_cfg.get("culture") or "").strip()
    description = _clean_text_block(area_cfg.get("description"))
    recognition_profile = _infer_area_recognition_profile(area_id, area_cfg)
    disambiguation_rules = _build_area_disambiguation_rules(area_id, area_cfg, lore_matches)
    belief_cues = _extract_belief_cues(lore_dir, lore_matches, default_settings=default_settings)

    lore_sections: list[str] = []
    source_titles: list[str] = []
    for item in lore_matches:
        title = str(item.get("title") or item.get("slug") or "Lore").strip()
        body = _trim_markdown_excerpt(str(item.get("content_markdown") or item.get("description") or "").strip(), max_chars=700)
        if title:
            source_titles.append(title)
        if body:
            lore_sections.append(f"### {title}\n{body}")

    description_bits = [
        f"AI-friendly area guide for {area_name}.",
        f"Type: {area_type}.",
    ]
    if culture:
        description_bits.append(f"Culture: {culture}.")
    if visual_traits:
        description_bits.append(f"Visual cues: {', '.join(visual_traits[:4])}.")
    description_text = " ".join(description_bits)

    content_parts = [
        f"# AI Lore: {area_name}",
        "## Recognition Profile",
        "\n".join([
            f"- Region type: {recognition_profile.get('region_type')}.",
            f"- Coastal or sea: {recognition_profile.get('coastal_or_sea')}.",
            f"- Mountain or highland: {recognition_profile.get('mountain_or_highland')}.",
            f"- Forest or wild: {recognition_profile.get('forest_or_wild')}.",
            f"- Urban or fortified: {recognition_profile.get('urban_or_fortified')}.",
            f"- Religious or ritual: {recognition_profile.get('religious_or_ritual')}.",
            f"- Triage keywords: {', '.join(recognition_profile.get('triage_keywords') or [])}.",
        ]),
        "## Allowed Identity Labels",
        "\n".join(filter(None, [
            f"- {area_id}",
            f"- {area_name}" if area_name.lower() != area_id.lower() else "",
            f"- {culture}" if culture else "",
        ])),
    ]
    if description:
        content_parts.extend(["## Area Summary", description])
    if visual_traits:
        content_parts.extend(["## Visual Cues", "\n".join(f"- {line}" for line in visual_traits)])
    if mood:
        content_parts.extend(["## Mood and Atmosphere", "\n".join(f"- {line}" for line in mood)])
    if disambiguation_rules:
        content_parts.extend(["## Disambiguation Rules", "\n".join(f"- {line}" for line in disambiguation_rules)])
    if belief_cues:
        content_parts.extend(["## Belief and Power Cues", "\n".join(f"- {line}" for line in belief_cues)])
    if lore_sections:
        content_parts.extend(["## Lore Snippets", "\n\n".join(lore_sections)])

    settings = normalize_settings_values(area_cfg.get("settings"))
    if not settings:
        settings = normalize_settings_values(default_settings or [])
    item = {
        "type": "lore",
        "title": f"AI Lore: {area_name}",
        "slug": f"ai_lore_area_{_safe_slug(area_id)}",
        "source": "ai_lore",
        "source_path": f"ai_lore/areas/{_safe_slug(area_id)}",
        "excerpt": description_text,
        "description": description_text,
        "categories": ["ai_lore", "area", "place_guide"],
        "settings": settings,
        "setting": settings[0] if settings else "",
        "ai_lore_kind": "area",
        "area": area_id,
        "culture": culture,
        "recognition_profile": recognition_profile,
        "disambiguation_rules": disambiguation_rules,
        "allowed_identity_labels": [value for value in [area_id, area_name, culture] if str(value).strip()],
        "terms": sorted({
            _safe_slug(area_id),
            _safe_slug(area_name),
            _safe_slug(culture),
            *(_safe_slug(title) for title in source_titles),
            *(_safe_slug(cue) for cue in belief_cues),
        }),
        "related_lore_slugs": [str(item.get("slug") or "").strip() for item in lore_matches if str(item.get("slug") or "").strip()],
        "content_markdown": "\n\n".join(part for part in content_parts if str(part).strip()),
    }
    return _normalize_lore_item(item, default_settings=default_settings)


def _load_drift_test(lore_dir: Path, default_settings: list[str] | None = None) -> str:
    path = lore_dir / "prompts_index.json"
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    items = data.get("items") if isinstance(data, dict) else []
    if not isinstance(items, list):
        return ""
    active_settings = set(normalize_settings_values(default_settings or []))
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip().lower()
        text = str(item.get("text") or "").strip()
        item_settings = set(normalize_settings_values(item.get("settings") or item.get("setting")))
        if "drift test" in title and text and (not active_settings or not item_settings or active_settings.intersection(item_settings)):
            return text
    return ""


def _load_full_lore_by_slug(lore_dir: Path, slug: str, default_settings: list[str] | None = None) -> dict[str, Any]:
    try:
        loaded = load_lore_item(lore_dir, slug, default_settings=default_settings)
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return {}


def _extract_doctrine_keywords(body: str) -> list[str]:
    keywords = [
        "pressures not persons",
        "gods are not beings",
        "condition not actor",
        "red god",
        "lilith",
        "daelgast",
        "ul_nha_rath",
        "black affirmation",
        "old gods",
        "breath of the world",
        "ritual aligns with forces",
        "faith shapes behavior",
        "misunderstanding a force",
        "personifies the red god",
        "drift test",
        "adds pressure not answers",
    ]
    body_slug = _safe_slug(body)
    return [kw.replace("_", " ") for kw in keywords if _safe_slug(kw) in body_slug]


def _build_ai_doctrine_lore_items(
    lore_dir: Path,
    *,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    gods = _load_full_lore_by_slug(lore_dir, "gods_and_powers", default_settings=default_settings)
    world_seed = _load_full_lore_by_slug(lore_dir, "world_seed", default_settings=default_settings)
    xanthir = _load_full_lore_by_slug(lore_dir, "xanthir", default_settings=default_settings)
    drift_test = _load_drift_test(lore_dir, default_settings=default_settings)

    cosmology_body = "\n\n".join([
        str(gods.get("content_markdown") or ""),
        str(world_seed.get("content_markdown") or ""),
        drift_test,
    ]).strip()
    xanthir_body = "\n\n".join([
        str(xanthir.get("content_markdown") or ""),
        str(gods.get("content_markdown") or ""),
        drift_test,
    ]).strip()

    items: list[dict[str, Any]] = []
    if cosmology_body:
        cosmology_content = "\n\n".join([
            "# AI Lore: Cosmology and Religion",
            "## Recognition Profile",
            "- Gods are pressures, conditions, resonances, or principles rather than speaking anthropomorphic deities.",
            "- Religion is culturally interpreted force-alignment, not guaranteed divine conversation.",
            "- Daelgast, Ul-Nha'rath, and the Breath of the World should be treated as conditions or pressures, not as chatty actors.",
            "## Allowed Identity Labels",
            "- cosmology",
            "- religion",
            "- gods_and_powers",
            "- red god",
            "- lilith",
            "- old gods",
            "- daelgast",
            "- ul_nha_rath",
            "- breath_of_the_world",
            "## Disambiguation Rules",
            "- If a query assumes gods are speaking people with clear personal intent, correct toward pressures, principles, or resonances if the lore supports that.",
            "- If a query personifies Daelgast, Ul-Nha'rath, or the Breath, restate them as conditions or world-pressures rather than individual actors.",
            "- If a culture's doctrine conflicts with the deeper cosmology, present both: the belief and the underlying force it misunderstands.",
            "## Drift Test",
            _trim_markdown_excerpt(drift_test, max_chars=2200) if drift_test else "- Drift guidance unavailable.",
            "## Source Lore",
            _trim_markdown_excerpt(cosmology_body, max_chars=3200),
        ])
        items.append(_normalize_lore_item({
            "type": "lore",
            "title": "AI Lore: Cosmology and Religion",
            "slug": "ai_lore_doctrine_cosmology",
            "source": "ai_lore",
            "source_path": "ai_lore/doctrine/cosmology",
            "excerpt": "AI guide to Lands of Legends cosmology, religion, powers, and drift safeguards.",
            "description": "AI guide to Lands of Legends cosmology, religion, powers, and drift safeguards.",
            "categories": ["ai_lore", "doctrine", "cosmology", "religion_guide"],
            "settings": normalize_settings_values(default_settings or []),
            "setting": normalize_settings_values(default_settings or [])[0] if normalize_settings_values(default_settings or []) else "",
            "ai_lore_kind": "doctrine",
            "recognition_profile": {
                "anthropomorphic_gods_expected": "no",
                "religion_is_cultural_interpretation": "yes",
                "conditions_not_actors": "yes",
                "triage_keywords": _extract_doctrine_keywords(cosmology_body)[:20],
            },
            "disambiguation_rules": [
                "Use pressures, principles, conditions, and resonances before personified god-language.",
                "Keep conflicting cultural interpretations and deeper metaphysical truth distinct.",
                "Run uncertain religion content through the drift test before treating it as canon.",
            ],
            "allowed_identity_labels": ["cosmology", "religion", "red_god", "lilith", "old_gods", "daelgast", "ul_nha_rath", "breath_of_the_world"],
            "related_lore_slugs": [slug for slug in ["gods_and_powers", "world_seed"] if slug],
            "terms": sorted({_safe_slug(term) for term in ["cosmology", "religion", "red god", "lilith", "old gods", "daelgast", "ul-nha'rath", "breath of the world", "drift test"]}),
            "content_markdown": cosmology_content,
        }, default_settings=default_settings))
    if xanthir_body:
        xanthir_content = "\n\n".join([
            "# AI Lore: Xanthir Doctrine",
            "## Recognition Profile",
            "- Xanthir is a militant theocracy that personifies the Red God.",
            "- This is a cultural doctrine, not the final metaphysical truth of the setting.",
            "- Look for priests, war-judges, crimson synods, sacrifice, conquest, ritual law, and sacred harbors.",
            "## Allowed Identity Labels",
            "- xanthir",
            "- xanthir doctrine",
            "- red faith",
            "- crimson synod",
            "- red god",
            "## Disambiguation Rules",
            "- Distinguish between what Xanthir believes about the Red God and what the deeper cosmology says the Red God is.",
            "- Do not flatten Xanthir into simple evil; treat it as harsh doctrine, coercive structure, and dangerous theological misreading.",
            "- If answering a Xanthir religion question, include both orthodoxy and internal tension or schism when supported by context.",
            "## Drift Test",
            _trim_markdown_excerpt(drift_test, max_chars=1800) if drift_test else "- Drift guidance unavailable.",
            "## Source Lore",
            _trim_markdown_excerpt(xanthir_body, max_chars=2600),
        ])
        items.append(_normalize_lore_item({
            "type": "lore",
            "title": "AI Lore: Xanthir Doctrine",
            "slug": "ai_lore_doctrine_xanthir",
            "source": "ai_lore",
            "source_path": "ai_lore/doctrine/xanthir",
            "excerpt": "AI guide to Xanthir theology, authority, and the setting-specific difference between doctrine and cosmology.",
            "description": "AI guide to Xanthir theology, authority, and the setting-specific difference between doctrine and cosmology.",
            "categories": ["ai_lore", "doctrine", "religion", "faction_guide"],
            "settings": normalize_settings_values(default_settings or []),
            "setting": normalize_settings_values(default_settings or [])[0] if normalize_settings_values(default_settings or []) else "",
            "ai_lore_kind": "doctrine",
            "recognition_profile": {
                "state_religion": "yes",
                "anthropomorphic_god_language_present": "yes_but_culturally_interpreted",
                "rigid_hierarchy": "yes",
                "triage_keywords": _extract_doctrine_keywords(xanthir_body)[:20] + ["crimson synod", "zealot", "war-priest", "sacrifice"],
            },
            "disambiguation_rules": [
                "Separate Xanthir orthodoxy from setting-level metaphysical truth.",
                "Treat Red God language in Xanthir as doctrine first, cosmology second.",
                "Use the drift test when a Xanthir answer starts sounding like standard evil-cleric fantasy.",
            ],
            "allowed_identity_labels": ["xanthir", "xanthir_doctrine", "red_faith", "crimson_synod", "red_god"],
            "related_lore_slugs": [slug for slug in ["xanthir", "gods_and_powers", "world_seed"] if slug],
            "terms": sorted({_safe_slug(term) for term in ["xanthir", "xanthir doctrine", "red faith", "crimson synod", "red god", "drift test", "heresy", "doctrine"]}),
            "content_markdown": xanthir_content,
        }, default_settings=default_settings))

    breath_body = "\n\n".join([
        str(gods.get("content_markdown") or ""),
        str(_load_full_lore_by_slug(lore_dir, "fenmir", default_settings=default_settings).get("content_markdown") or ""),
        str(_load_full_lore_by_slug(lore_dir, "the_human_tribes", default_settings=default_settings).get("content_markdown") or ""),
        str(_load_full_lore_by_slug(lore_dir, "the_uruk_tribes", default_settings=default_settings).get("content_markdown") or ""),
        str(_load_full_lore_by_slug(lore_dir, "places", default_settings=default_settings).get("content_markdown") or ""),
    ]).strip()
    if breath_body:
        breath_content = "\n\n".join([
            "# AI Lore: Breath Traditions",
            "## Recognition Profile",
            "- The Breath of the World is not a god and should not be personified as one.",
            "- Highland Fenmir and Highland Uruk traditions lean toward attunement, ancestral memory, trance, song, ordeal, and breath-path practice.",
            "- Lowland Uruk red-breath traditions lean toward Gor-Kha, war-breath, communal momentum, and costly violent immediacy.",
            "## Allowed Identity Labels",
            "- breath_of_the_world",
            "- highland_fenmir_shamanism",
            "- highland_uruk_shamanism",
            "- gor_kha",
            "- red_breath",
            "- red_surge",
            "## Disambiguation Rules",
            "- Distinguish gentle breath-attunement from Lowland Uruk red-breath frenzy.",
            "- Fenmir Highland and Highland Uruk shamanic practice should read as place-bound, ancestral, and breath-based rather than temple orthodoxy.",
            "- Do not collapse Gor-Kha into the Red God; they are different forces and different cultural expressions.",
            "## Source Lore",
            _trim_markdown_excerpt(breath_body, max_chars=3200),
        ])
        items.append(_normalize_lore_item({
            "type": "lore",
            "title": "AI Lore: Breath Traditions",
            "slug": "ai_lore_doctrine_breath_traditions",
            "source": "ai_lore",
            "source_path": "ai_lore/doctrine/breath_traditions",
            "excerpt": "AI guide for Highland Fenmir and Highland Uruk breath-attunement, plus Lowland Uruk Gor-Kha / Red Breath traditions.",
            "description": "AI guide for Highland Fenmir and Highland Uruk breath-attunement, plus Lowland Uruk Gor-Kha / Red Breath traditions.",
            "categories": ["ai_lore", "doctrine", "religion", "spiritual_practice"],
            "settings": normalize_settings_values(default_settings or []),
            "setting": normalize_settings_values(default_settings or [])[0] if normalize_settings_values(default_settings or []) else "",
            "ai_lore_kind": "doctrine",
            "recognition_profile": {
                "anthropomorphic_gods_expected": "no",
                "highland_shamanic_attunement": "yes",
                "lowland_red_breath": "yes",
                "triage_keywords": ["breath of the world", "anail", "sulennaeth", "gor-kha", "red surge", "shaman", "ancestral memory", "breath-paths"],
            },
            "disambiguation_rules": [
                "Keep Highland Fenmir and Highland Uruk breath-practice distinct from temple religion.",
                "Treat Gor-Kha / Red Breath as a distorted war-breath with cost, not as simple evil magic or the Red God's blessing.",
                "If the answer starts sounding like standard druidism or barbarian rage, restate it in local Breath terms.",
            ],
            "allowed_identity_labels": ["breath_of_the_world", "highland_fenmir_shamanism", "highland_uruk_shamanism", "gor_kha", "red_breath", "red_surge"],
            "related_lore_slugs": ["gods_and_powers", "fenmir", "the_human_tribes", "the_uruk_tribes", "places"],
            "terms": sorted({_safe_slug(term) for term in ["Breath of the World", "Anail", "Sulennaeth", "Gor-Kha", "Red Breath", "Red Surge", "Highland Fenmir", "Highland Uruk", "shaman"]}),
            "content_markdown": breath_content,
        }, default_settings=default_settings))

    daelgast = _load_full_lore_by_slug(lore_dir, "the_daelgast", default_settings=default_settings)
    hollow_body = "\n\n".join([
        str(daelgast.get("content_markdown") or ""),
        str(gods.get("content_markdown") or ""),
        drift_test,
    ]).strip()
    if hollow_body and "hollow accord" in hollow_body.lower():
        hollow_accord_content = "\n\n".join([
            "# AI Lore: Hollow Accord",
            "## Recognition Profile",
            "- The Hollow Accord is a decentralized Daelgast-linked cult or movement, not a demon church and not a standard evil priesthood.",
            "- It treats Daelgast as revelation and mistaken truth, not as a speaking god.",
            "- Look for tainted zones, self-exposure rituals, necrotic resonance, identity-fracture, and anti-containment behavior.",
            "## Allowed Identity Labels",
            "- hollow_accord",
            "- cult_of_the_hollow_accord",
            "- daelgast_revelation_cult",
            "## Disambiguation Rules",
            "- Do not collapse the Hollow Accord into generic demon worship; its error is existential and revelatory, not infernal obedience.",
            "- Keep Hollow Accord separate from Ul-Nha'rath cult logic unless the lore explicitly joins them.",
            "- Hollow Accord members mistake erosion for truth; the guide should preserve that theological error rather than endorsing it.",
            "## Source Lore",
            _trim_markdown_excerpt(hollow_body, max_chars=2600),
        ])
        items.append(_normalize_lore_item({
            "type": "lore",
            "title": "AI Lore: Hollow Accord",
            "slug": "ai_lore_doctrine_hollow_accord",
            "source": "ai_lore",
            "source_path": "ai_lore/doctrine/hollow_accord",
            "excerpt": "AI guide to the Hollow Accord as a Daelgast-linked revelation cult shaped by erosion, tainted zones, and anti-containment belief.",
            "description": "AI guide to the Hollow Accord as a Daelgast-linked revelation cult shaped by erosion, tainted zones, and anti-containment belief.",
            "categories": ["ai_lore", "doctrine", "faction_guide"],
            "settings": normalize_settings_values(default_settings or []),
            "setting": normalize_settings_values(default_settings or [])[0] if normalize_settings_values(default_settings or []) else "",
            "ai_lore_kind": "doctrine",
            "recognition_profile": {
                "anthropomorphic_gods_expected": "no",
                "daelgast_revelation_cult": "yes",
                "source_backing": "present",
                "triage_keywords": ["hollow accord", "daelgast", "revelation", "necrotic resonance", "tainted zones", "identity fracture", "containment breach"],
            },
            "disambiguation_rules": [
                "Treat Hollow Accord as a Daelgast-corruption cult, not a generic demon sect.",
                "Keep their doctrine framed as error: they think Daelgast reveals truth, but the lore says it erodes.",
                "Use drift-test caution so they do not become melodramatic cosmic villains.",
            ],
            "allowed_identity_labels": ["hollow_accord", "cult_of_the_hollow_accord", "daelgast_revelation_cult"],
            "related_lore_slugs": ["the_daelgast", "gods_and_powers"],
            "terms": ["hollow_accord", "cult_of_the_hollow_accord", "daelgast_revelation_cult", "necrotic_resonance"],
            "content_markdown": hollow_accord_content,
        }, default_settings=default_settings))
    return items


def _matching_lore_entries_for_profession(
    lore_dir: Path,
    *,
    profession_id: str,
    profession_cfg: dict[str, Any],
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    candidates: list[tuple[int, dict[str, Any]]] = []
    tokens = {
        _safe_slug(profession_id),
        _safe_slug(profession_cfg.get("role")),
        *(_safe_slug(x) for x in (profession_cfg.get("gear_options") or [])),
        *(_safe_slug(x) for x in (profession_cfg.get("weapon_options") or [])),
    }
    tokens = {token for token in tokens if token}
    for item in list_lore_items(lore_dir, default_settings=default_settings):
        if not isinstance(item, dict):
            continue
        hay = _safe_slug(" ".join([
            str(item.get("title") or ""),
            str(item.get("description") or ""),
            str(item.get("excerpt") or ""),
            str(item.get("content_markdown") or "")[:2000],
            " ".join(item.get("terms", []) or []),
            " ".join(item.get("categories", []) or []),
        ]))
        score = 0
        for token in tokens:
            if token and token in hay:
                score += 3 if token in _safe_slug(item.get("title")) else 1
        if score > 0:
            candidates.append((score, item))
    candidates.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in candidates[:4]]


def _infer_profession_recognition_profile(profession_id: str, profession_cfg: dict[str, Any]) -> dict[str, Any]:
    appearance = _clean_text_block(profession_cfg.get("appearance"))
    clothing = _clean_text_block(profession_cfg.get("clothing"))
    role = str(profession_cfg.get("role") or profession_id).strip()
    prompt_type = str(profession_cfg.get("prompt_type") or "").strip()
    weapons = [str(x).strip() for x in (profession_cfg.get("weapon_options") or []) if str(x).strip()]
    gear = [str(x).strip() for x in (profession_cfg.get("gear_options") or []) if str(x).strip()]
    poses = [str(x).strip() for x in (profession_cfg.get("pose_options") or []) if str(x).strip()]
    blob = " ".join([profession_id, role, prompt_type, appearance, clothing, *weapons, *gear, *poses]).lower()

    def yn(words: list[str]) -> str:
        return "yes" if any(word in blob for word in words) else "no"

    return {
        "role_family": role,
        "martial_or_guarded": yn(["armor", "blade", "shield", "spear", "martial", "guard", "war"]),
        "ritual_or_sacred": yn(["ritual", "sacred", "invocation", "scroll", "talisman", "priest", "cleric", "shaman"]),
        "social_or_diplomatic": yn(["charisma", "negoti", "merchant", "voice", "presence", "advisor", "entertainer"]),
        "travel_or_fieldwork": yn(["travel", "trail", "track", "rough country", "field", "map", "survive"]),
        "common_visual_cues": [value for value in [appearance, clothing] if value][:2],
        "common_tools": (weapons + gear)[:8],
        "triage_keywords": sorted({
            token for token in re.findall(r"[a-z0-9]+", blob) if len(token) >= 4
        })[:28],
    }


def _build_profession_disambiguation_rules(profession_id: str, profession_cfg: dict[str, Any], lore_matches: list[dict[str, Any]]) -> list[str]:
    rules: list[str] = []
    profession_slug = _safe_slug(profession_id)
    if profession_slug == "priest":
        rules.extend([
            "Do not assume every priest is gentle or pleasant; check doctrine, dress, and expression.",
            "In Xanthir contexts, priest may imply war-priest, judge, zealot, or synod authority rather than a soft healer.",
            "Separate sacred office from cosmological truth; a priest may personify a force that the deeper lore treats as impersonal.",
        ])
    elif profession_slug == "shaman":
        rules.extend([
            "Shaman usually implies attunement, breath-paths, ancestral memory, trance, or land-speaking rather than temple hierarchy.",
            "If ritual practice is local, animist, or landscape-bound, check shaman before priest.",
        ])
    elif profession_slug == "merchant":
        rules.extend([
            "Merchant can imply cosmopolitan broker, caravan factor, harbor trader, or Free City deal-maker rather than generic shopkeeper.",
            "If the role is tied to trade law, diplomacy, or contracts, merchant may overlap with speaker-family roles.",
        ])
    elif profession_slug in {"captain", "privateer", "raider"}:
        rules.append("If the role centers on command at sea, contracts, or crews, prefer captain-like readings over generic warrior.")

    for item in lore_matches:
        title = str(item.get("title") or "").strip()
        excerpt = _clean_text_block(item.get("excerpt") or item.get("description"))
        if title and excerpt:
            rules.append(f"If the brief leans on {title}, use it to flavor the role: {excerpt[:140]}.")
    return rules[:10]


def _build_ai_profession_lore_item(
    lore_dir: Path,
    *,
    config: dict[str, Any],
    profession_id: str,
    profession_cfg: dict[str, Any],
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    role_label = str(profession_cfg.get("role") or profession_id).strip() or profession_id
    lore_matches = _matching_lore_entries_for_profession(
        lore_dir,
        profession_id=profession_id,
        profession_cfg=profession_cfg,
        default_settings=default_settings,
    )
    appearance = _clean_text_block(profession_cfg.get("appearance"))
    clothing = _clean_text_block(profession_cfg.get("clothing"))
    weapons = [str(x).strip() for x in (profession_cfg.get("weapon_options") or []) if str(x).strip()]
    gear = [str(x).strip() for x in (profession_cfg.get("gear_options") or []) if str(x).strip()]
    poses = [str(x).strip() for x in (profession_cfg.get("pose_options") or []) if str(x).strip()]
    recognition_profile = _infer_profession_recognition_profile(profession_id, profession_cfg)
    disambiguation_rules = _build_profession_disambiguation_rules(profession_id, profession_cfg, lore_matches)
    areas_obj = config.get("areas") if isinstance(config.get("areas"), dict) else {}
    culture_hints: list[str] = []
    doctrine_hints: list[str] = []
    role_blob = _safe_slug(" ".join([
        profession_id,
        str(profession_cfg.get("role") or ""),
        appearance,
        clothing,
        " ".join(weapons),
        " ".join(gear),
    ]))
    for area_id, area_cfg_raw in areas_obj.items():
        area_cfg = area_cfg_raw if isinstance(area_cfg_raw, dict) else {}
        area_name = str(area_cfg.get("name") or area_id).strip()
        area_culture = str(area_cfg.get("culture") or "").strip()
        area_desc = _safe_slug(" ".join([
            area_id,
            area_name,
            str(area_cfg.get("description") or ""),
            " ".join(area_cfg.get("visual_traits") or []),
        ]))
        if profession_id == "priest" and any(token in area_desc for token in ["temple", "sacred", "ritual", "theocracy", "religious"]):
            doctrine_hints.append(f"{area_name}: priestly authority is likely shaped by {area_culture or 'local'} doctrine and ritual order.")
        elif profession_id == "shaman" and any(token in area_desc for token in ["stone", "ancestral", "wild", "forest", "spiritual"]):
            culture_hints.append(f"{area_name}: shamans here likely reflect ancestral law, land-memory, or breath-path traditions.")
        elif profession_id == "merchant" and any(token in area_desc for token in ["trade", "harbor", "market", "dock", "city", "port"]):
            culture_hints.append(f"{area_name}: merchants here likely mediate contracts, mixed peoples, and opportunistic trade.")
        elif profession_id in {"captain", "privateer", "raider"} and any(token in area_desc for token in ["sea", "harbor", "dock", "pirate", "coast"]):
            culture_hints.append(f"{area_name}: captains here are likely sea-commanders, privateers, or harbor power-brokers.")
        elif profession_id in {"guard", "soldier", "warrior"} and any(token in area_desc for token in ["fort", "war", "frontier", "harsh", "contested"]):
            culture_hints.append(f"{area_name}: martial roles here are likely shaped by frontier pressure and defensive duty.")
        elif profession_id in {"scholar", "wizard", "seer", "oracle", "mystic"} and any(token in area_desc for token in ["scholar", "crystalline", "ancient", "gate", "ruin"]):
            culture_hints.append(f"{area_name}: learned roles here likely mix scholarship with old-world caution or gate-lore.")
    if not culture_hints and profession_id == "priest":
        doctrine_hints.append("Priestly roles should be flavored by local doctrine, cosmology, and ritual structure rather than generic benevolent-cleric assumptions.")
    if not culture_hints and profession_id == "merchant":
        culture_hints.append("Merchant roles should usually carry local trade style, law, or faction pressure rather than reading as generic shopkeepers.")
    if not culture_hints and profession_id == "shaman":
        culture_hints.append("Shaman roles should lean toward place-bound ritual, ancestral memory, or breath-attunement rather than temple orthodoxy.")

    creative_scaffolds: list[str] = []
    if profession_id == "priest":
        creative_scaffolds.extend([
            "Ask: is this temple hierarchy, war-faith discipline, village ritekeeping, or forbidden doctrine?",
            "Ask: does the role preserve order, interpret sacrifice, heal community wounds, or enforce coercive belief?",
        ])
    elif profession_id == "shaman":
        creative_scaffolds.extend([
            "Ask: what place, ancestor line, or breathing practice gives this role authority?",
            "Ask: is the shaman a guide, omen-reader, healer, memory-keeper, or dangerous ecstatic?",
        ])
    elif profession_id == "merchant":
        creative_scaffolds.extend([
            "Ask: is this role caravan broker, harbor factor, treaty-maker, contraband fixer, or guild agent?",
            "Ask: what local goods, laws, or obligations define this merchant's posture and reputation?",
        ])
    elif profession_id in {"innkeeper", "proprietor"}:
        creative_scaffolds.extend([
            "Ask: is this host a neutral keeper, rumor broker, retired survivor, or local power node?",
            "Ask: what does the inn trade in besides beds and drink: safety, gossip, smuggling, or sanctuary?",
        ])
    else:
        creative_scaffolds.extend([
            "When lore is thin, derive role flavor from local culture, area pressure, equipment, and doctrine instead of generic fantasy defaults.",
            "Treat profession as a social function in a place, not just a costume or combat style.",
        ])
    lore_sections: list[str] = []
    source_titles: list[str] = []
    for item in lore_matches:
        title = str(item.get("title") or item.get("slug") or "Lore").strip()
        body = _trim_markdown_excerpt(str(item.get("content_markdown") or item.get("description") or "").strip(), max_chars=650)
        if title:
            source_titles.append(title)
        if body:
            lore_sections.append(f"### {title}\n{body}")

    content_parts = [
        f"# AI Lore: Role {role_label.title()}",
        "## Recognition Profile",
        "\n".join([
            f"- Role family: {recognition_profile.get('role_family')}.",
            f"- Martial or guarded: {recognition_profile.get('martial_or_guarded')}.",
            f"- Ritual or sacred: {recognition_profile.get('ritual_or_sacred')}.",
            f"- Social or diplomatic: {recognition_profile.get('social_or_diplomatic')}.",
            f"- Travel or fieldwork: {recognition_profile.get('travel_or_fieldwork')}.",
            f"- Triage keywords: {', '.join(recognition_profile.get('triage_keywords') or [])}.",
        ]),
        "## Allowed Identity Labels",
        "\n".join(f"- {label}" for label in [profession_id, role_label] if str(label).strip()),
    ]
    if appearance:
        content_parts.extend(["## Appearance Cues", appearance])
    if clothing:
        content_parts.extend(["## Clothing and Silhouette", clothing])
    if weapons or gear:
        tool_lines = []
        if weapons:
            tool_lines.append(f"- Common weapons: {', '.join(weapons)}.")
        if gear:
            tool_lines.append(f"- Common gear: {', '.join(gear)}.")
        content_parts.extend(["## Tools and Equipment", "\n".join(tool_lines)])
    if poses:
        content_parts.extend(["## Pose and Behavior Cues", "\n".join(f"- {line}" for line in poses)])
    if disambiguation_rules:
        content_parts.extend(["## Disambiguation Rules", "\n".join(f"- {line}" for line in disambiguation_rules)])
    if culture_hints:
        content_parts.extend(["## Culture and Area Hints", "\n".join(f"- {line}" for line in culture_hints[:8])])
    if doctrine_hints:
        content_parts.extend(["## Doctrine and Belief Hints", "\n".join(f"- {line}" for line in doctrine_hints[:8])])
    if creative_scaffolds:
        content_parts.extend(["## Creative Scaffolds", "\n".join(f"- {line}" for line in creative_scaffolds[:8])])
    if lore_sections:
        content_parts.extend(["## Lore Snippets", "\n\n".join(lore_sections)])

    settings = normalize_settings_values(default_settings or [])
    item = {
        "type": "lore",
        "title": f"AI Lore: Role {role_label.title()}",
        "slug": f"ai_lore_role_{_safe_slug(profession_id)}",
        "source": "ai_lore",
        "source_path": f"ai_lore/roles/{_safe_slug(profession_id)}",
        "excerpt": f"AI guide for the {role_label} role in Lands of Legends.",
        "description": f"AI guide for the {role_label} role in Lands of Legends.",
        "categories": ["ai_lore", "role", "profession_guide"],
        "settings": settings,
        "setting": settings[0] if settings else "",
        "ai_lore_kind": "role",
        "profession": profession_id,
        "recognition_profile": recognition_profile,
        "disambiguation_rules": disambiguation_rules,
        "allowed_identity_labels": [profession_id, role_label],
        "terms": sorted({
            _safe_slug(profession_id),
            _safe_slug(role_label),
            *(_safe_slug(title) for title in source_titles),
            *(_safe_slug(x) for x in weapons),
            *(_safe_slug(x) for x in gear),
        }),
        "related_lore_slugs": [str(item.get("slug") or "").strip() for item in lore_matches if str(item.get("slug") or "").strip()],
        "content_markdown": "\n\n".join(part for part in content_parts if str(part).strip()),
    }
    return _normalize_lore_item(item, default_settings=default_settings)


def _build_ai_creature_category_items(
    lore_dir: Path,
    *,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    sands = _load_full_lore_by_slug(lore_dir, "the_sands", default_settings=default_settings)
    world_seed = _load_full_lore_by_slug(lore_dir, "world_seed", default_settings=default_settings)
    body = "\n\n".join([
        str(sands.get("content_markdown") or ""),
        str(world_seed.get("content_markdown") or ""),
    ]).strip()
    if not body:
        return []

    guides: list[dict[str, Any]] = []
    category_specs = [
        {
            "name": "Gorothim",
            "slug": "gorothim",
            "description": "Daelgast-born horrors: mutated, half-formed, non-playable creature categories rather than races.",
            "recognition": [
                "Not a playable race.",
                "Creature category tied to Daelgast corruption and the Sands.",
                "Look for warped flesh, unstable magic, fractured natural law, and incomplete anatomy or identity.",
            ],
            "rules": [
                "Treat Gorothim as horror or monster categories, not peoples with stable culture or lineage.",
                "Do not present Gorothim as a playable ancestry unless you explicitly create an exceptional one-off corruption story.",
                "Use Daelgast contamination, incompletion, and mutation instead of generic demon or beastfolk logic.",
            ],
            "terms": ["gorothim", "horror", "daelgast_horror", "mutated_beast", "half_formed_entity"],
        },
        {
            "name": "Gurthim",
            "slug": "gurthim",
            "description": "Daelgast-touched undead: restless dead and non-playable creature categories rather than races.",
            "recognition": [
                "Not a playable race.",
                "Creature category tied to failed death, lingering identity, and Daelgast mismatch.",
                "Look for restless dead, echo-behavior, partial memory, and unfinished release rather than necromancer control.",
            ],
            "rules": [
                "Treat Gurthim as undead creature categories, not peoples or lineages.",
                "Do not explain them with standard necromancy first; start from failed release and Daelgast contamination.",
                "Preserve the idea that ending a Gurthim often interrupts a process rather than slaying a conventional enemy.",
            ],
            "terms": ["gurthim", "undead", "restless_dead", "daelgast_undead", "failed_death"],
        },
    ]

    for spec in category_specs:
        content = "\n\n".join([
            f"# AI Lore: {spec['name']}",
            "## Recognition Profile",
            "\n".join(f"- {line}" for line in spec["recognition"]),
            "## Allowed Identity Labels",
            "\n".join(f"- {label}" for label in [spec["slug"], *spec["terms"]]),
            "## Disambiguation Rules",
            "\n".join(f"- {line}" for line in spec["rules"]),
            "## Source Lore",
            _trim_markdown_excerpt(body, max_chars=2200),
        ])
        guides.append(_normalize_lore_item({
            "type": "lore",
            "title": f"AI Lore: {spec['name']}",
            "slug": f"ai_lore_identity_{spec['slug']}",
            "source": "ai_lore",
            "source_path": f"ai_lore/identity/{spec['slug']}",
            "excerpt": spec["description"],
            "description": spec["description"],
            "categories": ["ai_lore", "race", "creature_category", "non_playable"],
            "settings": normalize_settings_values(default_settings or []),
            "setting": normalize_settings_values(default_settings or [])[0] if normalize_settings_values(default_settings or []) else "",
            "ai_lore_kind": "race",
            "recognition_profile": {
                "entity_class": "creature_category",
                "playable_race": "no",
                "daelgast_linked": "yes",
                "triage_keywords": spec["terms"],
            },
            "disambiguation_rules": spec["rules"],
            "allowed_identity_labels": [spec["slug"], *spec["terms"]],
            "related_lore_slugs": ["the_sands", "world_seed"],
            "terms": spec["terms"],
            "content_markdown": content,
        }, default_settings=default_settings))
    return guides


def _build_ai_race_lore_item(
    lore_dir: Path,
    *,
    config: dict[str, Any],
    names_cfg: dict[str, Any],
    race_id: str,
    race_cfg: dict[str, Any],
    default_settings: list[str] | None = None,
) -> dict[str, Any]:
    race_label = str(race_cfg.get("name") or race_id).strip() or race_id
    lore_matches = _matching_lore_entries_for_race(
        lore_dir,
        race_id=race_id,
        race_cfg=race_cfg,
        default_settings=default_settings,
    )
    core_truths = [str(x).strip() for x in (race_cfg.get("core_truths") or []) if str(x).strip()]
    themes = [str(x).strip() for x in (race_cfg.get("themes") or []) if str(x).strip()]
    tone = [str(x).strip() for x in (race_cfg.get("tone") or []) if str(x).strip()]
    avoid = [str(x).strip() for x in (race_cfg.get("avoid") or []) if str(x).strip()]
    visual_defaults = race_cfg.get("visual_defaults") if isinstance(race_cfg.get("visual_defaults"), dict) else {}
    signature_features = [str(x).strip() for x in (visual_defaults.get("signature_features") or []) if str(x).strip()]
    clothing = _clean_text_block(visual_defaults.get("clothing"))
    culture_tokens = {_safe_slug(race_id)}
    variants_obj = race_cfg.get("variants") if isinstance(race_cfg.get("variants"), dict) else {}
    culture_tokens.update(_safe_slug(key) for key in variants_obj.keys())
    geography = _matching_area_names_for_cultures(config, culture_tokens)
    first_names, surnames = _extract_name_examples(names_cfg, race_id)
    recognition_profile = _infer_recognition_profile(race_id, race_cfg, variants_obj)
    disambiguation_rules = _build_disambiguation_rules(race_id, race_cfg, variants_obj)

    variant_lines: list[str] = []
    allowed_identity_labels = [race_id]
    for variant_id, variant_cfg_raw in variants_obj.items():
        variant_cfg = variant_cfg_raw if isinstance(variant_cfg_raw, dict) else {}
        allowed_identity_labels.append(str(variant_id).strip())
        appearance = [str(x).strip() for x in (variant_cfg.get("appearance") or []) if str(x).strip()]
        variant_tone = _clean_text_block(variant_cfg.get("tone"))
        variant_first, variant_surnames = _extract_name_examples(names_cfg, race_id, str(variant_id))
        parts: list[str] = []
        if appearance:
            parts.append(f"visual cues: {', '.join(appearance)}")
        if variant_tone:
            parts.append(f"flavor: {variant_tone}")
        if variant_first:
            parts.append(f"first names: {', '.join(variant_first)}")
        if variant_surnames:
            parts.append(f"name tails: {', '.join(variant_surnames)}")
        if parts:
            variant_lines.append(f"- {str(variant_cfg.get('label') or variant_id).strip()}: {'; '.join(parts)}.")

    lore_sections: list[str] = []
    source_titles: list[str] = []
    for item in lore_matches:
        slug = str(item.get("slug") or "").strip()
        full_item = item
        if slug:
            try:
                loaded = load_lore_item(lore_dir, slug, default_settings=default_settings)
                if isinstance(loaded, dict):
                    full_item = loaded
            except Exception:
                full_item = item
        title = str(full_item.get("title") or slug or "Lore").strip()
        body = _trim_markdown_excerpt(str(full_item.get("content_markdown") or full_item.get("description") or "").strip(), max_chars=900)
        if title:
            source_titles.append(title)
        if body:
            lore_sections.append(f"### {title}\n{body}")

    description_bits: list[str] = []
    if signature_features:
        description_bits.append(f"Visual recognition cues: {', '.join(signature_features[:4])}.")
    if themes:
        description_bits.append(f"Flavor themes: {', '.join(themes[:4])}.")
    if geography:
        description_bits.append(f"Common homelands or strong ties: {', '.join(geography[:4])}.")
    description = " ".join(description_bits).strip() or f"AI-friendly race guide for {race_label}."

    content_parts = [
        f"# AI Lore: {race_label}",
        "## Recognition Profile",
        "\n".join([
            f"- Humanoid: {recognition_profile.get('humanoid')}.",
            f"- Size: {recognition_profile.get('size')}.",
            f"- Pointed ears: {recognition_profile.get('pointed_ears')}.",
            f"- Animal traits: {recognition_profile.get('animal_traits')}.",
            f"- Wings: {recognition_profile.get('wings')}.",
            f"- Horns: {recognition_profile.get('horns')}.",
            f"- Tusks: {recognition_profile.get('tusks')}.",
            f"- Skin palette: {recognition_profile.get('skin_palette')}.",
            f"- Triage keywords: {', '.join(recognition_profile.get('triage_keywords') or [])}.",
        ]),
        "## Recognition Clues",
        "\n".join(f"- {line}" for line in signature_features) if signature_features else "- No specific visual defaults recorded yet.",
    ]
    content_parts.extend([
        "## Allowed Identity Labels",
        "\n".join(f"- {label}" for label in allowed_identity_labels if str(label).strip()),
    ])
    if clothing:
        content_parts.extend(["## Clothing and Silhouette", clothing])
    if disambiguation_rules:
        content_parts.extend(["## Disambiguation Rules", "\n".join(f"- {line}" for line in disambiguation_rules)])
    if core_truths:
        content_parts.extend(["## Core Truths", "\n".join(f"- {line}" for line in core_truths)])
    if themes or tone:
        identity_lines: list[str] = []
        if themes:
            identity_lines.append(f"- Themes: {', '.join(themes)}.")
        if tone:
            identity_lines.append(f"- Tone: {', '.join(tone)}.")
        content_parts.extend(["## Flavor and Tone", "\n".join(identity_lines)])
    if geography:
        content_parts.extend(["## Geography and Cultural Ties", "\n".join(f"- {line}" for line in geography)])
    naming_lines: list[str] = []
    if first_names:
        naming_lines.append(f"- First names: {', '.join(first_names)}.")
    if surnames:
        naming_lines.append(f"- Surnames, clan names, or epithets: {', '.join(surnames)}.")
    if naming_lines:
        content_parts.extend(["## Naming Cues", "\n".join(naming_lines)])
    if variant_lines:
        content_parts.extend(["## Variant Recognition", "\n".join(variant_lines)])
    if avoid:
        content_parts.extend(["## Avoid When Generating", "\n".join(f"- {line}" for line in avoid)])
    if lore_sections:
        content_parts.extend(["## Lore Snippets", "\n\n".join(lore_sections)])

    settings = normalize_settings_values(race_cfg.get("settings"))
    if not settings:
        settings = normalize_settings_values(default_settings or [])
    item = {
        "type": "lore",
        "title": f"AI Lore: {race_label}",
        "slug": f"ai_lore_race_{_safe_slug(race_id)}",
        "source": "ai_lore",
        "source_path": f"ai_lore/races/{_safe_slug(race_id)}",
        "excerpt": description,
        "description": description,
        "categories": ["ai_lore", "race", "identity_guide"],
        "settings": settings,
        "setting": settings[0] if settings else "",
        "ai_lore_kind": "race",
        "race": race_id,
        "recognition_profile": recognition_profile,
        "disambiguation_rules": disambiguation_rules,
        "allowed_identity_labels": allowed_identity_labels,
        "terms": sorted(
            {
                _safe_slug(race_id),
                _safe_slug(race_cfg.get("name")),
                *(_safe_slug(key) for key in variants_obj.keys()),
                *(_safe_slug(title) for title in source_titles),
            }
        ),
        "related_lore_slugs": [str(item.get("slug") or "").strip() for item in lore_matches if str(item.get("slug") or "").strip()],
        "content_markdown": "\n\n".join(part for part in content_parts if str(part).strip()),
    }
    return _normalize_lore_item(item, default_settings=default_settings)


def list_ai_lore_items(
    lore_dir: Path,
    *,
    config_dir: Path,
    setting: str | None = None,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    active_setting = _active_ai_lore_setting(setting=setting, default_settings=default_settings)
    if not active_setting:
        return []
    try:
        config = load_config_dir(config_dir, setting_id=active_setting)
    except Exception:
        return []
    races_obj = config.get("races") if isinstance(config.get("races"), dict) else {}
    areas_obj = config.get("areas") if isinstance(config.get("areas"), dict) else {}
    professions_obj = config.get("professions") if isinstance(config.get("professions"), dict) else {}
    names_cfg = config.get("names") if isinstance(config.get("names"), dict) else {}
    items: list[dict[str, Any]] = []
    for race_id, race_cfg_raw in races_obj.items():
        if not isinstance(race_cfg_raw, dict):
            continue
        race_id_str = str(race_id or "").strip()
        if not race_id_str:
            continue
        items.append(
            _build_ai_race_lore_item(
                lore_dir,
                config=config,
                names_cfg=names_cfg,
                race_id=race_id_str,
                race_cfg=race_cfg_raw,
                default_settings=normalize_settings_values([active_setting, *(default_settings or [])]),
            )
        )
    items.extend(
        _build_ai_creature_category_items(
            lore_dir,
            default_settings=normalize_settings_values([active_setting, *(default_settings or [])]),
        )
    )
    for area_id, area_cfg_raw in areas_obj.items():
        if not isinstance(area_cfg_raw, dict):
            continue
        area_id_str = str(area_id or "").strip()
        if not area_id_str:
            continue
        items.append(
            _build_ai_area_lore_item(
                lore_dir,
                area_id=area_id_str,
                area_cfg=area_cfg_raw,
                default_settings=normalize_settings_values([active_setting, *(default_settings or [])]),
            )
        )
    items.extend(
        _build_ai_doctrine_lore_items(
            lore_dir,
            default_settings=normalize_settings_values([active_setting, *(default_settings or [])]),
        )
    )
    for profession_id, profession_cfg_raw in professions_obj.items():
        if not isinstance(profession_cfg_raw, dict):
            continue
        profession_id_str = str(profession_id or "").strip()
        if not profession_id_str:
            continue
        items.append(
            _build_ai_profession_lore_item(
                lore_dir,
                config=config,
                profession_id=profession_id_str,
                profession_cfg=profession_cfg_raw,
                default_settings=normalize_settings_values([active_setting, *(default_settings or [])]),
            )
        )
    return items


def search_ai_lore(
    lore_dir: Path,
    query: str | None = None,
    *,
    config_dir: Path,
    setting: str | None = None,
    location: str | None = None,
    default_settings: list[str] | None = None,
) -> list[dict[str, Any]]:
    query_lc = _safe_slug(query)
    location_lc = _safe_slug(location)
    results: list[tuple[int, dict[str, Any]]] = []
    for item in list_ai_lore_items(
        lore_dir,
        config_dir=config_dir,
        setting=setting,
        default_settings=default_settings,
    ):
        if not isinstance(item, dict):
            continue
        hay = " ".join([
            str(item.get("title") or ""),
            str(item.get("description") or ""),
            str(item.get("excerpt") or ""),
            str(item.get("content_markdown") or ""),
            " ".join(item.get("categories", []) or []),
            " ".join(item.get("terms", []) or []),
        ])
        hay_slug = _safe_slug(hay)
        if location_lc and location_lc not in hay_slug:
            continue
        if not query_lc:
            results.append((1, item))
            continue
        score = 0
        for token in [tok for tok in query_lc.split("_") if tok]:
            if token in hay_slug:
                score += 3 if token in _safe_slug(item.get("title")) else 1
        if query_lc and query_lc in hay_slug:
            score += 5
        if score > 0:
            results.append((score, item))
    results.sort(key=lambda row: row[0], reverse=True)
    return [item for _, item in results]


def _index_path(lore_dir: Path) -> Path:
    return lore_dir / "index.json"


def _entries_dir(lore_dir: Path) -> Path:
    return lore_dir / "entries"


def _trash_entries_dir(lore_dir: Path) -> Path:
    return lore_dir / ".trash" / "entries"


def _slugify(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_")


def _load_index(lore_dir: Path) -> dict[str, Any]:
    path = _index_path(lore_dir)
    if not path.exists():
        return {"count": 0, "items": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {"count": 0, "items": []}
    items = data.get("items")
    if not isinstance(items, list):
        data["items"] = []
    return data


def _write_index(lore_dir: Path, data: dict[str, Any]) -> None:
    items = [item for item in (data.get("items") or []) if isinstance(item, dict)]
    data = dict(data)
    data["items"] = items
    data["count"] = len(items)
    _index_path(lore_dir).write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _index_item_from_entry(entry: dict[str, Any]) -> dict[str, Any]:
    categories = _normalized_categories(entry.get("categories"))
    settings = normalize_settings_values(entry.get("settings"))
    if not settings:
        settings = normalize_settings_values(entry.get("setting"))
    area = str(entry.get("area") or entry.get("environment") or "").strip()
    location = str(entry.get("location") or entry.get("title") or "").strip()
    location_type = str(entry.get("location_type") or _pick_location_type(categories) or "").strip()
    return {
        "title": str(entry.get("title") or "Untitled"),
        "slug": str(entry.get("slug") or ""),
        "source_path": str(entry.get("source_path") or ""),
        "description": str(entry.get("description") or entry.get("excerpt") or ""),
        "excerpt": str(entry.get("excerpt") or entry.get("description") or ""),
        "categories": [str(x) for x in categories if str(x).strip()],
        "mentions_total": int(entry.get("mentions_total") or 0),
        "settings": settings,
        "setting": settings[0] if settings else "",
        "area": area,
        "environment": area,
        "location": location,
        "location_type": location_type,
        "images": _normalize_image_refs(entry.get("images")),
    }


def _upsert_index_item(lore_dir: Path, entry: dict[str, Any]) -> None:
    index_data = _load_index(lore_dir)
    items = [item for item in (index_data.get("items") or []) if isinstance(item, dict)]
    slug = str(entry.get("slug") or "").strip()
    if not slug:
        raise ValueError("lore entry slug is required")
    summary = _index_item_from_entry(entry)
    replaced = False
    next_items: list[dict[str, Any]] = []
    for item in items:
        if str(item.get("slug") or "").strip() == slug:
            next_items.append(summary)
            replaced = True
        else:
            next_items.append(item)
    if not replaced:
        next_items.append(summary)
    index_data["items"] = next_items
    _write_index(lore_dir, index_data)


def _remove_index_slug(lore_dir: Path, slug: str) -> None:
    index_data = _load_index(lore_dir)
    items = [item for item in (index_data.get("items") or []) if isinstance(item, dict)]
    keep = [item for item in items if str(item.get("slug") or "").strip() != slug]
    index_data["items"] = keep
    _write_index(lore_dir, index_data)


def update_lore_item(lore_dir: Path, slug: str, item: dict[str, Any]) -> dict[str, Any]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise ValueError("invalid lore slug")
    path = _entries_dir(lore_dir) / f"{slug_clean}.json"
    if not path.exists():
        raise FileNotFoundError(f"No lore entry named '{slug_clean}'")

    payload = dict(item)
    payload["slug"] = slug_clean
    payload.setdefault("type", "lore")
    payload.setdefault("title", "Untitled")
    payload.setdefault("source", "local")
    payload.setdefault("schema_version", LORE_ENTRY_SCHEMA_VERSION)
    categories = _normalized_categories(payload.get("categories"))
    if categories:
        payload["categories"] = categories

    area = str(payload.get("area") or payload.get("environment") or "").strip()
    if _is_location_entry(categories) or str(payload.get("location") or "").strip():
        if not area:
            raise ValueError("location entries require area")
        payload["area"] = area
        payload["environment"] = area
        payload["location"] = str(payload.get("location") or payload.get("title") or "Unnamed Location").strip()
        location_type = str(payload.get("location_type") or _pick_location_type(categories)).strip()
        if location_type:
            payload["location_type"] = location_type
        if "location" not in categories:
            payload["categories"] = sorted(set(categories + ["location"]))
    settings = normalize_settings_values(payload.get("settings"))
    if settings:
        payload["settings"] = settings
        payload["setting"] = payload.get("setting") or settings[0]
    payload["images"] = _normalize_image_refs(payload.get("images"))

    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    _upsert_index_item(lore_dir, payload)
    return payload


def list_trashed_lore_items(lore_dir: Path) -> list[dict[str, Any]]:
    root = _trash_entries_dir(lore_dir)
    if not root.exists():
        return []
    items: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), reverse=True):
        slug = path.stem
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            items.append({
                "slug": slug,
                "title": data.get("title"),
                "source_path": data.get("source_path"),
            })
        except Exception:
            items.append({"slug": slug, "title": slug, "source_path": ""})
    return items


def load_trashed_lore_item(lore_dir: Path, slug: str) -> dict[str, Any]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise FileNotFoundError(f"No trashed lore entry named '{slug}'")
    path = _trash_entries_dir(lore_dir) / f"{slug_clean}.json"
    if not path.exists():
        raise FileNotFoundError(f"No trashed lore entry named '{slug_clean}'")
    return json.loads(path.read_text(encoding="utf-8"))


def trash_lore_item(lore_dir: Path, slug: str) -> dict[str, str]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise FileNotFoundError(f"No lore entry named '{slug}'")
    source = _entries_dir(lore_dir) / f"{slug_clean}.json"
    if not source.exists():
        raise FileNotFoundError(f"No lore entry named '{slug_clean}'")
    trash_dir = _trash_entries_dir(lore_dir)
    trash_dir.mkdir(parents=True, exist_ok=True)
    target = trash_dir / f"{slug_clean}.json"
    source.rename(target)
    _remove_index_slug(lore_dir, slug_clean)
    return {"slug": slug_clean}


def restore_trashed_lore_item(lore_dir: Path, slug: str) -> dict[str, str]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise FileNotFoundError(f"No trashed lore entry named '{slug}'")
    source = _trash_entries_dir(lore_dir) / f"{slug_clean}.json"
    if not source.exists():
        raise FileNotFoundError(f"No trashed lore entry named '{slug_clean}'")
    entries_dir = _entries_dir(lore_dir)
    entries_dir.mkdir(parents=True, exist_ok=True)
    target = entries_dir / f"{slug_clean}.json"
    source.rename(target)
    data = json.loads(target.read_text(encoding="utf-8"))
    data["slug"] = slug_clean
    _upsert_index_item(lore_dir, data)
    return {"slug": slug_clean}


def expunge_trashed_lore_item(lore_dir: Path, slug: str) -> dict[str, str]:
    slug_clean = _slugify(slug)
    if not slug_clean:
        raise FileNotFoundError(f"No trashed lore entry named '{slug}'")
    target = _trash_entries_dir(lore_dir) / f"{slug_clean}.json"
    if not target.exists():
        raise FileNotFoundError(f"No trashed lore entry named '{slug_clean}'")
    target.unlink()
    return {"slug": slug_clean}
