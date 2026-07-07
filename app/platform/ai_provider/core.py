"""AIProvider: the Gemini client wrapper (structured generation, embeddings,
the stylist chat tool-loop).

Split from the god-module app/platform/ai_provider.py (P3.6,
ARCHITECTURE_AUDIT R8): this file holds the ACTIVE, widely-used surface
(generate_structured, embed_texts, chat) that the Gmail extraction pipeline,
photo detection, enrichment, embeddings, and the AI Stylist all call today.
The legacy multi-item outfit-photo detect/generate methods live in
_legacy_outfit.py and are mixed in below so AIProvider keeps exposing every
method callers already use -- the public surface is unchanged.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types

from app.core.config import settings
from app.platform.ai_provider._legacy_outfit import _LegacyOutfitGenerationMixin

logger = logging.getLogger(__name__)


@dataclass
class DetectedItem:
    """Represents a detected clothing item."""
    name: str


class AIProvider(_LegacyOutfitGenerationMixin):
    """Abstraction layer for AI providers (Gemini, OpenAI, etc.)."""

    def __init__(self):
        """Initialize the AI provider based on configuration."""
        provider = settings.LLM_PROVIDER

        if provider == "gemini":
            self._provider = "gemini"
            # Pass API key explicitly from settings, or let it read from GOOGLE_API_KEY env var
            api_key = settings.GEMINI_API_KEY
            if api_key:
                self._client = genai.Client(api_key=api_key)
            else:
                # Fallback: let genai.Client() read from GOOGLE_API_KEY environment variable
                self._client = genai.Client()
        else:
            raise ValueError(f"Unsupported LLM provider: {provider}")

    def generate_structured(
        self,
        *,
        model: str,
        system_instruction: str,
        user_text: str,
        response_schema: Any,
        image_parts: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.0,
        media_resolution: Optional[Any] = None,
    ):
        """Synchronous structured-output generation (the phase-3c receipt extractor).

        Forces valid typed JSON via responseMimeType=application/json + responseSchema,
        so the caller NEVER regexes the model output. Returns the raw
        GenerateContentResponse so the caller can read `.parsed` / `.text` and
        `.usage_metadata` (for cost instrumentation).

        Kept synchronous on purpose: the extraction pass mirrors the 3b fetch
        service (sync, ThreadPoolExecutor), so a blocking SDK call inside a worker
        thread is the right shape. This reuses the single Gemini SDK path; it does
        NOT add a new provider integration.

        `system_instruction` and `user_text` are kept separate so untrusted email
        content (user_text) can never be confused with the extraction rules
        (system_instruction) — the prompt-injection boundary.
        """
        contents_parts: List[Any] = []
        if image_parts:
            contents_parts.extend(image_parts)
        contents_parts.append({"text": user_text})

        config_kwargs: Dict[str, Any] = dict(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=response_schema,
            temperature=temperature,
        )
        # media_resolution=LOW lets the vision-verify pass pay for color+garment
        # recognition without OCR-grade token cost. Optional / additive.
        if media_resolution is not None:
            config_kwargs["media_resolution"] = media_resolution
        config = types.GenerateContentConfig(**config_kwargs)
        return self._client.models.generate_content(
            model=model,
            contents=contents_parts,
            config=config,
        )

    def embed_texts(
        self,
        texts: List[str],
        *,
        model: str,
        dim: int,
        task_type: str = "RETRIEVAL_DOCUMENT",
    ) -> List[List[float]]:
        """Embed one or more short product strings to fixed-width vectors.

        Wave S0 Branch B: the item-embedding seam. Synchronous (mirrors
        generate_structured — enrichment runs in a background thread, so a blocking
        SDK call is the right shape). `output_dimensionality=dim` pins the width to
        the vector(dim) column declared in migration 0018 (768; gemini-embedding-001's
        native width is 3072, truncated via MRL). `task_type=RETRIEVAL_DOCUMENT` is
        correct for indexing closet
        items; a query-time embed would pass RETRIEVAL_QUERY.

        The input is product attribute text ONLY (brand/subcategory/color/pattern/…),
        never image bytes or PII — see app/services/embeddings.build_canonical_text.
        Returns one vector per input, in order. Raises on API failure (the caller —
        enrich_item — swallows it so a transient embed miss never breaks enrichment).
        """
        if not texts:
            return []
        resp = self._client.models.embed_content(
            model=model,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=dim,
            ),
        )
        # google-genai returns .embeddings[i].values (list[float]) per input.
        return [list(e.values) for e in resp.embeddings]

    def chat(
        self,
        *,
        model: str,
        system_instruction: str,
        contents: List[Any],
        tool_declarations: Optional[List[Dict[str, Any]]] = None,
        tool_executor: Optional[Any] = None,
        on_text: Optional[Any] = None,
        on_tool: Optional[Any] = None,
        on_usage: Optional[Any] = None,
        temperature: float = 0.4,
        max_tool_rounds: int = 6,
    ) -> str:
        """The stylist tool-calling loop (Wave S2): stream -> dispatch -> repeat.

        Synchronous by design (the SSE route runs it in a worker thread and
        forwards events to the async stream). Each round streams one model
        response; text deltas go to ``on_text(text)`` as they arrive; function
        calls are collected, dispatched through ``tool_executor(name, args)``
        (which is expected to be fail-closed and to AUTHORIZE nothing — the
        executor's closure owns tenant scoping), and their responses are
        appended for the next round. The loop hard-stops after
        ``max_tool_rounds`` rounds by disabling tools for one final,
        text-only round — the model can never spin forever.

        ``on_tool(name, phase)`` fires with phase 'start'/'end' around each
        dispatch (drives SSE progress). ``on_usage(model, response_chunk)``
        receives the last chunk of each round for REAL usage_metadata
        accounting. Returns the final assistant text.
        """
        contents = list(contents)
        final_text_parts: List[str] = []
        rounds = 0

        while True:
            tools_enabled = bool(tool_declarations) and rounds < max_tool_rounds
            config_kwargs: Dict[str, Any] = dict(
                system_instruction=system_instruction,
                temperature=temperature,
                # Manual dispatch only: the SDK must never call anything itself.
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=True
                ),
            )
            if tools_enabled:
                config_kwargs["tools"] = [
                    types.Tool(
                        function_declarations=[
                            types.FunctionDeclaration(**decl)
                            for decl in tool_declarations
                        ]
                    )
                ]
            config = types.GenerateContentConfig(**config_kwargs)

            stream = self._client.models.generate_content_stream(
                model=model, contents=contents, config=config
            )

            round_text_parts: List[str] = []
            function_calls: List[Any] = []
            last_chunk = None
            for chunk in stream:
                last_chunk = chunk
                candidates = getattr(chunk, "candidates", None) or []
                if not candidates:
                    continue
                content = getattr(candidates[0], "content", None)
                parts = getattr(content, "parts", None) or []
                for part in parts:
                    fc = getattr(part, "function_call", None)
                    if fc is not None:
                        function_calls.append(fc)
                        continue
                    text = getattr(part, "text", None)
                    if text:
                        round_text_parts.append(text)
                        if on_text is not None:
                            on_text(text)

            if on_usage is not None and last_chunk is not None:
                on_usage(model, last_chunk)
            final_text_parts.extend(round_text_parts)

            if not function_calls:
                return "".join(final_text_parts)

            # Echo the model's function-call turn, then answer each call.
            contents.append(
                types.Content(
                    role="model",
                    parts=[types.Part(function_call=fc) for fc in function_calls],
                )
            )
            response_parts: List[Any] = []
            for fc in function_calls:
                name = getattr(fc, "name", "") or ""
                args = dict(getattr(fc, "args", None) or {})
                if on_tool is not None:
                    on_tool(name, "start")
                if tool_executor is not None:
                    result = tool_executor(name, args)
                else:
                    result = {"error": "no tools available"}
                if on_tool is not None:
                    on_tool(name, "end")
                response_parts.append(
                    types.Part.from_function_response(name=name, response=result)
                )
            contents.append(types.Content(role="user", parts=response_parts))
            rounds += 1


# Module-level singleton instance
_ai_provider: Optional[AIProvider] = None


def get_ai_provider() -> AIProvider:
    """Get or create the singleton AI provider instance."""
    global _ai_provider
    if _ai_provider is None:
        _ai_provider = AIProvider()
    return _ai_provider
