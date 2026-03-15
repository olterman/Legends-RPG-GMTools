from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.search import VectorIndexService


@dataclass(frozen=True)
class GenerationRequest:
    title: str
    record_type: str
    system_id: str
    addon_id: str
    setting_id: str
    campaign_id: str
    focus_query: str
    notes: str
    source_kind: str
    provider_id: str


@dataclass(frozen=True)
class PreparedGenerationContext:
    request: GenerationRequest
    snippets: list[dict[str, Any]]
    summary: str
    tags: list[str]
    sections: list[dict[str, str]]
    prompt_text: str
    retrieval_query: str


class LocalStructuredDraftProvider:
    provider_id = "local_structured_draft"
    provider_label = "Local Structured Draft"

    def build(self, request: GenerationRequest, *, vector_service: VectorIndexService) -> dict[str, Any]:
        context = prepare_generation_context(request, vector_service=vector_service)
        body = self._render_body(request, context.sections, context.snippets)
        return build_generation_result(
            provider_id=self.provider_id,
            provider_label=self.provider_label,
            context=context,
            body=body,
        )

    def _build_summary(self, request: GenerationRequest, snippets: list[dict[str, Any]]) -> str:
        if snippets:
            lead = snippets[0]
            return (
                f"Draft {request.record_type.replace('_', ' ')} for {request.title or request.focus_query}, "
                f"grounded in {lead['title']} and related scoped setting material."
            )
        return f"Draft {request.record_type.replace('_', ' ')} for {request.title or request.focus_query}."

    def _build_tags(self, request: GenerationRequest, snippets: list[dict[str, Any]]) -> list[str]:
        tags: list[str] = []
        for candidate in (
            request.record_type,
            request.setting_id,
            request.campaign_id,
            request.focus_query.split(" ")[0] if request.focus_query else "",
        ):
            text = str(candidate or "").strip().lower().replace(" ", "_")
            if text and text not in tags:
                tags.append(text)
        for snippet in snippets[:3]:
            token = str(snippet.get("title") or "").strip().lower().replace(" ", "_")
            if token and token not in tags:
                tags.append(token)
        return tags[:8]

    def _build_sections(self, request: GenerationRequest, snippets: list[dict[str, Any]]) -> list[dict[str, str]]:
        thematic = " ".join(str(snippet.get("text") or "") for snippet in snippets[:3]).lower()
        sections = [
            {
                "heading": "Concept",
                "content": (
                    f"{request.title or request.focus_query} is being drafted as a {request.record_type.replace('_', ' ')} "
                    f"within {request.setting_id or 'the current setting'}, focused on {request.focus_query.lower()}."
                ),
            },
            {
                "heading": "Context Fit",
                "content": (
                    "This draft should align with the retrieved setting material, especially its established tone, "
                    "regional pressures, and social tensions."
                ),
            },
        ]
        if request.notes:
            sections.append({"heading": "Author Notes", "content": request.notes})
        if "religion" in thematic or "god" in thematic:
            sections.append(
                {
                    "heading": "Religious Pressure",
                    "content": "Faith, taboo, and old pacts should matter in how this draft is written and framed.",
                }
            )
        if any(word in thematic for word in ("war", "ruin", "scar", "frontier", "mercenary")):
            sections.append(
                {
                    "heading": "Conflict Pressure",
                    "content": "The draft should preserve evidence of instability, danger, or pressure from the surrounding region.",
                }
            )
        if snippets:
            sections.append(
                {
                    "heading": "Source Anchors",
                    "content": "; ".join(
                        f"{snippet['title']} / {snippet['heading']}" for snippet in snippets[:4]
                    ),
                }
            )
        target_guidance = _record_type_guidance(request.record_type)
        if target_guidance:
            sections.append({"heading": "Target Shape", "content": target_guidance["summary"]})
        return sections

    def _render_body(
        self,
        request: GenerationRequest,
        sections: list[dict[str, str]],
        snippets: list[dict[str, Any]],
    ) -> str:
        lines = [f"# {request.title or 'Untitled Draft'}", ""]
        for section in sections:
            lines.append(f"## {section['heading']}")
            lines.append(section["content"])
            lines.append("")
        if snippets:
            lines.append("## Retrieved Snippets")
            for snippet in snippets[:5]:
                lines.append(f"- {snippet['title']} / {snippet['heading']}: {snippet['text']}")
        return "\n".join(lines).strip()


