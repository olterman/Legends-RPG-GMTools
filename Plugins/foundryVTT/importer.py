from __future__ import annotations

import re
from html import unescape
from typing import Any


UUID_LINK_PATTERN = re.compile(
    r"@UUID\[(?P<target>[^\]]+)\](?:\{(?P<label>[^}]*)\})?",
    flags=re.IGNORECASE,
)


def _strip_foundry_uuid_links(text: str) -> tuple[str, list[dict[str, str]]]:
    links: list[dict[str, str]] = []

    def repl(match: re.Match) -> str:
        target = str(match.group("target") or "").strip()
        label = str(match.group("label") or "").strip()
        if target:
            links.append({
                "target": target,
                "label": label,
            })
        return label or ""

    cleaned = UUID_LINK_PATTERN.sub(repl, str(text or ""))
    return cleaned, links


def _html_to_plain_text(value: str) -> str:
    text, _ = _strip_foundry_uuid_links(str(value or ""))
    if not text:
        return ""
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_skill_level(value: str) -> str:
    raw = str(value or "").strip().lower()
    mapping = {
        "inability": "inability",
        "practiced": "practiced",
        "practised": "practiced",
        "trained": "trained",
        "specialized": "expert",
        "specialised": "expert",
        "expert": "expert",
    }
    return mapping.get(raw, "trained")


