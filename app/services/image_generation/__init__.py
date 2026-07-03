"""Image-GENERATION provider seam (Wave 2) — public surface.

See base.py for the seam contract. Generated images are CANDIDATES only; the
vision-verify gate decides whether they are ever shown.
"""
from app.services.image_generation.base import (
    MAX_GENERATED_BYTES,
    GenerationBudget,
    GenerationProvider,
    GenerationRequest,
    GenerationResult,
    NullGenerationProvider,
    get_generation_provider,
    list_available_providers,
    sniff_generated_image,
)
from app.services.image_generation.prompt import build_generation_prompt

__all__ = [
    "MAX_GENERATED_BYTES",
    "GenerationBudget",
    "GenerationProvider",
    "GenerationRequest",
    "GenerationResult",
    "NullGenerationProvider",
    "build_generation_prompt",
    "get_generation_provider",
    "list_available_providers",
    "sniff_generated_image",
]
