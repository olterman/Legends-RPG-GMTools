from flask import Flask
from pathlib import Path

from .api import register_routes
from .config_loader import load_config_dir


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
    images_dir = project_root / "images"
    lore_dir = project_root / "lore"
    prompts_file = lore_dir / "prompts_index.json"
    docs_dir = project_root / "docs"


    # store paths in Flask config
    app.config["LOL_PROJECT_ROOT"] = project_root
    app.config["LOL_CONFIG_DIR"] = config_dir
    app.config["LOL_STORAGE_DIR"] = storage_dir
    app.config["LOL_COMPENDIUM_DIR"] = compendium_dir
    app.config["LOL_IMAGES_DIR"] = images_dir
    app.config["LOL_LORE_DIR"] = lore_dir
    app.config["LOL_PROMPTS_FILE"] = prompts_file
    app.config["LOL_DOCS_DIR"] = docs_dir

    # load YAML configuration
    app.config["LOL_CONFIG"] = load_config_dir(config_dir)

    register_routes(app)

    return app
