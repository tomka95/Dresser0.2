"""AI provider abstraction layer for supporting multiple LLM providers (Gemini, OpenAI, etc.).

Split into a package (P3.6, ARCHITECTURE_AUDIT R8 -- was one 841-line module):
  core.py           -- AIProvider (the active surface: generate_structured,
                        embed_texts, chat) + get_ai_provider() singleton.
  _legacy_outfit.py -- the legacy multi-item outfit-photo detect/generate
                        methods, mixed into AIProvider so its public surface
                        is unchanged for every caller.
  _json.py          -- extract_json_metadata, the shared structured-output
                        JSON parser.

`from app.platform.ai_provider import ...` is unchanged for every existing
caller -- AIProvider, get_ai_provider, extract_json_metadata, and DetectedItem
are all re-exported here exactly as they were importable from the single
module before the split.
"""
from app.platform.ai_provider.core import AIProvider, DetectedItem, get_ai_provider
from app.platform.ai_provider._json import extract_json_metadata

__all__ = ["AIProvider", "DetectedItem", "get_ai_provider", "extract_json_metadata"]
