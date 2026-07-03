"""Style Profile READ path (Wave S2 scope A): the first consumer of the S0/S1
profile substrate.

Assembles the per-turn profile block the agent's system prompt carries:

  * ``facts``           — style_profiles.facts, treated as LITERAL HARD
                          CONSTRAINTS. The composer excludes items matching the
                          avoid-lists; the prompt marks them inviolable.
  * ``narrative``       — style_profiles.narrative_blob (distilled prose, when
                          S1 distillation has run; onboarding leaves it {}).
  * ``preferences``     — active style_preferences ordered by confidence,
                          capped, rendered one-per-line with polarity.

Server-side only: assembled fresh each turn from the DB under the RLS-scoped
session; never accepted from the client or the model.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import StylePreference, StyleProfile

logger = logging.getLogger(__name__)

# Facts keys read as hard avoid-lists (LITERAL: values name categories, colors,
# materials, subcategories, patterns the user will not wear).
HARD_AVOID_KEYS = ("avoid", "never_wear", "hard_constraints", "no_go")

_MAX_PREFERENCES = 20
_MAX_FACT_CHARS = 2000
_MAX_NARRATIVE_CHARS = 1200


@dataclass
class ProfileBlock:
    """The assembled profile a turn runs with."""

    facts: Dict[str, Any] = field(default_factory=dict)
    narrative: Dict[str, Any] = field(default_factory=dict)
    preferences: List[Dict[str, Any]] = field(default_factory=list)
    hard_avoids: List[str] = field(default_factory=list)
    onboarded: bool = False

    def to_prompt_text(self) -> str:
        """Render the compact profile section of the system prompt."""
        lines: List[str] = []

        if self.hard_avoids:
            lines.append(
                "HARD CONSTRAINTS (inviolable — never suggest anything matching these):"
            )
            for avoid in self.hard_avoids:
                lines.append(f"  - never: {avoid}")

        fact_lines = _render_facts(self.facts)
        if fact_lines:
            lines.append("Profile facts (sizes/context — treat as ground truth):")
            lines.extend(f"  - {f}" for f in fact_lines)

        if self.preferences:
            lines.append("Style preferences (weight by confidence; not hard rules):")
            for p in self.preferences:
                conf = p.get("confidence")
                conf_txt = f" (confidence {conf:.2f})" if isinstance(conf, float) else ""
                lines.append(
                    f"  - {p['dimension']}: {p.get('polarity') or 'noted'} "
                    f"{_compact(p.get('value'))}{conf_txt}"
                )

        narrative_text = _narrative_text(self.narrative)
        if narrative_text:
            lines.append(f"Style narrative: {narrative_text}")

        if not lines:
            return (
                "No style profile yet — ask light preference questions as you go "
                "and use record_preference when the user states a taste."
            )
        return "\n".join(lines)


def _compact(value: Any, limit: int = 160) -> str:
    if value in (None, {}, []):
        return ""
    text = str(value)
    return text[:limit]


def _render_facts(facts: Dict[str, Any]) -> List[str]:
    """Flatten facts to short 'key: value' lines, skipping the avoid-lists
    (rendered separately as hard constraints) and server bookkeeping."""
    lines: List[str] = []
    used = 0
    for key, value in facts.items():
        if key in HARD_AVOID_KEYS or key == "onboarding_completed_at":
            continue
        rendered = f"{key}: {_compact(value)}"
        if used + len(rendered) > _MAX_FACT_CHARS:
            break
        used += len(rendered)
        lines.append(rendered)
    return lines


def _narrative_text(narrative: Dict[str, Any]) -> str:
    if not isinstance(narrative, dict) or not narrative:
        return ""
    # Distillation writes prose under 'text'/'summary'; fall back to any strings.
    for key in ("text", "summary", "narrative"):
        val = narrative.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()[:_MAX_NARRATIVE_CHARS]
    parts = [str(v) for v in narrative.values() if isinstance(v, str) and v.strip()]
    return " ".join(parts)[:_MAX_NARRATIVE_CHARS]


def extract_hard_avoids(facts: Dict[str, Any]) -> List[str]:
    """Collect the literal avoid tokens from every HARD_AVOID_KEYS list."""
    avoids: List[str] = []
    for key in HARD_AVOID_KEYS:
        raw = facts.get(key)
        if isinstance(raw, str) and raw.strip():
            avoids.append(raw.strip().lower())
        elif isinstance(raw, list):
            avoids.extend(str(v).strip().lower() for v in raw if str(v).strip())
        elif isinstance(raw, dict):
            # {"colors": [...], "categories": [...]} shape — flatten the leaves.
            for sub in raw.values():
                if isinstance(sub, list):
                    avoids.extend(str(v).strip().lower() for v in sub if str(v).strip())
                elif isinstance(sub, str) and sub.strip():
                    avoids.append(sub.strip().lower())
    # De-duplicate, preserve order.
    seen = set()
    out = []
    for a in avoids:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def assemble_profile(db: Session, user_id: UUID) -> ProfileBlock:
    """Read + assemble the user's profile block (facts, narrative, preferences).

    Every query filters ``user_id`` (app-level guard); under the RLS-scoped
    session Postgres additionally enforces it.
    """
    profile_row: Optional[StyleProfile] = (
        db.query(StyleProfile).filter(StyleProfile.user_id == user_id).one_or_none()
    )
    facts = dict(profile_row.facts or {}) if profile_row is not None else {}
    narrative = dict(profile_row.narrative_blob or {}) if profile_row is not None else {}

    pref_rows: List[StylePreference] = (
        db.query(StylePreference)
        .filter(StylePreference.user_id == user_id, StylePreference.active.is_(True))
        .order_by(StylePreference.confidence.desc().nullslast(),
                  StylePreference.last_seen_at.desc())
        .limit(_MAX_PREFERENCES)
        .all()
    )
    preferences = [
        {
            "dimension": p.dimension,
            "value": p.value or {},
            "polarity": p.polarity,
            "confidence": float(p.confidence) if p.confidence is not None else None,
            "weight": float(p.weight) if p.weight is not None else None,
        }
        for p in pref_rows
    ]

    return ProfileBlock(
        facts=facts,
        narrative=narrative,
        preferences=preferences,
        hard_avoids=extract_hard_avoids(facts),
        onboarded=bool(facts.get("onboarding_completed_at")),
    )
