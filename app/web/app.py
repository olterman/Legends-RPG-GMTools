from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from app.core.app import discover_systems
from app.core.auth import AuthService
from app.core.campaigns import CampaignService
from app.core.content import ContentService
from app.core.contracts import build_record
from app.core.contracts.context import normalize_token
from app.core.database import ensure_database
from app.core.config import MANIFEST_FILENAME, load_json_object
from app.core.rulebooks import build_rulebook_toc, load_rulebook_document, render_rulebook_html

OWNER_USERNAME = "olterman"
OWNER_EMAIL = "patrik@olterman.se"
OWNER_PASSWORD = "changeme"
OWNER_DISPLAY_NAME = "Patrik Olterman"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _systems_root(project_root: Path) -> Path:
    return project_root / "app" / "systems"


def _content_root(project_root: Path) -> Path:
    return project_root / "content"


def _data_root(project_root: Path) -> Path:
    return project_root / "data"


def _db_path(project_root: Path) -> Path:
    return _data_root(project_root) / "gmforge.db"


def _branding_root(project_root: Path) -> Path:
    return _data_root(project_root) / "assets" / "branding"


def _branding_asset_info(project_root: Path) -> dict[str, str]:
    branding_root = _branding_root(project_root)
    logo_name = ""
    for candidate in (
        "gmf_logo.svg",
        "gmf-logo.svg",
        "gmf_logo.png",
        "gmf-logo.png",
        "gmf_logo.webp",
        "gmf-logo.webp",
    ):
        if (branding_root / candidate).exists():
            logo_name = candidate
            break
    favicon_name = ""
    for candidate in (
        "favicon.ico",
        "gmf_logo.png",
        "gmf-logo.png",
        "gmf_logo.svg",
        "gmf-logo.svg",
    ):
        if (branding_root / candidate).exists():
            favicon_name = candidate
            break
    return {
        "logo_name": logo_name,
        "logo_url": f"/assets/branding/{logo_name}" if logo_name else "",
        "favicon_name": favicon_name,
        "favicon_url": "/favicon.ico" if favicon_name else "",
    }


def _discover_setting_options(project_root: Path, *, system_id: str, expansion_id: str = "") -> list[dict[str, str]]:
    system_token = normalize_token(system_id)
    if not system_token or system_token == "none":
        return []
    root = _content_root(project_root) / system_token
    if not root.exists():
        return []
    items: list[dict[str, str]] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        manifest_path = child / MANIFEST_FILENAME
        if not manifest_path.exists():
            continue
        try:
            payload = load_json_object(manifest_path)
        except Exception:
            continue
        if str(payload.get("kind") or "") != "setting":
            continue
        if expansion_id and str(payload.get("expansion_id") or "") != normalize_token(expansion_id):
            continue
        items.append(
            {
                "id": str(payload.get("id") or child.name),
                "label": str(payload.get("label") or child.name),
                "expansion_id": str(payload.get("expansion_id") or ""),
            }
        )
    return items


def _build_workspace_options(
    project_root: Path,
    campaign_service: CampaignService,
    *,
    selected_system_id: str = "",
    selected_expansion_id: str = "",
    selected_setting_id: str = "",
) -> dict[str, Any]:
    systems = discover_systems(_systems_root(project_root))
    system_options = [{"id": "none", "label": "No System"}]
    system_options.extend({"id": system["id"], "label": system["name"]} for system in systems)
    selected_system = normalize_token(selected_system_id) or (systems[0]["id"] if systems else "none")
    expansions: list[dict[str, str]] = []
    for system in systems:
        if system["id"] == selected_system:
            expansions = [{"id": addon["id"], "label": addon["name"]} for addon in system.get("addons", [])]
            break
    selected_expansion = normalize_token(selected_expansion_id) or (expansions[0]["id"] if expansions else "")
    settings = _discover_setting_options(
        project_root,
        system_id=selected_system,
        expansion_id=selected_expansion,
    )
    selected_setting = normalize_token(selected_setting_id) or (settings[0]["id"] if settings else "")
    campaigns = []
    if selected_system and selected_setting:
        campaigns = campaign_service.list_campaigns(
            system_id=selected_system,
            expansion_id=selected_expansion,
            setting_id=selected_setting,
        )
    return {
        "systems": system_options,
        "expansions": expansions,
        "settings": settings,
        "campaigns": campaigns,
        "selected_system_id": selected_system,
        "selected_expansion_id": selected_expansion,
        "selected_setting_id": selected_setting,
    }


