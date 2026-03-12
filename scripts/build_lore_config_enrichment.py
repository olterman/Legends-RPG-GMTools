from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

import yaml
from lol_api.config_loader import load_config_dir, infer_default_world_id

RACE_HINTS = {
    "race",
    "races",
    "tribe",
    "tribes",
    "folk",
    "people",
    "peoples",
    "clan",
    "clans",
    "bloodline",
}

ENV_HINTS = {
    "city",
    "cities",
    "realm",
    "realms",
    "land",
    "lands",
    "region",
    "coast",
    "harbor",
    "island",
    "sea",
    "seas",
    "mountain",
    "highlands",
    "lowlands",
    "wilds",
    "forest",
    "desert",
    "ruins",
}

STOP_TOKENS = {
    "overview",
    "origin",
    "separation",
    "society",
    "relations",
    "matters",
    "legacy",
    "references",
    "fragmented",
    "why",
    "nature",
    "saying",
    "deep",
    "groves",
}

NOISE_NAMES = {
    "the",
    "they",
    "this",
    "that",
    "these",
    "those",
    "you",
    "we",
    "it",
    "he",
    "she",
    "them",
    "his",
    "her",
    "our",
    "their",
}

IGNORE_TITLES = {
    "ancestral descriptors",
    "peoples",
    "places",
    "world seed",
    "untitled",
    "gods and powers",
}

DEFAULT_EXCLUDED_RACE_KEYS = {
    "daelgast",
    "alfirin_tribes",
    "human_tribes",
    "uruk_tribes",
    "small_folk",
}


@dataclass
class Candidate:
    name: str
    key: str
    category: str
    confidence: float
    mentions: int
    source_titles: list[str]
    source_paths: list[str]
    evidence: str


