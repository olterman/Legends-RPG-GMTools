from flask import Flask
import os
from pathlib import Path

from .api import register_routes
from .config_loader import (
    load_config_dir,
    list_world_ids,
    infer_default_world_id,
    list_world_descriptors,
    list_setting_ids,
    infer_default_setting_id,
    list_setting_descriptors,
)


def create_app():

    base_dir = Path(__file__).resolve().parent
    project_root = base_dir.parent

    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates")
    )
    app.json.sort_keys = False

    config_dir = project_root / "config"
    storage_dir = project_root / "storage"
    compendium_dir = project_root / "CSRD" / "compendium"
    official_compendium_dir = project_root / "PDF_Repository" / "private_compendium"
    images_dir = project_root / "images"
    lore_dir = project_root / "lore"
    prompts_file = lore_dir / "prompts_index.json"
    docs_dir = project_root / "docs"
    foundry_token = os.getenv("LOL_FOUNDRYVTT_API_TOKEN", "").strip()
    foundry_origins_raw = os.getenv("LOL_FOUNDRYVTT_ALLOWED_ORIGINS", "").strip()
    foundry_origins = [
        value.strip()
        for value in foundry_origins_raw.split(",")
        if value.strip()
    ]


    # store paths in Flask config
    app.config["LOL_PROJECT_ROOT"] = project_root
    app.config["LOL_CONFIG_DIR"] = config_dir
    app.config["LOL_STORAGE_DIR"] = storage_dir
    app.config["LOL_COMPENDIUM_DIR"] = compendium_dir
    app.config["LOL_OFFICIAL_COMPENDIUM_DIR"] = official_compendium_dir
    app.config["LOL_IMAGES_DIR"] = images_dir
    app.config["LOL_LORE_DIR"] = lore_dir
    app.config["LOL_PROMPTS_FILE"] = prompts_file
    app.config["LOL_DOCS_DIR"] = docs_dir
    app.config["LOL_FOUNDRYVTT_API_TOKEN"] = foundry_token
    app.config["LOL_FOUNDRYVTT_ALLOWED_ORIGINS"] = foundry_origins

    available_worlds = list_world_ids(config_dir)
    available_world_descriptors = list_world_descriptors(config_dir)
    available_settings = list_setting_ids(config_dir)
    available_setting_descriptors = list_setting_descriptors(config_dir)
    requested_setting = (
        os.getenv("LOL_SETTING_ID", "").strip()
        or os.getenv("LOL_WORLD_ID", "").strip()
        or None
    )
    default_setting = infer_default_setting_id(config_dir) or infer_default_world_id(config_dir)
    active_setting = requested_setting or default_setting

    # load layered YAML configuration (legacy flat + optional core + optional setting)
    app.config["LOL_CONFIG"] = load_config_dir(config_dir, setting_id=active_setting)
    app.config["LOL_SETTING_ID"] = active_setting
    app.config["LOL_WORLD_ID"] = active_setting
    app.config["LOL_AVAILABLE_WORLDS"] = available_worlds
    app.config["LOL_AVAILABLE_WORLD_DESCRIPTORS"] = available_world_descriptors
    app.config["LOL_AVAILABLE_SETTINGS"] = available_settings
    app.config["LOL_AVAILABLE_SETTING_DESCRIPTORS"] = available_setting_descriptors

    register_routes(app)

    return app
