"""Item-cutout seam (Collage Phase 1): true-alpha garment mattes, computed
ONCE at image-birth with a local u2net ONNX model, QA-gated, stored per user.

Public surface:
  * service.matte_items_background — the birth hook (confirm chokepoint callers)
  * service.matte_item             — one item, used by the hook + backfill
  * engine.warm                    — optional boot-time session/model preload
  * qa.qa_matte                    — the pure structural gate

Distinct from app.photo_closet.cutout (zone CROPPING of a source photo): this
package mattes finished DISPLAY CARDS to transparency for compositing.
"""