class ExternalAIDraftProvider:
    provider_id = "external_ai"
    provider_label = "External AI"

    def __init__(self, *, plugin: dict[str, Any], settings: dict[str, Any]) -> None:
        self.plugin = dict(plugin)
        self.settings = dict(settings)

    def build(self, request: GenerationRequest, *, vector_service: VectorIndexService) -> dict[str, Any]:
        context = prepare_generation_context(request, vector_service=vector_service)
        body = self.generate_text(prompt=self._render_provider_prompt(context))
        return build_generation_result(
            provider_id=self.provider_id,
            provider_label=self.provider_label,
            context=context,
            body=body,
        )

    def generate_text(self, *, prompt: str) -> str:
        raise NotImplementedError

    def _setting(self, key: str) -> str:
        return str(self.settings.get(key) or "").strip()

    def _render_provider_prompt(self, context: PreparedGenerationContext) -> str:
        request = context.request
        target_guidance = _record_type_guidance(request.record_type)
        lines = [
            "Write a polished markdown draft for GMForge.",
            "Use the retrieved context faithfully and avoid contradicting it.",
            "If the context leaves something unclear, use restrained invention that fits the visible tone and taxonomy.",
            "Keep the result useful for later editing inside GMForge.",
            "",
            f"Draft title: {request.title or 'Untitled Draft'}",
            f"Record type: {request.record_type}",
            f"System: {request.system_id or 'none'}",
            f"Expansion: {request.addon_id or 'none'}",
            f"Setting: {request.setting_id or 'none'}",
            f"Campaign: {request.campaign_id or 'none'}",
            f"Summary target: {context.summary}",
            f"Tags target: {', '.join(context.tags)}",
            f"Retrieval query used: {context.retrieval_query}",
            "",
            f"Focus: {request.focus_query}",
        ]
        if request.notes:
            lines.extend(["", "Author notes:", request.notes])
        if target_guidance:
            lines.extend(["", "Target structure:", target_guidance["prompt"]])
        if context.sections:
            lines.extend(["", "Suggested sections:"])
            for section in context.sections:
                lines.append(f"- {section['heading']}: {section['content']}")
        if context.snippets:
            lines.extend(["", "Retrieved context:"])
            for index, snippet in enumerate(context.snippets, start=1):
                lines.append(
                    f"[{index}] [{snippet['source_kind']}] {snippet['title']} / {snippet['heading']}: {snippet['text']}"
                )
        lines.extend(
            [
                "",
                "Return markdown only.",
                "Start with a level-one title, then use clear sections.",
                "Do not switch into encounter stat-block output unless the record type explicitly calls for an encounter.",
            ]
        )
        return "\n".join(lines).strip()


def _render_prompt_packet(request: GenerationRequest, snippets: list[dict[str, Any]]) -> str:
    lines = [
        f"Draft title: {request.title}",
        f"Record type: {request.record_type}",
        f"System: {request.system_id or 'none'}",
        f"Expansion: {request.addon_id or 'none'}",
        f"Setting: {request.setting_id or 'none'}",
        f"Campaign: {request.campaign_id or 'none'}",
        "",
        f"Focus: {request.focus_query}",
    ]
    if request.notes:
        lines.extend(["", "Author notes:", request.notes])
    if snippets:
        lines.append("")
        lines.append("Retrieved context:")
        for snippet in snippets:
            lines.append(f"- [{snippet['source_kind']}] {snippet['title']} / {snippet['heading']}")
            lines.append(f"  {snippet['text']}")
    return "\n".join(lines).strip()


def prepare_generation_context(
    request: GenerationRequest,
    *,
    vector_service: VectorIndexService,
) -> PreparedGenerationContext:
    retrieval_query = _build_retrieval_query(request)
    filters = {
        "system_id": request.system_id,
        "addon_id": request.addon_id,
        "setting_id": request.setting_id,
        "campaign_id": request.campaign_id,
        "source_kind": request.source_kind,
    }
    snippets = vector_service.query(q=retrieval_query, k=8, filters=filters)
    local_provider = LocalStructuredDraftProvider()
    summary = local_provider._build_summary(request, snippets)
    tags = local_provider._build_tags(request, snippets)
    sections = local_provider._build_sections(request, snippets)
    prompt_text = _render_prompt_packet(request, snippets)
    return PreparedGenerationContext(
        request=request,
        snippets=snippets,
        summary=summary,
        tags=tags,
        sections=sections,
        prompt_text=prompt_text,
        retrieval_query=retrieval_query,
    )


