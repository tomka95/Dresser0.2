"""The ONE shared generation prompt (all providers use the same wording).

A single deterministic prompt keeps the bake-off honest: provider differences in
output quality are provider differences, not prompt differences.

INVARIANTS (tests assert these — do not weaken):
  * PRESERVE — the garment must be reproduced exactly (shape, colors, pattern,
    texture, and any existing text/logos/labels/graphics).
  * NO-ADD — the model must not invent logos, text, brand marks, tags or
    decoration that are not visible in the input. This is why brand/name are
    deliberately EXCLUDED from the prompt: naming a brand invites the model to
    paint its logo onto the garment.
  * NO SCENE — no person, mannequin, hangers or props; plain studio background.
  * DETERMINISTIC — same request in, same prompt out. No randomness.
"""
from __future__ import annotations

from app.services.image_generation.base import GenerationRequest

_BASE_PROMPT = (
    "A clean e-commerce product photo of this exact garment, front view, centered "
    "on a plain light-neutral studio background with soft even lighting. "
    "Preserve the garment EXACTLY: same shape, colors, pattern, fabric texture, "
    "and any text, logos, labels or graphics precisely as they appear in the "
    "input. Do NOT add any logo, text, brand mark, tag, or decoration that is "
    "not visible in the input. Do not change the garment's color or pattern. "
    "No person, no mannequin, no hangers, no props, no shadows of other objects."
)

_VOWELS = "aeiou"


def build_generation_prompt(req: GenerationRequest) -> str:
    """Build the shared prompt, appending a short attribute hint when present.

    Only category/color/pattern feed the hint ("The garment is a black striped
    hoodie."); name/brand never enter the prompt (see NO-ADD invariant above).
    Deterministic — a pure function of the request's attributes.
    """
    color = (req.color or "").strip().lower()
    pattern = (req.pattern or "").strip().lower()
    category = (req.category or "").strip().lower()

    words = [w for w in (color, pattern, category or ("garment" if (color or pattern) else "")) if w]
    if not words:
        return _BASE_PROMPT

    phrase = " ".join(words)
    article = "an" if phrase[0] in _VOWELS else "a"
    return f"{_BASE_PROMPT} The garment is {article} {phrase}."
