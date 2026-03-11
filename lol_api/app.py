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

    config_dir = project_root / "config"
    storage_dir = project_root / "storage"

    # store paths in Flask config
    app.config["LOL_CONFIG_DIR"] = config_dir
    app.config["LOL_STORAGE_DIR"] = storage_dir

    # load YAML configuration
    app.config["LOL_CONFIG"] = load_config_dir(config_dir)

    register_routes(app)

    return app