def build_generation_result(
    *,
    provider_id: str,
    provider_label: str,
    context: PreparedGenerationContext,
    body: str,
) -> dict[str, Any]:
    request = context.request
    proposed_record = {
        "record_type": request.record_type,
        "title": request.title or "Untitled Draft",
        "system_id": request.system_id,
        "addon_id": request.addon_id,
        "setting_id": request.setting_id,
        "campaign_id": request.campaign_id,
        "summary": context.summary,
        "tags": context.tags,
        "body": body,
        "status": "draft",
    }
    return {
        "provider_id": provider_id,
        "provider_label": provider_label,
        "prompt_text": context.prompt_text,
        "summary": context.summary,
        "tags": context.tags,
        "sections": context.sections,
        "snippets": context.snippets,
        "proposed_record": proposed_record,
    }


class GenerationService:
    def __init__(self, *, vector_service: VectorIndexService, plugin_service: Any | None = None) -> None:
        self.vector_service = vector_service
        self.providers = {
            LocalStructuredDraftProvider.provider_id: LocalStructuredDraftProvider(),
        }
        if plugin_service is not None:
            for provider in plugin_service.load_generation_providers():
                provider_id = str(getattr(provider, "provider_id", "") or "").strip()
                if provider_id:
                    self.providers[provider_id] = provider

    def list_providers(self) -> list[dict[str, str]]:
        return [
            {
                "id": provider.provider_id,
                "label": provider.provider_label,
                "warmup_note": "First request may be slower while the local model loads."
                if provider.provider_id == "ollama_local"
                else "",
            }
            for provider in self.providers.values()
        ]

    def build_draft(self, request: GenerationRequest) -> dict[str, Any]:
        provider = self.providers.get(request.provider_id) or self.providers[LocalStructuredDraftProvider.provider_id]
        return provider.build(request, vector_service=self.vector_service)


def _build_retrieval_query(request: GenerationRequest) -> str:
    base = str(request.focus_query or "").strip()
    hints = _record_type_guidance(request.record_type)
    extra_terms = " ".join(hints["retrieval_terms"]) if hints else ""
    if not extra_terms:
        return base
    return f"{base} {extra_terms}".strip()


def _record_type_guidance(record_type: str) -> dict[str, Any] | None:
    kind = str(record_type or "").strip().lower()
    guides: dict[str, dict[str, Any]] = {
        "village": {
            "retrieval_terms": ["village", "settlement", "economy", "culture", "region", "inn"],
            "summary": "Favor settlement-level framing: overview, economy, culture, tensions, and notable inn.",
            "prompt": (
                "For a village draft, write in-place setting material. Prefer sections like Overview, Economy, Culture, "
                "Local Tensions, and Notable Inn. Avoid combat encounter structure, stat blocks, or adventure-format output."
            ),
        },
        "city": {
            "retrieval_terms": ["city", "settlement", "districts", "trade", "politics", "inn"],
            "summary": "Favor urban framing: overview, politics, districts, trade, and notable institutions.",
            "prompt": (
                "For a city draft, focus on political identity, districts, trade life, major tensions, and a few notable places. "
                "Do not format it as an encounter or NPC sheet."
            ),
        },
        "inn": {
            "retrieval_terms": ["inn", "proprietor", "clientele", "atmosphere", "rumor"],
            "summary": "Favor inn-level framing: atmosphere, proprietor, clientele, notable feature, and rumor or hook.",
            "prompt": (
                "For an inn draft, prefer sections like Overview, Atmosphere, Proprietor, Clientele, Notable Feature, and Rumor or Hook."
            ),
        },
        "region": {
            "retrieval_terms": ["region", "culture", "history", "politics", "landscape"],
            "summary": "Favor broad world framing: landscape, culture, history, politics, and conflicts.",
            "prompt": (
                "For a region draft, stay at regional scale. Cover landscape, history, culture, politics, and active pressures."
            ),
        },
        "subregion": {
            "retrieval_terms": ["subregion", "landscape", "villages", "rivers", "landmarks"],
            "summary": "Favor subregional framing: place identity, notable settlements, terrain, and pressures.",
            "prompt": (
                "For a subregion draft, describe the local terrain, settlements, mood, and the pressures tying the area together."
            ),
        },
        "people": {
            "retrieval_terms": ["people", "culture", "history", "relationships", "identity"],
            "summary": "Favor cultural framing: identity, history, relationships, and worldview.",
            "prompt": (
                "For a people draft, focus on identity, history, culture, relationships, and worldview rather than place description."
            ),
        },
    }
    return guides.get(kind)
