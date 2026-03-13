from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any


def _plain_to_html(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines()]
    chunks = [line for line in lines if line]
    if not chunks:
        return ""
    return "".join(f"<p>{line}</p>" for line in chunks)


def _ms_now() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _new_actor_id() -> str:
    return uuid.uuid4().hex[:16]


def _new_item_id() -> str:
    return uuid.uuid4().hex[:16]


def _pick_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _extract_level_text(*values: Any) -> str:
    text = _pick_text(*values)
    if not text:
        return "1"
    match = re.search(r"\d+(?:\s*\+\s*\d+)?|1d\d+(?:\s*\+\s*\d+)?", text, flags=re.IGNORECASE)
    if match:
        return match.group(0).replace(" ", "")
    return text


def _skill_rating_label(level: str) -> str:
    key = str(level or "").strip().lower()
    mapping = {
        "inability": "Inability",
        "practiced": "Practiced",
        "trained": "Trained",
        "expert": "Specialized",
    }
    return mapping.get(key, "Trained")


def _parse_tagged_equipment_line(line: str) -> tuple[str, dict[str, Any]]:
    text = str(line or "").strip()
    if text.startswith("[Cypher]"):
        name = text.replace("[Cypher]", "", 1).strip()
        level_match = re.search(r"\(L(\d+)\)\s*$", name)
        level = int(level_match.group(1)) if level_match else 1
        if level_match:
            name = name[: level_match.start()].strip()
        return (
            "cypher",
            {
                "name": name or "Cypher",
                "system": {
                    "version": 2,
                    "description": "",
                    "basic": {"level": level, "type": [2, 1], "identified": True},
                },
            },
        )
    if text.startswith("[Artifact]"):
        name = text.replace("[Artifact]", "", 1).strip()
        level_match = re.search(r"L(\d+)", name)
        dep_match = re.search(r"depletion ([^)]+)", name, flags=re.IGNORECASE)
        level = level_match.group(1) if level_match else "1"
        depletion = dep_match.group(1).strip() if dep_match else ""
        name = re.sub(r"\(([^)]*)\)\s*$", "", name).strip()
        return (
            "artifact",
            {
                "name": name or "Artifact",
                "system": {
                    "version": 2,
                    "description": "",
                    "basic": {"level": level, "depletion": depletion, "identified": True},
                },
            },
        )
    return (
        "equipment",
        {
            "name": text or "Equipment",
            "system": {
                "version": 2,
                "description": "",
                "basic": {"quantity": 1},
            },
        },
    )


