from pathlib import Path
from flask import Flask

from .api import register_routes
from .config_loader import load_config_dir


def create_app():
    base_dir = Path(__file__).resolve().parent

    app = Flask(
        __name__,
        template_folder=str(base_dir / "templates")
    )

    config_dir = base_dir.parent / "config"
    storage_dir = base_dir.parent / "storage"

    app.config["LOL_BASE_DIR"] = base_dir
    app.config["LOL_CONFIG_DIR"] = config_dir
    app.config["LOL_STORAGE_DIR"] = storage_dir
    app.config["LOL_CONFIG"] = load_config_dir(config_dir)

    register_routes(app)
    return app