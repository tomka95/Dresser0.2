"""The shared generation prompt (flux / seedream) + nano's logo-hardened variant.

A single deterministic base prompt keeps the bake-off honest: provider differences in
output quality are provider differences, not prompt differences. The ONE exception is
build_nano_generation_prompt, which appends a provider-specific anti-logo-hallucination
guard for nano_banana ONLY (Gemini is the provider that duplicates/invents brand marks);
flux and seedream keep the base prompt verbatim.

ISOLATION AT GENERATION TIME
----------------------------
No usable segmentation mask is available (Gemini cannot emit one — see
photo_closet/detection.py), so the stored input can be a full-scene box crop with
a person, background, and several garments. The generation (image-editing) model
does the isolation itself: the prompt tells it to EXTRACT ONLY the single target
garment and drop the person/background/other garments. It is conditioned on the
target garment's identifying attributes (category + color + pattern + name) so it
picks the RIGHT garment when several are in frame.

INVARIANTS (tests assert these — do not weaken):
  * ISOLATE — extract only the ONE target garment; remove the person, the scene,
    and every other garment/accessory.
  * PRESERVE — the target garment is reproduced exactly (shape, colors, pattern,
    texture, and any existing text/logos/labels/graphics).
  * NO-ADD — the model must not invent logos, text, brand marks, tags or
    decoration not visible on the target garment. BRAND is still excluded from
    the prompt (naming a brand invites the model to paint its logo); NAME is now
    included only to disambiguate WHICH garment to extract, still under NO-ADD.
  * NO SCENE — no person, mannequin, hangers or props; plain studio background.
  * DETERMINISTIC — same request in, same prompt out. No randomness.
"""
from __future__ import annotations

from app.services.image_generation.base import GenerationRequest

_BASE_PROMPT = (
    "The input is a real photo that may contain a person, a background, and several "
    "clothing items. Extract ONLY the single target garment identified below and "
    "produce a clean e-commerce product photo of just that one garment, front view, "
    "centered on a plain light-neutral studio background with soft even lighting. "
    "REMOVE the person (face, skin, hair, hands), the background and scene, and every "
    "OTHER garment or accessory that is not the target garment. "
    "Preserve the target garment EXACTLY: same shape, colors, pattern, fabric "
    "texture, and any text, logos, labels or graphics precisely as they appear in "
    "the input. Do NOT add any logo, text, brand mark, tag, or decoration that is "
    "not visible on the target garment. Do not change its color or pattern. "
    "No person, no mannequin, no hangers, no props, no shadows of other objects."
)

_VOWELS = "aeiou"

# nano_banana-SPECIFIC hardening. Gemini image gen is the provider that hallucinates
# logos — it duplicates an existing mark (a twin Nike swoosh at the collar) or paints a
# fake brand label onto a plain garment. The verify gate catches these (-> crop fallback)
# but each miss wastes a generation. This clause is appended ONLY to nano's prompt (flux /
# seedream keep the shared prompt untouched, so the bake-off stays honest for them). It is
# ADDITIVE — it strengthens, never relaxes, the base ISOLATE / PRESERVE / NO-SCENE rules.
_NANO_LOGO_GUARD = (
    " CRITICAL — LOGOS, TEXT AND BRAND MARKS: reproduce ONLY the logos, text, labels or "
    "brand marks that are ALREADY visibly printed on the target garment in the input, each "
    "in its exact original position, size, orientation and count. Do NOT add, invent, "
    "duplicate, mirror, complete, relocate, resize or re-draw any logo, wordmark, monogram, "
    "emblem, tag, or graphic. If the target garment shows no logo or text, leave it "
    "completely plain — never place a brand mark on a blank area. When unsure whether a "
    "mark is present, omit it. Reproduce exactly what is visible on the garment, nothing more."
)


def build_generation_prompt(req: GenerationRequest) -> str:
    """Build the shared prompt, appending a target-garment descriptor to condition
    the isolation on which garment to extract.

    category/color/pattern build the descriptor phrase ("the black striped top");
    ``name`` is appended in quotes to disambiguate when several similar garments
    are in frame. ``brand`` is NEVER included (NO-ADD invariant — naming a brand
    invites a painted-on logo). Deterministic — a pure function of the attributes.
    """
    color = (req.color or "").strip().lower()
    pattern = (req.pattern or "").strip().lower()
    category = (req.category or "").strip().lower()
    name = (req.name or "").strip()

    words = [w for w in (color, pattern, category or ("garment" if (color or pattern) else "")) if w]
    phrase = " ".join(words)

    if phrase and name:
        target = f' The target garment is the {phrase} ("{name}").'
    elif phrase:
        article = "an" if phrase[0] in _VOWELS else "a"
        target = f" The target garment is {article} {phrase}."
    elif name:
        target = f' The target garment is "{name}".'
    else:
        target = ""
    return _BASE_PROMPT + target


def build_nano_generation_prompt(req: GenerationRequest) -> str:
    """nano_banana's prompt: the shared prompt PLUS the anti-logo-hallucination guard.

    Provider-specific on purpose (nano is the offender). flux / seedream keep calling
    build_generation_prompt, so their wording is unchanged. Deterministic."""
    return build_generation_prompt(req) + _NANO_LOGO_GUARD