def character_sheet_result_to_foundry_actor(result: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    sheet = result.get("sheet") if isinstance(result.get("sheet"), dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    sheet_meta = sheet.get("metadata") if isinstance(sheet.get("metadata"), dict) else {}
    pools = sheet.get("pools") if isinstance(sheet.get("pools"), dict) else {}
    max_pools = pools.get("max") if isinstance(pools.get("max"), dict) else {}
    current_pools = pools.get("current") if isinstance(pools.get("current"), dict) else {}
    edges = sheet.get("edges") if isinstance(sheet.get("edges"), dict) else {}
    recovery = sheet.get("recovery_rolls_used") if isinstance(sheet.get("recovery_rolls_used"), dict) else {}

    name = str(sheet.get("name") or result.get("name") or "Imported Character").strip() or "Imported Character"
    actor = {
        "name": name,
        "type": "pc",
        "img": "icons/svg/mystery-man.svg",
        "system": {
            "version": 4,
            "basic": {
                "descriptor": str(sheet.get("descriptor") or ""),
                "type": str(sheet.get("type") or ""),
                "focus": str(sheet.get("focus") or ""),
                "additionalSentence": "",
                "tier": int(sheet_meta.get("tier") or metadata.get("tier") or 1),
                "effort": int(sheet.get("effort") or 1),
                "xp": int(sheet_meta.get("xp") or metadata.get("xp") or 0),
                "altXp": 0,
            },
            "pools": {
                "might": {
                    "value": int(current_pools.get("might") or 0),
                    "max": int(max_pools.get("might") or 0),
                    "edge": int(edges.get("might") or 0),
                },
                "speed": {
                    "value": int(current_pools.get("speed") or 0),
                    "max": int(max_pools.get("speed") or 0),
                    "edge": int(edges.get("speed") or 0),
                },
                "intellect": {
                    "value": int(current_pools.get("intellect") or 0),
                    "max": int(max_pools.get("intellect") or 0),
                    "edge": int(edges.get("intellect") or 0),
                },
            },
            "combat": {
                "recoveries": {
                    "roll": "1d6",
                    "oneAction": bool(recovery.get("action")),
                    "tenMinutes": bool(recovery.get("ten_minutes")),
                    "oneHour": bool(recovery.get("one_hour")),
                    "tenHours": bool(recovery.get("ten_hours")),
                },
                "damageTrack": {
                    "state": str(sheet.get("damage_track") or "Hale"),
                    "applyImpaired": True,
                    "applyDebilitated": True,
                },
                "armor": {"ratingTotal": 0, "costTotal": 0},
            },
            "equipment": {
                "cypherLimit": str(sheet.get("cypher_limit") or 2),
            },
            "notes": str(sheet.get("notes") or ""),
            "description": str(sheet.get("sentence") or ""),
        },
        "items": [],
        "effects": [],
        "_stats": {
            "compendiumSource": None,
            "duplicateSource": None,
            "exportSource": {
                "worldId": "lands-of-legend",
                "uuid": f"Actor.{_new_actor_id()}",
                "coreVersion": "13.351",
                "systemId": "cyphersystem",
                "systemVersion": "3.4.3",
            },
            "coreVersion": "13.351",
            "systemId": "cyphersystem",
            "systemVersion": "3.4.3",
            "createdTime": _ms_now(),
            "modifiedTime": _ms_now(),
        },
        "ownership": {"default": 0},
    }

    for ability in sheet.get("chosen_abilities") or []:
        name = str(ability or "").strip()
        if not name:
            continue
        actor["items"].append({
            "name": name,
            "type": "ability",
            "img": "systems/cyphersystem/icons/items/ability.svg",
            "system": {
                "version": 2,
                "description": "",
                "basic": {"cost": "0", "pool": "Pool"},
            },
            "effects": [],
        })

    skill_rows: list[tuple[str, str]] = []
    descriptor_effects = sheet.get("descriptor_effects") if isinstance(sheet.get("descriptor_effects"), dict) else {}
    for skill_name in descriptor_effects.get("skills") or []:
        s = str(skill_name or "").strip()
        if s:
            skill_rows.append((s, "trained"))
    for skill_name in descriptor_effects.get("inabilities") or []:
        s = str(skill_name or "").strip()
        if s:
            skill_rows.append((s, "inability"))
    for entry in sheet.get("chosen_skills") or []:
        if not isinstance(entry, dict):
            continue
        s = str(entry.get("name") or "").strip()
        if not s:
            continue
        lvl = str(entry.get("level") or "trained").strip().lower()
        skill_rows.append((s, lvl))

    seen = set()
    for skill_name, level in skill_rows:
        key = (skill_name.lower(), level)
        if key in seen:
            continue
        seen.add(key)
        actor["items"].append({
            "name": skill_name,
            "type": "skill",
            "img": "systems/cyphersystem/icons/items/skill.svg",
            "system": {
                "version": 2,
                "description": "",
                "basic": {"rating": _skill_rating_label(level)},
            },
            "effects": [],
        })

    for attack in sheet.get("attacks") or []:
        if not isinstance(attack, dict):
            continue
        attack_name = str(attack.get("name") or "").strip()
        if not attack_name:
            continue
        actor["items"].append({
            "name": attack_name,
            "type": "attack",
            "img": "systems/cyphersystem/icons/items/attack.svg",
            "system": {
                "version": 2,
                "description": str(attack.get("description") or ""),
                "basic": {
                    "type": str(attack.get("weapon_type") or "attack"),
                    "damage": attack.get("damage") or 0,
                    "range": str(attack.get("range") or "immediate"),
                    "skillRating": str(attack.get("skill_rating") or "Practiced"),
                },
            },
            "effects": [],
        })

    for cypher in sheet.get("cyphers") or []:
        if not isinstance(cypher, dict):
            continue
        cypher_name = str(cypher.get("name") or "").strip()
        if not cypher_name:
            continue
        actor["items"].append({
            "name": cypher_name,
            "type": "cypher",
            "img": "systems/cyphersystem/icons/items/cypher.svg",
            "system": {
                "version": 2,
                "description": str(cypher.get("description") or ""),
                "basic": {
                    "level": cypher.get("level") if cypher.get("level") not in (None, "") else 1,
                    "type": [2, 1],
                    "identified": True,
                },
            },
            "effects": [],
        })

    for artifact in sheet.get("artifacts") or []:
        if not isinstance(artifact, dict):
            continue
        artifact_name = str(artifact.get("name") or "").strip()
        if not artifact_name:
            continue
        actor["items"].append({
            "name": artifact_name,
            "type": "artifact",
            "img": "systems/cyphersystem/icons/items/artifact.svg",
            "system": {
                "version": 2,
                "description": str(artifact.get("description") or ""),
                "basic": {
                    "level": str(artifact.get("level") or "1"),
                    "depletion": str(artifact.get("depletion") or ""),
                    "identified": True,
                },
            },
            "effects": [],
        })

    for line in sheet.get("equipment") or []:
        item_type, data = _parse_tagged_equipment_line(str(line or ""))
        actor["items"].append({
            "name": data["name"],
            "type": item_type,
            "img": f"systems/cyphersystem/icons/items/{item_type}.svg",
            "system": data.get("system") or {"version": 2},
            "effects": [],
        })

    return actor


def npc_or_creature_result_to_foundry_actor(result: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    stat = result.get("stat_block") if isinstance(result.get("stat_block"), dict) else {}
    notes = str(result.get("text") or "")
    name = str(result.get("name") or "Imported Actor").strip() or "Imported Actor"
    level = int(stat.get("level") or 1)
    health = int(stat.get("health") or max(3, level * 3))
    armor = int(stat.get("armor") or 0)
    damage = int(stat.get("damage") or 0)

    actor = {
        "name": name,
        "type": "npc",
        "img": "icons/svg/mystery-man.svg",
        "system": {
            "version": 4,
            "basic": {"level": level},
            "pools": {"health": {"value": health, "max": health}},
            "combat": {"damage": damage, "armor": armor},
            "description": _plain_to_html(str((result.get("sections") or {}).get("character") or "")),
            "notes": _plain_to_html(notes),
        },
        "items": [],
        "effects": [],
        "_stats": {
            "compendiumSource": None,
            "duplicateSource": None,
            "exportSource": {
                "worldId": "lands-of-legend",
                "uuid": f"Actor.{_new_actor_id()}",
                "coreVersion": "13.351",
                "systemId": "cyphersystem",
                "systemVersion": "3.4.3",
            },
            "coreVersion": "13.351",
            "systemId": "cyphersystem",
            "systemVersion": "3.4.3",
            "createdTime": _ms_now(),
            "modifiedTime": _ms_now(),
        },
        "ownership": {"default": 0},
    }

    for line in stat.get("combat") or []:
        text = str(line or "").strip()
        if not text:
            continue
        actor["items"].append({
            "name": text,
            "type": "attack",
            "img": "systems/cyphersystem/icons/items/attack.svg",
            "system": {
                "version": 2,
                "description": "",
                "basic": {"type": "natural attack", "damage": damage},
            },
            "effects": [],
        })
    for line in stat.get("loot") or []:
        text = str(line or "").strip()
        if not text:
            continue
        actor["items"].append({
            "name": text,
            "type": "equipment",
            "img": "systems/cyphersystem/icons/items/equipment.svg",
            "system": {"version": 2, "description": "", "basic": {"quantity": 1}},
            "effects": [],
        })

    return actor


def cypher_result_to_foundry_item(result: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = payload or {}
    sections = result.get("sections") if isinstance(result.get("sections"), dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    name = str(result.get("name") or "Imported Cypher").strip() or "Imported Cypher"
    level = _extract_level_text(
        result.get("level"),
        sections.get("level"),
        metadata.get("level"),
    )
    form = _pick_text(
        sections.get("form"),
        sections.get("manifestation"),
        sections.get("appearance"),
        result.get("manifestation"),
        result.get("appearance"),
    )
    effect = _pick_text(
        sections.get("effect"),
        result.get("description"),
        result.get("text"),
    )
    description = effect
    if form:
        description = f"Form: {form}\n\nEffect: {effect or ''}".strip()

    return {
        "name": name,
        "type": "cypher",
        "img": "systems/cyphersystem/icons/items/cypher.svg",
        "system": {
            "version": 2,
            "description": description,
            "basic": {
                "level": level or "1",
                "type": [2, 1],
                "identified": True,
            },
        },
        "effects": [],
        "_stats": {
            "compendiumSource": None,
            "duplicateSource": None,
            "exportSource": {
                "worldId": "lands-of-legend",
                "uuid": f"Item.{_new_item_id()}",
                "coreVersion": "13.351",
                "systemId": "cyphersystem",
                "systemVersion": "3.4.3",
            },
            "coreVersion": "13.351",
            "systemId": "cyphersystem",
            "systemVersion": "3.4.3",
            "createdTime": _ms_now(),
            "modifiedTime": _ms_now(),
        },
    }


def artifact_result_to_foundry_item(result: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    _ = payload or {}
    sections = result.get("sections") if isinstance(result.get("sections"), dict) else {}
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}
    name = str(result.get("name") or "Imported Artifact").strip() or "Imported Artifact"
    level = _extract_level_text(
        result.get("level"),
        sections.get("level"),
        metadata.get("level"),
    )
    depletion = _pick_text(
        result.get("depletion"),
        sections.get("depletion"),
        metadata.get("depletion"),
    )
    form = _pick_text(
        sections.get("form"),
        sections.get("manifestation"),
        sections.get("appearance"),
        result.get("manifestation"),
        result.get("appearance"),
    )
    effect = _pick_text(
        sections.get("effect"),
        result.get("description"),
        result.get("text"),
    )
    description_bits: list[str] = []
    if form:
        description_bits.append(f"Form: {form}")
    if effect:
        description_bits.append(f"Effect: {effect}")
    description = "\n\n".join(description_bits).strip()

    return {
        "name": name,
        "type": "artifact",
        "img": "systems/cyphersystem/icons/items/artifact.svg",
        "system": {
            "version": 2,
            "description": description,
            "basic": {
                "level": level or "1",
                "depletion": depletion,
                "identified": True,
            },
        },
        "effects": [],
        "_stats": {
            "compendiumSource": None,
            "duplicateSource": None,
            "exportSource": {
                "worldId": "lands-of-legend",
                "uuid": f"Item.{_new_item_id()}",
                "coreVersion": "13.351",
                "systemId": "cyphersystem",
                "systemVersion": "3.4.3",
            },
            "coreVersion": "13.351",
            "systemId": "cyphersystem",
            "systemVersion": "3.4.3",
            "createdTime": _ms_now(),
            "modifiedTime": _ms_now(),
        },
    }