def slugify(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_text = ascii_text.lower().strip()
    ascii_text = re.sub(r"[^a-z0-9]+", "_", ascii_text)
    ascii_text = re.sub(r"_+", "_", ascii_text)
    return ascii_text.strip("_")


def title_case(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def existing_terms(config: dict[str, Any], key: str) -> set[str]:
    found: set[str] = set()
    section = config.get(key, {}) or {}
    if not isinstance(section, dict):
        return found

    for item_key, item_data in section.items():
        found.add(slugify(str(item_key)))
        if isinstance(item_data, dict):
            item_name = str(item_data.get("name", "")).strip()
            if item_name:
                found.add(slugify(item_name))
    return found


def canonical_key(key: str) -> str:
    return re.sub(r"^the_", "", slugify(key))


def similar_to_existing(key: str, existing: set[str]) -> bool:
    ck = canonical_key(key)
    for item in existing:
        if canonical_key(item) == ck:
            return True
        if SequenceMatcher(None, canonical_key(item), ck).ratio() >= 0.9:
            return True
    return False


def clean_title_candidate(title: str) -> str:
    value = title_case(title)
    value = re.sub(r"\s*\([^)]*\)\s*", " ", value).strip()
    value = re.sub(r"^The\s+", "", value, flags=re.IGNORECASE)
    return title_case(value)


def classify_candidate(name: str, text_blob: str) -> tuple[str, float]:
    name_lc = name.lower()
    key = slugify(name)
    race_forced = {
        "alfirin",
        "alfirin_tribes",
        "human_tribes",
        "uruk_tribes",
        "small_folk",
        "velim",
        "uruk",
        "lilim",
        "fellic",
        "gitz",
        "vaettyr",
        "duergar",
        "daelgast",
        "lhainim",
    }
    env_forced = {
        "aldamir",
        "cird",
        "cirth",
        "cirdion",
        "caldor",
        "xanthir",
        "fenmir",
        "sands",
        "ered_engrin",
        "lomeanor",
        "pirate_seas",
    }

    if key in race_forced:
        return "race", 0.9
    if key in env_forced:
        return "area", 0.9

    race_score = 0
    env_score = 0

    if any(h in name_lc for h in ["tribe", "folk", "people", "duergar", "lilim", "uruk", "alfirin", "fellic", "vaettyr", "gitz"]):
        race_score += 2
    if any(h in name_lc for h in ["city", "island", "sea", "sands", "highlands", "lowlands", "wilds", "ruins", "cirdion", "caldor", "xanthir", "lomeanor", "almadir", "fenmir"]):
        env_score += 2

    # Hard category bias for obvious ancestry labels.
    if any(h in name_lc for h in ["tribe", "folk", "people"]):
        race_score += 5

    words = set(re.findall(r"[a-z]+", text_blob.lower()))
    race_score += len(words.intersection(RACE_HINTS))
    env_score += len(words.intersection(ENV_HINTS))

    if key in {"peoples", "places", "world_seed", "ancestral_descriptors"}:
        return "ignore", 0.0

    if race_score == 0 and env_score == 0:
        return "ignore", 0.0

    if race_score >= env_score:
        conf = min(0.95, 0.55 + 0.08 * (race_score - env_score) + 0.02 * race_score)
        return "race", conf

    conf = min(0.95, 0.55 + 0.08 * (env_score - race_score) + 0.02 * env_score)
    return "area", conf


def choose_evidence(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith("---"):
            continue
        return s[:260]
    return fallback[:260]


def build_candidates(config: dict[str, Any], lore_dir: Path) -> dict[str, list[Candidate]]:
    races_existing = existing_terms(config, "races")
    env_existing = existing_terms(config, "areas")

    entries_dir = lore_dir / "entries"
    results: dict[str, Candidate] = {}

    for path in sorted(entries_dir.glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        title = str(entry.get("title", "")).strip()
        source_path = str(entry.get("source_path", "")).strip()
        markdown = str(entry.get("content_markdown", "") or "")
        excerpt = str(entry.get("excerpt", "") or "")

        if not title or title.lower().strip() in IGNORE_TITLES:
            continue

        title_candidate = clean_title_candidate(title)
        local_counts: dict[str, int] = {}
        if title_candidate:
            local_counts[title_candidate] = 5

        for name, mentions in local_counts.items():
            key = slugify(name)
            if not key:
                continue
            if key in STOP_TOKENS:
                continue
            if name.lower() in NOISE_NAMES:
                continue
            if len(name) < 3:
                continue

            category, confidence = classify_candidate(name, markdown)
            if category == "ignore":
                continue

            if category == "race" and similar_to_existing(key, races_existing):
                continue
            if category == "area" and similar_to_existing(key, env_existing):
                continue

            evidence = choose_evidence(markdown, excerpt)
            bucket_key = f"{category}:{key}"
            current = results.get(bucket_key)
            if current is None:
                results[bucket_key] = Candidate(
                    name=title_case(name),
                    key=key,
                    category=category,
                    confidence=confidence,
                    mentions=mentions,
                    source_titles=[title] if title else [],
                    source_paths=[source_path] if source_path else [],
                    evidence=evidence,
                )
                continue

            current.mentions += mentions
            current.confidence = max(current.confidence, confidence)
            if title and title not in current.source_titles:
                current.source_titles.append(title)
            if source_path and source_path not in current.source_paths:
                current.source_paths.append(source_path)

    races: list[Candidate] = []
    envs: list[Candidate] = []
    for c in results.values():
        if c.mentions < 4:
            continue
        if c.category == "race":
            races.append(c)
        else:
            envs.append(c)

    # Avoid over-broad region key. Fenmir should be represented by specific
    # subregions (highlands/lowlands), which are already modeled in base config.
    envs = [c for c in envs if c.key != "fenmir"]

    races.sort(key=lambda x: (-x.confidence, -x.mentions, x.name.lower()))
    envs.sort(key=lambda x: (-x.confidence, -x.mentions, x.name.lower()))
    return {"races": races[:40], "areas": envs[:60]}


def race_stub(c: Candidate) -> dict[str, Any]:
    variants: dict[str, Any] = {}
    if c.key == "human_tribes":
        variants = {
            "fenmir": {
                "label": "Fenmir",
                "appearance": ["wind-weathered skin", "ritual tattoos"],
                "clothing": "highland leathers, clan cloth, carved bone charms",
                "tone": "spiritual proud highlanders",
            },
            "caldoran": {
                "label": "Caldorans",
                "appearance": ["confident cosmopolitan bearing"],
                "clothing": "refined trade-city garments, renaissance merchant fashion",
                "tone": "ambitious merchant culture",
            },
            "xanthir": {
                "label": "Xanthir",
                "appearance": ["stern disciplined gaze"],
                "clothing": "militant temple vestments, red religious insignia",
                "tone": "militant theocracy",
            },
        }
    elif c.key == "uruk_tribes":
        variants = {
            "highland": {
                "label": "Highland Uruk",
                "appearance": ["blue skin", "weathered philosopher-warrior presence"],
                "clothing": "nomadic layers, herd gear, carved memory tokens",
                "tone": "herders poets philosophers",
            },
            "lowland": {
                "label": "Lowland Uruk",
                "appearance": ["green skin", "scarred martial bearing"],
                "clothing": "disciplined war armor, conquest trophies",
                "tone": "militant conquerors",
            },
        }
    elif c.key == "alfirin_tribes":
        variants = {
            "sky_children": {
                "label": "Sky Children",
                "appearance": ["blue skin", "clear luminous eyes", "calm noble bearing"],
                "clothing": "sea-silk robes, scholar garments, wind-borne fabrics, coastal ornament",
                "tone": "open cultured trade-oriented",
            },
            "galadhrim": {
                "label": "Galadhrim",
                "appearance": ["green skin", "wild natural grace", "forest-bound presence"],
                "clothing": "living fiber garments, leaf-patterned leathers, draped natural textures",
                "tone": "instinctive nature stewards",
            },
            "duathrim": {
                "label": "Duathrim",
                "appearance": ["white hair", "pale to violet skin", "cold watchful gaze"],
                "clothing": "dark layered robes, hidden blades, shadow-draped fabrics",
                "tone": "secretive hierarchical manipulators",
            },
        }
    elif c.key == "small_folk":
        variants = {
            "gitz": {
                "label": "Gitz",
                "appearance": ["quick agile bodies", "bright alert eyes"],
                "clothing": "patched woodland gear, clever handmade tools",
                "tone": "quick wary pragmatic",
            },
            "vaettyr": {
                "label": "Vaettyr",
                "appearance": ["thoughtful analytical gaze", "soot-marked hands"],
                "clothing": "engineer garments, tool harnesses, machine maintenance gear",
                "tone": "methodical quiet engineers",
            },
            "lhainim": {
                "label": "Lhainîm",
                "appearance": ["fey-touched features", "whimsical dangerous aura"],
                "clothing": "leafwork, patchwork, ritual trinkets",
                "tone": "otherworldly trickster folklore spirits",
            },
            "velim": {
                "label": "Velim",
                "appearance": ["faint inner glow", "delicate luminous wings"],
                "clothing": "minimal luminous adornment, threshold markings",
                "tone": "quiet vigilant gate wardens",
            },
        }

    data = {
        "name": c.name,
        "group": "Lore-Derived",
        "character_base": c.key,
        "core_truths": [
            f"Lore-derived ancestry based on {', '.join(c.source_titles[:2]) or 'logseq lore'}.",
            "Requires final lore curation.",
        ],
        "themes": ["identity", "survival", "legacy"],
        "tone": ["grounded", "mythic"],
        "avoid": ["stereotypes pending curation"],
        "visual_defaults": {
            "scale": "human sized",
            "signature_features": [f"traits associated with {c.name.lower()} lore"],
            "clothing": "lore-consistent attire pending curation",
        },
    }
    if variants:
        data["variants"] = variants

    return {c.key: data}


def area_stub(c: Candidate) -> dict[str, Any]:
    return {
        c.key: {
            "name": c.name,
            "type": "region",
            "culture": "mixed",
            "description": c.evidence,
            "visual_traits": [
                f"landmarks tied to {c.name.lower()}",
                "lore-derived terrain cues pending curation",
                "faction traces and local history",
            ],
            "mood": ["mysterious", "volatile", "adventurous"],
        }
    }


def settlement_stub(c: Candidate) -> dict[str, Any]:
    label = c.name
    return {
        c.key: {
            "settlement_types": [
                f"{label.lower()} outpost",
                f"{label.lower()} trade camp",
                f"{label.lower()} fortified village",
            ],
            "visual_features": [
                f"architecture adapted to {label.lower()} terrain",
                "visible scars from older conflicts",
                "local iconography tied to lore factions",
            ],
            "landmarks": [
                f"a central site linked to {label.lower()} history",
                "a contested route or crossing",
                "a ritual or civic gathering place",
            ],
            "economies": [
                "survival trade and local craft",
                "resource extraction or waystation services",
                "faction contracts and guarded routes",
            ],
            "tensions": [
                "conflict between local tradition and outside pressure",
                "scarcity exposing old rivalries",
                "a buried truth resurfacing through recent events",
            ],
            "atmospheres": [
                "uneasy but resilient",
                "politically tense",
                "ripe for adventure hooks",
            ],
        }
    }


def encounter_stub(c: Candidate) -> dict[str, Any]:
    label = c.name
    return {
        c.key: {
            "first_impressions": [
                f"the party arrives as tensions around {label} spill into public view",
                "a normal routine is abruptly interrupted by an unresolved incident",
                "locals are watchful and withholding around a recent disturbance",
            ],
            "subjects": [
                "a local authority under pressure",
                "a messenger or witness carrying partial truth",
                "a faction agent pursuing a private objective",
            ],
            "truths": [
                "the visible conflict hides a deeper historical cause",
                "someone is steering events to control the narrative",
                f"the real stake is who defines {label} going forward",
            ],
            "complications": [
                "every option creates a new obligation with a local faction",
                "time pressure narrows safe choices",
                "an apparent ally is withholding critical context",
            ],
            "hooks": [
                "stabilize the situation before it escalates into open violence",
                "uncover the hidden motive behind the public crisis",
                "choose which truth to reveal and who pays for it",
            ],
        }
    }


def merge_snippets(items: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in items:
        merged.update(item)
    return merged


def load_base_config(config_dir: Path) -> dict[str, Any]:
    default_world = infer_default_world_id(config_dir)
    return load_config_dir(config_dir, world_id=default_world)


def ai_prompt(candidates_path: Path, output_path: Path) -> None:
    content = f"""# AI Config Enrichment Prompt

Use `{candidates_path}` as source material.

Goal:
- Expand `config/worlds/lands_of_legends/10_races.yaml`, `config/worlds/lands_of_legends/12_areas.yaml`, `config/worlds/lands_of_legends/20_settlements.yaml`, and `config/worlds/lands_of_legends/21_encounters.yaml`.
- Keep compatibility with existing schema.
- Prioritize high-confidence candidates first.

Rules:
- Do not change existing keys unless needed for typo fix or aliasing.
- Keep new keys snake_case and stable.
- For each added area, also add matching `settlements` and `encounters` blocks.
- Write hooks/truths/complications in the same style as existing encounter config.
- Use evidence lines and source titles to keep additions lore-faithful.

Review checklist:
1. No duplicate semantic entries (`the_sands` vs `sands`).
2. No generic placeholders left in final YAML.
3. Added entries are grounded in lore evidence.
4. `POST /reload` works and generation endpoints still return results.
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build AI-ready config enrichment from lore.")
    parser.add_argument("--config-dir", default="config")
    parser.add_argument("--lore-dir", default="lore")
    parser.add_argument("--json-out", default="docs/lore_config_enrichment_candidates.json")
    parser.add_argument("--prompt-out", default="docs/AI_CONFIG_ENRICHMENT_PROMPT.md")
    parser.add_argument("--yaml-out", default="docs/lore_config_enrichment.generated.yaml")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.72,
        help="Only write candidates above this confidence to yaml-out.",
    )
    args = parser.parse_args()

    config = load_base_config(Path(args.config_dir))
    candidates = build_candidates(config, Path(args.lore_dir))

    races = candidates["races"]
    envs = candidates["areas"]

    output_json = {
        "summary": {
            "race_candidates": len(races),
            "area_candidates": len(envs),
            "yaml_min_confidence": args.min_confidence,
            "default_excluded_race_keys": sorted(DEFAULT_EXCLUDED_RACE_KEYS),
        },
        "races": [
            {
                "name": c.name,
                "key": c.key,
                "confidence": round(c.confidence, 3),
                "mentions": c.mentions,
                "source_titles": c.source_titles,
                "source_paths": c.source_paths,
                "evidence": c.evidence,
            }
            for c in races
        ],
        "areas": [
            {
                "name": c.name,
                "key": c.key,
                "confidence": round(c.confidence, 3),
                "mentions": c.mentions,
                "source_titles": c.source_titles,
                "source_paths": c.source_paths,
                "evidence": c.evidence,
            }
            for c in envs
        ],
    }

    json_path = Path(args.json_out)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(output_json, indent=2, ensure_ascii=False), encoding="utf-8")

    ai_prompt(json_path, Path(args.prompt_out))

    race_yaml = [
        race_stub(c)
        for c in races
        if c.confidence >= args.min_confidence and c.key not in DEFAULT_EXCLUDED_RACE_KEYS
    ]
    env_yaml = [area_stub(c) for c in envs if c.confidence >= args.min_confidence]
    settlement_yaml = [settlement_stub(c) for c in envs if c.confidence >= args.min_confidence]
    encounter_yaml = [encounter_stub(c) for c in envs if c.confidence >= args.min_confidence]

    yaml_doc = {
        "races": merge_snippets(race_yaml),
        "areas": merge_snippets(env_yaml),
        "settlements": merge_snippets(settlement_yaml),
        "encounters": merge_snippets(encounter_yaml),
    }
    yaml_path = Path(args.yaml_out)
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        yaml.safe_dump(yaml_doc, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
    )

    print(f"Candidates JSON: {json_path}")
    print(f"AI prompt: {args.prompt_out}")
    print(f"Generated config additions: {yaml_path}")
    print(f"Race candidates: {len(races)}")
    print(f"Area candidates: {len(envs)}")


if __name__ == "__main__":
    main()