def foundry_actor_to_character_sheet(actor: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    system = actor.get("system") if isinstance(actor.get("system"), dict) else {}
    basic = system.get("basic") if isinstance(system.get("basic"), dict) else {}
    pools = system.get("pools") if isinstance(system.get("pools"), dict) else {}
    combat = system.get("combat") if isinstance(system.get("combat"), dict) else {}
    recoveries = combat.get("recoveries") if isinstance(combat.get("recoveries"), dict) else {}
    damage_track = combat.get("damageTrack") if isinstance(combat.get("damageTrack"), dict) else {}
    equipment_sys = system.get("equipment") if isinstance(system.get("equipment"), dict) else {}

    descriptor = str(basic.get("descriptor") or "").strip()
    type_title = str(basic.get("type") or "").strip()
    focus = str(basic.get("focus") or "").strip()
    name = str(actor.get("name") or basic.get("name") or "Unnamed Character").strip() or "Unnamed Character"

    def pool_value(key: str, field: str, fallback: int = 0) -> int:
        node = pools.get(key) if isinstance(pools.get(key), dict) else {}
        try:
            return int(node.get(field) if node.get(field) is not None else fallback)
        except Exception:
            return fallback

    max_might = pool_value("might", "max")
    max_speed = pool_value("speed", "max")
    max_intellect = pool_value("intellect", "max")
    cur_might = pool_value("might", "value", max_might)
    cur_speed = pool_value("speed", "value", max_speed)
    cur_intellect = pool_value("intellect", "value", max_intellect)

    edge_might = pool_value("might", "edge")
    edge_speed = pool_value("speed", "edge")
    edge_intellect = pool_value("intellect", "edge")

    ability_names: list[str] = []
    chosen_skills: list[dict[str, str]] = []
    descriptor_skills: list[str] = []
    descriptor_inabilities: list[str] = []
    attacks: list[dict[str, Any]] = []
    cyphers: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    equipment_lines: list[str] = []
    notes_parts: list[str] = []
    foundry_internal_links: list[dict[str, str]] = []

    for item in actor.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        item_name = str(item.get("name") or "").strip()
        item_system = item.get("system") if isinstance(item.get("system"), dict) else {}
        basic_data = item_system.get("basic") if isinstance(item_system.get("basic"), dict) else {}
        raw_desc, desc_links = _strip_foundry_uuid_links(str(item_system.get("description") or ""))
        foundry_internal_links.extend(desc_links)
        item_desc = _html_to_plain_text(raw_desc)

        if item_type == "ability":
            if item_name:
                ability_names.append(item_name)
        elif item_type == "skill":
            if item_name:
                level = _parse_skill_level(basic_data.get("rating"))
                chosen_skills.append({"name": item_name, "level": level})
                if level == "inability":
                    descriptor_inabilities.append(item_name)
                else:
                    descriptor_skills.append(item_name)
        elif item_type == "attack":
            if item_name:
                attacks.append({
                    "name": item_name,
                    "description": item_desc,
                    "damage": basic_data.get("damage"),
                    "weapon_type": basic_data.get("type"),
                    "range": basic_data.get("range"),
                    "skill_rating": basic_data.get("skillRating"),
                })
        elif item_type == "equipment":
            if item_name:
                qty = basic_data.get("quantity")
                if qty not in (None, "", 1, "1"):
                    equipment_lines.append(f"{item_name} x{qty}")
                else:
                    equipment_lines.append(item_name)
        elif item_type == "cypher":
            if item_name:
                cyphers.append({
                    "name": item_name,
                    "level": basic_data.get("level"),
                    "description": item_desc,
                })
        elif item_type == "artifact":
            if item_name:
                level = basic_data.get("level")
                dep = str(basic_data.get("depletion") or "").strip()
                suffix = []
                if level not in (None, ""):
                    suffix.append(f"L{level}")
                if dep:
                    suffix.append(f"depletion {dep}")
                artifacts.append({
                    "name": item_name,
                    "level": level,
                    "depletion": dep,
                    "description": item_desc,
                })

        if item_desc and item_type in {"ability", "skill", "attack"}:
            notes_parts.append(f"{item_name}: {item_desc}".strip(": "))

    cypher_limit_raw = equipment_sys.get("cypherLimit")
    try:
        cypher_limit = int(cypher_limit_raw) if cypher_limit_raw not in (None, "") else 0
    except Exception:
        cypher_limit = 0
    if cypher_limit <= 0:
        cypher_limit = 2

    tier_raw = basic.get("tier")
    effort_raw = basic.get("effort")
    try:
        tier = int(tier_raw) if tier_raw is not None else 1
    except Exception:
        tier = 1
    try:
        effort = int(effort_raw) if effort_raw is not None else 1
    except Exception:
        effort = 1

    recovery_action = any(
        bool(recoveries.get(k))
        for k in ("oneAction", "oneAction2", "oneAction3", "oneAction4", "oneAction5", "oneAction6", "oneAction7")
    )
    recovery_10m = any(bool(recoveries.get(k)) for k in ("tenMinutes", "tenMinutes2"))
    recovery_1h = bool(recoveries.get("oneHour"))
    recovery_10h = bool(recoveries.get("tenHours"))

    raw_notes, notes_links = _strip_foundry_uuid_links(str(system.get("notes") or ""))
    raw_description, description_links = _strip_foundry_uuid_links(str(system.get("description") or ""))
    foundry_internal_links.extend(notes_links)
    foundry_internal_links.extend(description_links)
    actor_notes = _html_to_plain_text(raw_notes)
    actor_description = _html_to_plain_text(raw_description)
    summary_sentence = f"{name} is {descriptor or 'a character'} {('who ' + focus) if focus else ''}.".replace("  ", " ").strip()
    summary_sentence = summary_sentence[:-1] + "." if not summary_sentence.endswith(".") else summary_sentence

    merged_notes = "\n\n".join(part for part in [actor_notes, actor_description] if part)
    if notes_parts:
        merged_notes = (merged_notes + "\n\n" if merged_notes else "") + "\n".join(notes_parts)

    foundry_uuid = ""
    stats = actor.get("_stats")
    if isinstance(stats, dict):
        export_source = stats.get("exportSource")
        if isinstance(export_source, dict):
            foundry_uuid = str(export_source.get("uuid") or "").strip()

    metadata = {
        "name": name,
        "race": str(payload.get("race") or ""),
        "profession": str(payload.get("profession") or ""),
        "area": str(payload.get("area") or payload.get("environment") or ""),
        "location": str(payload.get("location") or ""),
        "character_type": type_title,
        "flavor": "",
        "descriptor": descriptor,
        "focus": focus,
        "tier": tier,
        "xp": basic.get("xp"),
        "source": "foundry_vtt",
        "foundry_actor_type": str(actor.get("type") or ""),
        "foundry_actor_uuid": foundry_uuid,
        "foundry_internal_links": foundry_internal_links,
    }

    return {
        "name": name,
        "sentence": summary_sentence,
        "type": type_title,
        "flavor": "",
        "descriptor": descriptor,
        "focus": focus,
        "effort": effort,
        "cypher_limit": cypher_limit,
        "weapons": "",
        "pools": {
            "max": {"might": max_might, "speed": max_speed, "intellect": max_intellect},
            "current": {"might": cur_might, "speed": cur_speed, "intellect": cur_intellect},
        },
        "edges": {"might": edge_might, "speed": edge_speed, "intellect": edge_intellect},
        "damage_track": str(damage_track.get("state") or "Hale"),
        "recovery_rolls_used": {
            "action": recovery_action,
            "ten_minutes": recovery_10m,
            "one_hour": recovery_1h,
            "ten_hours": recovery_10h,
        },
        "descriptor_effects": {
            "pool": {"might": 0, "speed": 0, "intellect": 0},
            "skills": descriptor_skills,
            "inabilities": descriptor_inabilities,
            "traits": [],
            "equipment": [],
        },
        "type_tier_1_abilities": [],
        "flavor_tier_1_abilities": [],
        "focus_tier_1_abilities": [],
        "chosen_abilities": ability_names,
        "chosen_skills": chosen_skills,
        "attacks": attacks,
        "cyphers": cyphers,
        "artifacts": artifacts,
        "equipment": equipment_lines,
        "notes": merged_notes,
        "generated": None,
        "wizard_completed": True,
        "metadata": metadata,
    }


def foundry_actor_to_npc_result(actor: dict[str, Any], payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    system = actor.get("system") if isinstance(actor.get("system"), dict) else {}
    basic = system.get("basic") if isinstance(system.get("basic"), dict) else {}
    pools = system.get("pools") if isinstance(system.get("pools"), dict) else {}
    combat = system.get("combat") if isinstance(system.get("combat"), dict) else {}

    name = str(actor.get("name") or "Imported NPC").strip() or "Imported NPC"
    level_raw = basic.get("level")
    try:
        level = int(level_raw) if level_raw is not None else 1
    except Exception:
        level = 1

    health_node = pools.get("health") if isinstance(pools.get("health"), dict) else {}
    try:
        health = int(health_node.get("value") if health_node.get("value") is not None else (level * 3))
    except Exception:
        health = level * 3
    try:
        armor = int(combat.get("armor") or 0)
    except Exception:
        armor = 0
    try:
        damage = int(combat.get("damage") or 0)
    except Exception:
        damage = 0

    raw_notes, notes_links = _strip_foundry_uuid_links(str(system.get("notes") or ""))
    raw_description, description_links = _strip_foundry_uuid_links(str(system.get("description") or ""))
    notes = _html_to_plain_text(raw_notes)
    description = _html_to_plain_text(raw_description)
    full_text = "\n\n".join(part for part in [description, notes] if part).strip()

    attacks: list[str] = []
    loot: list[str] = []
    for item in actor.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        item_name = str(item.get("name") or "").strip()
        if not item_name:
            continue
        if item_type == "attack":
            attacks.append(item_name)
        elif item_type in {"equipment", "artifact", "cypher"}:
            loot.append(item_name)

    sections = {
        "setting": str(payload.get("setting") or ""),
        "character": name,
        "environment": str(payload.get("area") or payload.get("environment") or ""),
    }

    stat_block = {
        "level": level,
        "target_number": level * 3,
        "health": health,
        "armor": armor,
        "damage": damage,
        "movement": "short",
        "modifications": [],
        "combat": attacks,
        "interaction": [],
        "loot": loot,
    }

    compendium_source = ""
    stats = actor.get("_stats")
    if isinstance(stats, dict):
        compendium_source = str(stats.get("compendiumSource") or "").strip()
    lowered_source = compendium_source.lower()
    result_type = "creature" if ".creatures." in lowered_source else "npc"

    metadata = {
        "race": str(payload.get("race") or ""),
        "profession": str(payload.get("profession") or ""),
        "area": str(payload.get("area") or payload.get("environment") or ""),
        "environment": str(payload.get("environment") or payload.get("area") or ""),
        "location": str(payload.get("location") or ""),
        "source": "foundry_vtt",
        "origin": "foundry_import",
        "foundry_actor_type": str(actor.get("type") or ""),
        "foundry_compendium_source": compendium_source,
        "foundry_internal_links": notes_links + description_links,
    }
    if isinstance(stats, dict):
        export_source = stats.get("exportSource")
        if isinstance(export_source, dict):
            metadata["foundry_actor_uuid"] = str(export_source.get("uuid") or "").strip()

    text_chunks = [full_text] if full_text else []
    text_chunks.append(
        f"{name}\nLevel {stat_block['level']} (target number {stat_block['target_number']})\n"
        f"Health: {stat_block['health']}\nArmor: {stat_block['armor']}\nDamage: {stat_block['damage']}"
    )
    return {
        "type": result_type,
        "name": name,
        "sections": {k: v for k, v in sections.items() if str(v).strip()},
        "stat_block": stat_block,
        "text": "\n\n".join(text_chunks).strip(),
        "metadata": metadata,
    }