def _find_rulebook(
    *,
    project_root: Path,
    system_id: str,
    addon_id: str,
    rulebook_id: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    systems = discover_systems(_systems_root(project_root))
    for system in systems:
        if system["id"] != system_id:
            continue
        for addon in system.get("addons", []):
            if addon["id"] != addon_id:
                continue
            for rulebook in addon.get("rulebooks", []):
                if rulebook["id"] == rulebook_id:
                    return system, addon, rulebook
    raise FileNotFoundError(f"rulebook not found: {system_id}/{addon_id}/{rulebook_id}")


def _serialize_systems(systems: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for system in systems:
        item = dict(system)
        addons: list[dict[str, Any]] = []
        for addon in system.get("addons", []):
            addon_item = dict(addon)
            addon_item["api_url"] = f"/api/systems/{system['id']}/addons/{addon['id']}"
            rulebooks: list[dict[str, Any]] = []
            for rulebook in addon.get("rulebooks", []):
                rulebook_item = dict(rulebook)
                rulebook_item["api_url"] = (
                    f"/api/systems/{system['id']}/addons/{addon['id']}/rulebooks/{rulebook['id']}"
                )
                rulebook_item["ui_url"] = (
                    f"/systems/{system['id']}/addons/{addon['id']}/rulebooks/{rulebook['id']}"
                )
                rulebooks.append(rulebook_item)
            addon_item["rulebooks"] = rulebooks
            addons.append(addon_item)
        item["addons"] = addons
        item["api_url"] = f"/api/systems/{system['id']}"
        items.append(item)
    return items


def _serialize_rulebook_payload(
    *,
    system: dict[str, Any],
    addon: dict[str, Any],
    rulebook: dict[str, Any],
    resolved_root: Path,
) -> dict[str, Any]:
    addon_root = resolved_root / "app" / "systems" / system["id"] / "addons" / addon["id"]
    markdown_path = addon_root / rulebook["markdown_path"]
    document = load_rulebook_document(markdown_path, title=rulebook["title"])
    html_path = addon_root / rulebook["html_path"] if rulebook.get("html_path") else None
    html_exists = bool(html_path and html_path.exists() and html_path.is_file())
    return {
        "system": {"id": system["id"], "name": system["name"]},
        "addon": {"id": addon["id"], "name": addon["name"]},
        "rulebook": dict(rulebook),
        "document": {
            "title": document.title,
            "markdown_path": document.markdown_path,
            "toc": [
                {
                    "level": heading.level,
                    "title": heading.title,
                    "anchor": heading.anchor,
                    "line_number": heading.line_number,
                }
                for heading in build_rulebook_toc(document, max_level=2)
            ],
            "headings_count": len(document.headings),
            "html_available": html_exists,
            "ui_url": f"/systems/{system['id']}/addons/{addon['id']}/rulebooks/{rulebook['id']}",
            "html_url": (
                f"/systems/{system['id']}/addons/{addon['id']}/rulebooks/{rulebook['id']}/html"
                if html_exists
                else ""
            ),
            "rendered_html": render_rulebook_html(document),
        },
    }


def _json_error(message: str, *, status: int):
    response = jsonify({"error": message})
    response.status_code = status
    return response


def _request_json() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def _request_actor_user_id(payload: dict[str, Any]) -> str:
    explicit = str(payload.get("actor_user_id") or "").strip()
    if explicit:
        return explicit
    current_user = getattr(g, "current_user", None)
    return str(getattr(current_user, "id", "") or "")


def _request_bearer_token() -> str:
    header = str(request.headers.get("Authorization") or "").strip()
    if not header:
        return ""
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return value.strip()


def _build_record_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("record"), dict):
        return dict(payload["record"])
    return build_record(
        record_type=payload.get("record_type") or payload.get("type"),
        title=payload.get("title"),
        slug=payload.get("slug"),
        system_id=payload.get("system_id"),
        addon_id=payload.get("addon_id"),
        setting_id=payload.get("setting_id"),
        campaign_id=payload.get("campaign_id"),
        source=payload.get("source") if isinstance(payload.get("source"), dict) else {},
        content=payload.get("content") if isinstance(payload.get("content"), dict) else {},
        metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        audit=payload.get("audit") if isinstance(payload.get("audit"), dict) else {},
        links=payload.get("links") if isinstance(payload.get("links"), list) else [],
        extensions=payload.get("extensions") if isinstance(payload.get("extensions"), dict) else {},
        record_id=payload.get("id"),
    )


def _merge_record(current: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("record"), dict):
        merged = dict(payload["record"])
        merged["id"] = current["id"]
        return merged

    merged = dict(current)
    for key in ("type", "title", "slug"):
        if key in payload:
            merged[key] = payload[key]

    if any(key in payload for key in ("system_id", "addon_id")):
        system = dict(merged.get("system") or {})
        if "system_id" in payload:
            system["id"] = payload.get("system_id")
        if "addon_id" in payload:
            system["addon_id"] = payload.get("addon_id")
        merged["system"] = system

    if any(key in payload for key in ("setting_id", "campaign_id", "system_id")):
        context = dict(merged.get("context") or {})
        if "system_id" in payload:
            context["system_id"] = payload.get("system_id")
        for key in ("setting_id", "campaign_id"):
            if key in payload:
                context[key] = payload.get(key)
        merged["context"] = context

    for key in ("source", "content", "metadata", "audit", "extensions"):
        if isinstance(payload.get(key), dict):
            nested = dict(merged.get(key) or {})
            nested.update(payload[key])
            merged[key] = nested
    if "links" in payload and isinstance(payload.get("links"), list):
        merged["links"] = payload["links"]
    return merged


def create_app(*, project_root: Path | None = None) -> Flask:
    resolved_root = (project_root or _project_root()).resolve()
    branding = _branding_asset_info(resolved_root)
    ensure_database(_db_path(resolved_root))
    auth_service = AuthService(_db_path(resolved_root))
    auth_service.ensure_user(
        username=OWNER_USERNAME,
        email=OWNER_EMAIL,
        display_name=OWNER_DISPLAY_NAME,
        password=OWNER_PASSWORD,
        role="owner",
    )
    content_service = ContentService(data_root=_data_root(resolved_root), db_path=_db_path(resolved_root))
    campaign_service = CampaignService(_content_root(resolved_root))
    app = Flask(
        __name__,
        template_folder=str(Path(__file__).resolve().parent / "templates"),
    )
    app.secret_key = os.getenv("GMFORGE_SECRET_KEY", "gmforge-dev-secret")
    app.config["GMFORGE_PROJECT_ROOT"] = str(resolved_root)
    app.config["GMFORGE_AUTH_SERVICE"] = auth_service
    app.config["GMFORGE_BRANDING"] = branding

    def _session_user():
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            return None
        loaded_session = auth_service.get_session(session_id)
        if loaded_session is None:
            session.pop("session_id", None)
            return None
        user = auth_service.get_user_by_id(loaded_session.user_id)
        if user is None or not user.is_active:
            session.pop("session_id", None)
            return None
        return user

    def _bearer_session_and_user():
        token = _request_bearer_token()
        if not token:
            return None, None
        loaded_session = auth_service.get_session(token)
        if loaded_session is None:
            return None, None
        user = auth_service.get_user_by_id(loaded_session.user_id)
        if user is None or not user.is_active:
            return None, None
        return loaded_session, user

    @app.context_processor
    def inject_auth_state() -> dict[str, Any]:
        return {
            "current_user": getattr(g, "current_user", None),
            "branding": app.config.get("GMFORGE_BRANDING", {}),
        }

    @app.before_request
    def require_login():
        g.current_user = None
        g.api_session = None
        endpoint = request.endpoint or ""
        if endpoint in {"login", "logout", "api_login", "branding_asset", "favicon", "static"}:
            return None
        if request.path.startswith("/api/"):
            g.api_session, g.current_user = _bearer_session_and_user()
            if g.current_user is not None:
                return None
            return _json_error("bearer token required", status=401)
        g.current_user = _session_user()
        if g.current_user is not None:
            return None
        next_url = request.full_path if request.query_string else request.path
        return redirect(url_for("login", next=next_url))

    @app.route("/login", methods=["GET", "POST"])
    def login() -> str:
        error = ""
        if request.method == "POST":
            user = auth_service.authenticate(
                username=str(request.form.get("username") or ""),
                password=str(request.form.get("password") or ""),
            )
            if user is None:
                error = "Invalid username or password."
            else:
                created_session = auth_service.create_session(user_id=user.id, ttl_hours=12)
                session["session_id"] = created_session.id
                target = str(request.args.get("next") or request.form.get("next") or "").strip()
                if not target.startswith("/"):
                    target = url_for("index")
                return redirect(target)
        return render_template(
            "login.html",
            error=error,
            seeded_owner={"username": OWNER_USERNAME, "email": OWNER_EMAIL},
            next_url=str(request.args.get("next") or request.form.get("next") or "").strip(),
        )

    @app.get("/assets/branding/<path:filename>")
    def branding_asset(filename: str):
        branding_root = _branding_root(resolved_root)
        asset_path = (branding_root / filename).resolve()
        if branding_root.resolve() not in asset_path.parents or not asset_path.exists() or not asset_path.is_file():
            abort(404)
        return send_file(asset_path)

    @app.get("/favicon.ico")
    def favicon():
        favicon_name = str(branding.get("favicon_name") or "")
        if not favicon_name:
            abort(404)
        return send_file(_branding_root(resolved_root) / favicon_name)

    @app.post("/api/session/login")
    def api_login():
        payload = _request_json()
        user = auth_service.authenticate(
            username=str(payload.get("username") or ""),
            password=str(payload.get("password") or ""),
        )
        if user is None:
            return _json_error("invalid username or password", status=401)
        created_session = auth_service.create_session(user_id=user.id, ttl_hours=12)
        return jsonify(
            {
                "access_token": created_session.id,
                "token_type": "Bearer",
                "expires_at": created_session.expires_at,
                "user": {
                    "id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "display_name": user.display_name,
                    "role": user.role,
                },
            }
        )

    @app.get("/api/session")
    def api_session():
        if g.current_user is None:
            return _json_error("bearer token required", status=401)
        return jsonify(
            {
                "access_token": str(getattr(g.api_session, "id", "") or ""),
                "user": {
                    "id": g.current_user.id,
                    "username": g.current_user.username,
                    "email": g.current_user.email,
                    "display_name": g.current_user.display_name,
                    "role": g.current_user.role,
                }
            }
        )

    @app.route("/logout", methods=["GET", "POST"])
    def logout():
        session_id = str(session.pop("session_id", "") or "").strip()
        if session_id:
            try:
                auth_service.revoke_session(session_id)
            except FileNotFoundError:
                pass
        return redirect(url_for("login"))

    @app.post("/api/session/logout")
    def api_logout():
        session_id = str(getattr(g.api_session, "id", "") or "").strip() or _request_bearer_token()
        if not session_id:
            return _json_error("bearer token required", status=401)
        try:
            auth_service.revoke_session(session_id)
        except FileNotFoundError:
            return _json_error("session not found", status=404)
        return jsonify({"status": "logged_out"})

    @app.get("/")
    def index() -> str:
        systems = discover_systems(_systems_root(resolved_root))
        return render_template("index.html", systems=systems)

    @app.route("/workspace/campaigns", methods=["GET", "POST"])
    def campaigns_workspace() -> str:
        error = ""
        message = ""
        selected_system_id = str(request.values.get("system_id") or "").strip()
        selected_expansion_id = str(request.values.get("expansion_id") or "").strip()
        selected_setting_id = str(request.values.get("setting_id") or "").strip()
        if request.method == "POST":
            try:
                campaign_service.create_campaign(
                    system_id=request.form.get("system_id"),
                    expansion_id=request.form.get("expansion_id") or "",
                    setting_id=request.form.get("setting_id"),
                    campaign_id=request.form.get("campaign_id"),
                    campaign_label=request.form.get("campaign_label") or "",
                    summary=request.form.get("summary") or "",
                )
                message = "Campaign created."
                selected_system_id = str(request.form.get("system_id") or "")
                selected_expansion_id = str(request.form.get("expansion_id") or "")
                selected_setting_id = str(request.form.get("setting_id") or "")
            except Exception as exc:
                error = str(exc)

        options = _build_workspace_options(
            resolved_root,
            campaign_service,
            selected_system_id=selected_system_id,
            selected_expansion_id=selected_expansion_id,
            selected_setting_id=selected_setting_id,
        )
        filters = {
            "system_id": options["selected_system_id"],
            "expansion_id": options["selected_expansion_id"],
            "setting_id": options["selected_setting_id"],
        }
        campaigns = options["campaigns"]
        return render_template(
            "campaigns.html",
            campaigns=campaigns,
            filters=filters,
            options=options,
            error=error,
            message=message,
        )

    @app.route("/workspace/records", methods=["GET", "POST"])
    def records_workspace() -> str:
        error = ""
        message = ""
        selected_system_id = str(request.values.get("system_id") or "").strip()
        selected_expansion_id = str(request.values.get("expansion_id") or "").strip()
        selected_setting_id = str(request.values.get("setting_id") or "").strip()
        if request.method == "POST":
            try:
                record = build_record(
                    record_type=request.form.get("record_type"),
                    title=request.form.get("title"),
                    slug=request.form.get("slug") or "",
                    system_id=request.form.get("system_id") or "none",
                    addon_id=request.form.get("expansion_id") or "",
                    setting_id=request.form.get("setting_id") or "",
                    campaign_id=request.form.get("campaign_id") or "",
                    content={"body": request.form.get("body") or ""},
                    metadata={
                        "tags": [tag.strip() for tag in str(request.form.get("tags") or "").split(",") if tag.strip()],
                        "summary": request.form.get("summary") or "",
                    },
                )
                content_service.create_record(record)
                message = "Record created."
                selected_system_id = str(request.form.get("system_id") or "")
                selected_expansion_id = str(request.form.get("expansion_id") or "")
                selected_setting_id = str(request.form.get("setting_id") or "")
            except Exception as exc:
                error = str(exc)

        options = _build_workspace_options(
            resolved_root,
            campaign_service,
            selected_system_id=selected_system_id,
            selected_expansion_id=selected_expansion_id,
            selected_setting_id=selected_setting_id,
        )
        filters = {
            "query": str(request.values.get("q") or "").strip(),
            "type": str(request.values.get("type") or "").strip(),
            "system_id": options["selected_system_id"],
            "addon_id": options["selected_expansion_id"],
            "setting_id": options["selected_setting_id"],
            "campaign_id": str(request.values.get("campaign_id") or "").strip() or (
                str(options["campaigns"][0].get("id") or "") if options["campaigns"] else ""
            ),
            "tag": str(request.values.get("tag") or "").strip(),
        }
        store_filters = {key: value for key, value in filters.items() if key != "query" and value}
        records = (
            content_service.search_records(query=filters["query"], filters=store_filters)
            if filters["query"]
            else content_service.list_records(filters=store_filters)
        )
        return render_template(
            "records.html",
            records=records,
            filters=filters,
            options=options,
            error=error,
            message=message,
        )

    @app.get("/api/systems")
    def api_systems():
        systems = discover_systems(_systems_root(resolved_root))
        return jsonify({"systems": _serialize_systems(systems)})

    @app.get("/api/systems/<system_id>")
    def api_system(system_id: str):
        systems = discover_systems(_systems_root(resolved_root))
        for system in systems:
            if system["id"] == system_id:
                return jsonify({"system": _serialize_systems([system])[0]})
        abort(404)

    @app.get("/api/systems/<system_id>/addons/<addon_id>")
    def api_addon(system_id: str, addon_id: str):
        systems = discover_systems(_systems_root(resolved_root))
        for system in systems:
            if system["id"] != system_id:
                continue
            for addon in system.get("addons", []):
                if addon["id"] == addon_id:
                    payload = dict(addon)
                    payload["system_id"] = system_id
                    payload["api_url"] = f"/api/systems/{system_id}/addons/{addon_id}"
                    return jsonify({"addon": payload})
        abort(404)

    @app.get("/api/systems/<system_id>/addons/<addon_id>/rulebooks/<rulebook_id>")
    def api_rulebook(system_id: str, addon_id: str, rulebook_id: str):
        try:
            system, addon, rulebook = _find_rulebook(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                rulebook_id=rulebook_id,
            )
        except FileNotFoundError:
            abort(404)
        return jsonify(
            _serialize_rulebook_payload(
                system=system,
                addon=addon,
                rulebook=rulebook,
                resolved_root=resolved_root,
            )
        )

    @app.get("/api/campaigns")
    def api_campaigns():
        system_id = str(request.args.get("system_id") or "").strip()
        expansion_id = str(request.args.get("expansion_id") or "").strip()
        setting_id = str(request.args.get("setting_id") or "").strip()
        if not system_id or not setting_id:
            return _json_error("system_id and setting_id are required", status=400)
        return jsonify(
            {
                "campaigns": campaign_service.list_campaigns(
                    system_id=system_id,
                    expansion_id=expansion_id,
                    setting_id=setting_id,
                )
            }
        )

    @app.post("/api/campaigns")
    def api_create_campaign():
        payload = _request_json()
        try:
            campaign = campaign_service.create_campaign(
                system_id=payload.get("system_id"),
                expansion_id=payload.get("expansion_id") or "",
                setting_id=payload.get("setting_id"),
                campaign_id=payload.get("campaign_id"),
                campaign_label=payload.get("campaign_label") or payload.get("label") or "",
                summary=payload.get("summary") or "",
            )
        except FileExistsError as exc:
            return _json_error(str(exc), status=409)
        except Exception as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"campaign": campaign}), 201

    @app.get("/api/records")
    def api_records():
        query = str(request.args.get("q") or "").strip()
        filters = {
            "type": str(request.args.get("type") or "").strip(),
            "system_id": str(request.args.get("system_id") or "").strip(),
            "addon_id": str(request.args.get("addon_id") or request.args.get("expansion_id") or "").strip(),
            "setting_id": str(request.args.get("setting_id") or "").strip(),
            "campaign_id": str(request.args.get("campaign_id") or "").strip(),
            "status": str(request.args.get("status") or "").strip(),
            "tag": str(request.args.get("tag") or "").strip(),
        }
        clean_filters = {key: value for key, value in filters.items() if value}
        items = content_service.search_records(query=query, filters=clean_filters) if query else content_service.list_records(filters=clean_filters)
        return jsonify({"records": items})

    @app.post("/api/records")
    def api_create_record():
        payload = _request_json()
        try:
            record = _build_record_from_payload(payload)
            created = content_service.create_record(
                record,
                actor_user_id=_request_actor_user_id(payload),
                request_kind=str(payload.get("request_kind") or "manual"),
                provider_id=str(payload.get("provider_id") or ""),
                prompt_text=str(payload.get("prompt_text") or ""),
            )
        except FileExistsError as exc:
            return _json_error(str(exc), status=409)
        except Exception as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"record": created}), 201

    @app.get("/api/records/<record_id>")
    def api_record(record_id: str):
        try:
            return jsonify({"record": content_service.get_record(record_id)})
        except FileNotFoundError:
            return _json_error(f"record not found: {record_id}", status=404)

    @app.put("/api/records/<record_id>")
    def api_update_record(record_id: str):
        payload = _request_json()
        try:
            current = content_service.get_record(record_id)
            merged = _merge_record(current, payload)
            updated = content_service.update_record(
                record_id,
                merged,
                actor_user_id=_request_actor_user_id(payload),
                request_kind=str(payload.get("request_kind") or "manual"),
                provider_id=str(payload.get("provider_id") or ""),
                prompt_text=str(payload.get("prompt_text") or ""),
            )
        except FileNotFoundError:
            return _json_error(f"record not found: {record_id}", status=404)
        except Exception as exc:
            return _json_error(str(exc), status=400)
        return jsonify({"record": updated})

    @app.delete("/api/records/<record_id>")
    def api_delete_record(record_id: str):
        payload = _request_json()
        try:
            result = content_service.delete_record(
                record_id,
                actor_user_id=_request_actor_user_id(payload),
                request_kind=str(payload.get("request_kind") or "manual"),
            )
        except FileNotFoundError:
            return _json_error(f"record not found: {record_id}", status=404)
        return jsonify(result)

    @app.get("/systems/<system_id>/addons/<addon_id>/rulebooks/<rulebook_id>")
    def rulebook_view(system_id: str, addon_id: str, rulebook_id: str) -> str:
        try:
            system, addon, rulebook = _find_rulebook(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                rulebook_id=rulebook_id,
            )
        except FileNotFoundError:
            abort(404)

        addon_root = resolved_root / "app" / "systems" / system_id / "addons" / addon_id
        markdown_path = addon_root / rulebook["markdown_path"]
        document = load_rulebook_document(markdown_path, title=rulebook["title"])
        html_path = addon_root / rulebook["html_path"] if rulebook.get("html_path") else None
        html_exists = bool(html_path and html_path.exists() and html_path.is_file())
        return render_template(
            "rulebook.html",
            system=system,
            addon=addon,
            rulebook=rulebook,
            document=document,
            toc=build_rulebook_toc(document, max_level=2),
            rendered_html=render_rulebook_html(document),
            html_exists=html_exists,
            raw_html_url=url_for(
                "rulebook_html_asset",
                system_id=system_id,
                addon_id=addon_id,
                rulebook_id=rulebook_id,
            )
            if html_exists
            else "",
        )

    @app.get("/systems/<system_id>/addons/<addon_id>/rulebooks/<rulebook_id>/html")
    def rulebook_html_asset(system_id: str, addon_id: str, rulebook_id: str):
        try:
            _, _, rulebook = _find_rulebook(
                project_root=resolved_root,
                system_id=system_id,
                addon_id=addon_id,
                rulebook_id=rulebook_id,
            )
        except FileNotFoundError:
            abort(404)
        addon_root = resolved_root / "app" / "systems" / system_id / "addons" / addon_id
        html_path = addon_root / rulebook["html_path"]
        if not html_path.exists() or not html_path.is_file():
            abort(404)
        return send_file(html_path)

    return app
