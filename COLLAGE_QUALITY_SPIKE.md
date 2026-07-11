# Collage Quality — Phase 0 Research Spike (Diagnosis + Options)

**Date:** 2026-07-11
**Scope:** Diagnose why the outfit collage (the composited multi-item image on Home / Today's Look) looks bad, evaluate fix approaches, recommend a direction. **No production changes were made. No generation APIs were called.** Everything ran locally (CPU) against real bucket images and real stored collages.
**Visual report (all evidence images embedded):** https://claude.ai/code/artifact/c5492160-ec32-4113-be4a-412416cdfc5f

---

## TL;DR

It's not one problem — it's a compositing pipeline built on a matte it can't reliably get.

Closet items are clean generated product shots, but they are stored as **opaque JPEGs with no alpha channel**, each on a **different** off-white (up to Δ22 RGB/channel from the collage canvas), with **baked-in shadows that the generation invariant explicitly allows**. The collage renderer re-derives a cutout at render time using a color-tolerance flood fill, which **structurally cannot handle white/light garments** — so it eats bites out of light jeans, mangles white tees, leaves shadow smudges floating on the new canvas, and silently falls back to pasting mismatched opaque rectangles. On top of that, every item is scaled to the same 78% canvas height, so a sneaker renders as tall as a shirt.

**Recommendation:** matte each item **once, at image-birth, with a local ONNX salience model (u2net, ~90 ms CPU, $0 marginal)**, store the alpha cutout next to the display JPEG, and rewrite the compositor to place true-alpha cutouts with category-aware scale and one synthetic shadow. A prototype of exactly this took the worst real outfits from patchy to catalog-grade.

---

## 1. Method

- Pulled 13 real item images + 6 recent stored collages (`outfit_collages/`) from the live Supabase bucket.
- Measured border colors, alpha presence, knockout behavior with the repo venv against `app/services/stylist/collage.py` on main (grid-v5 — i.e. *post* the `fix/todays-look-collage-knockout` fix, which is already merged and insufficient).
- Reproduced the failures fresh by calling `compose_grid()` on real items — confirming current code, not stale cache.
- Prototyped three candidate fixes on the same items (scratchpad: `proto_whitekey.py`, `proto_rembg.py`, `proto_composite.py`).

Closet composition datum: **31 of 32** active item images are `generated_items/` (invariant-satisfying near-white product shots); 1 is `ingest_items/` (raw retailer photo — the belt).

## 2. Diagnosed causes (in order of damage)

### ① The render-time cutout is a color key, and the closet is full of white clothes
`_background_mask()` keys out pixels within **tolerance 26** of the sampled border color, flood-filled from the border. On light garments the flood **enters the garment** wherever it grades into the background. Observed on real/reproduced collages:
- ragged bite eaten out of light-wash jeans (right leg partially dissolved);
- white tee with dissolved/eaten edges;
- white sneaker toe keyed away.

### ② Baked-in shadows are allowed at the source — then survive as dirt
`INVARIANT_BLOCK` (app/services/image_generation/prompt.py) demands "off-white … **at most a subtle natural product shadow**". Perfect for single-item display; poison for compositing. Shadow pixels darker than the key tolerance count as "content", so after the background is swapped they float on the new canvas as scalloped smudges (clearly visible under the tee hem; ×6 contrast amplification shows smears/halos everywhere).

### ③ When the key gives up, the fallback is an opaque rectangle on the wrong white
Busy/gradient backgrounds (the belt — retailer `ingest_items` photo; the cloudy-background Jordans) fail the `_MIN_BG_FRACTION` check and paste as full rectangles. Measured border whites across real items span **(222,217,211) → (250,248,235)** — up to **Δ22 per channel** vs the #F3EEE6 canvas. A Δ of ~3 is visible; 22 is a patch. This is the "patchy" look.

### ④ Category-blind scale: every item is 78% of canvas height
`compose_grid` height-normalizes every cell to the same target. A sneaker (landscape) ends up with *more canvas area than the jeans*; a belt renders as tall as shorts. The row reads "random tiles", not "an outfit".

### ⑤ No stored transparency, so all of this re-happens on every render
Every item image in the bucket is an opaque JPEG (`has_alpha: false` across the sample). The renderer's alpha-reuse path (`_source_alpha`) is dead code in practice. Each collage re-runs the fragile key from scratch per item.

**What it is *not*:** not a "remove a messy background from a raw photo" problem (sources are already clean studio shots — the user-photo case is handled upstream by generation), and not *primarily* a mismatched-white-tone problem — when the key succeeds the field unifies; the eaten garments, shadow dirt, rectangle fallbacks and scale chaos are what remain.

## 3. Prototype results (same real images)

### 3a. Smarter classical white-key — still fails (structurally)
Built a substantially better key than production: multiplicative-shading background model (shadows classify as background), chroma-residual distance, border connectivity, soft alpha ramp, color decontamination. Results: shadows removed cleanly, colored garments fine — but **the white tee itself dissolves** and white shoe leather goes see-through. White cloth and near-white background are the *same colors*; no color-based method can separate them. Tuning moves the failure around; it doesn't remove it. This closet is full of white/light garments → **disqualifying**. (~100–900 ms/item, numpy only.)

### 3b. Local learned salience models (rembg / ONNX, CPU, $0 per image)

| Model | Size | CPU latency/item* | Result on 10 real items |
|---|---|---|---|
| **u2net** | 176 MB | **~85–110 ms** (455 ms first) | **10/10 clean** — incl. both white-garment traps, heavy-shadow jeans, and the cloudy-bg Jordans that production pastes as a rectangle |
| isnet-general-use | 179 MB | ~150–160 ms | 9/10 — misread the white tee (kept only the flower graphic) |
| birefnet-general | 930 MB | **45–205 s** (+1 EP crash) | Tee matte quality equals u2net — but latency is disqualifying inline; offline/GPU-only |

\* Apple Silicon, onnxruntime CPU, after warmup. Session init ~9 s (one-time per process).

Takeaway: **u2net alone handled every hard case in the sample**; model choice matters (isnet failed the adversarial white-tee), so whichever ships needs a cheap QA gate with a fallback.

### 3c. Recomposited with true alpha + category scale + one synthetic shadow
Same canvas contract as production (1080×540, #F3EEE6). Garments centered; footwear ~36% height seated low; accessories ~28%; one consistent soft shadow derived from each alpha. Result on the worst real outfits: **no bites, no smudges, no rectangles, believable relative scale** — catalog-grade, pure PIL/numpy, no generation call. (Category scale table is a tuning knob for the build phase.)

## 4. Options, ranked

| Verdict | Approach | Quality ceiling | Latency | Cost | Infra |
|---|---|---|---|---|---|
| **RECOMMENDED** | **Matte once at image-birth (local u2net), store alpha PNG alongside JPEG, rewrite compositor** | Catalog-grade (demonstrated); every future surface inherits clean cutouts | ~90–150 ms/item **once ever**; collage render stays <1 s pure PIL | $0 marginal; ~176 MB model in worker image | onnxruntime dep + backfill job over ~32 images + nullable `cutout_url` / storage convention |
| Fallback-tier | (a) Same matting at collage-render time (no stored alpha) | Same visual ceiling | +0.4–1 s per uncached collage | $0 | Model in API/worker process; re-pays per cache miss; other surfaces don't benefit |
| Complement | (c) Tighten generation invariant (exact bg, "no shadow") | Helps future images only; can't fix the 31 existing without paid regen; models won't hit an exact hex reliably | 0 added | $0 new / ~$1.40+ to regen catalog (FLUX rung-1) | Prompt-only — do it *softly* (bias flatter light), don't bet the collage on prompt compliance |
| **Rejected** | (b) Generate the collage directly (one image call) | Highest editorial ceiling, but item fidelity becomes a per-collage generation-verify problem (logo/pattern drift) | 5–20 s/collage | **~$0.045+ per collage per re-render, recurring** — scales with outfits, not items; conflicts with the just-completed cost-discipline effort | Multi-item prompt+verify pipeline; cache invalidation on any item change |
| Rejected by prototype | (a-lite) Classical white-key only | Cannot matte white-on-white (3a) | ~0.1–0.9 s/item | $0 | None — quality ceiling disqualifying on real data |
| Insufficient alone | (d-only) Better compositing without true mattes | Fixes cause ④ only; bites/smudges/rectangles remain | unchanged | $0 | Folded into recommended path as "compositing v2" |

## 5. Recommended build shape (NOT started — pending direction pick)

1. **Cutout service** — u2net via onnxruntime CPU behind a small pure seam. QA gate: alpha region must be one dominant connected blob, coverage sane vs trim box, no border contact. On QA fail → try isnet-general-use → else mark item `no_matte` (collage renders it flat on its own tile, never a patchy rectangle).
2. **Store at birth** — hook the confirm chokepoint (photo-seam P4) + one-shot backfill job for the ~32 existing images (seconds of compute); content-addressed `item_cutouts/` object + nullable `cutout_url`.
3. **Compositing v2** — grid renderer consumes stored alpha (finally lighting up the `_source_alpha` path), category-aware scale table, baseline anchoring for footwear/accessories, one synthetic shadow; delete the render-time key for matted items. Bump `grid-v6` / `lookbook-v3` so caches invalidate.
4. **Invariant nudge (optional, cheap)** — soften "natural product shadow" toward "minimal, soft, directly beneath" for *future* generations; do not regenerate the back catalog.

### Open questions for review
- Ship u2net-only with QA fallback, or u2net+isnet dual-model from day one? (Dual adds ~180 MB to the worker image; sample says u2net alone was 10/10, but n=10.)
- Where does the ~180 MB model live in deploy — baked into the image vs downloaded at boot into a volume?
- Is the collage the only consumer of cutouts for now, or should the deck card adopt them in the same wave (bigger blast radius, same infra)?

---

*Prototype scripts and raw evidence live in the session scratchpad (`proto_whitekey.py`, `proto_rembg.py`, `proto_hardcase.py`, `proto_composite.py`, `diagnose.py`) — temporary; the artifact link above is the durable visual record. Prior partial fix: `fix/todays-look-collage-knockout` (merged into main as grid-v5; addressed interior-hole punching only, insufficient for the causes above).*
