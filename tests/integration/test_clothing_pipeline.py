"""Integration test for the clothing pipeline."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from app.services.clothing_pipeline import process_outfit_image


@pytest.mark.asyncio
async def test_full_outfit_pipeline_integration(tmp_path: Path):
    """Test the full outfit processing pipeline with a real image."""
    # Find the first image in Images folder
    project_root = Path(__file__).resolve().parents[2]
    images_dir = project_root / "Images"
    
    # Common image extensions
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp"}
    
    # Find first image file
    input_image = None
    if images_dir.exists():
        for file_path in sorted(images_dir.iterdir()):
            if file_path.is_file() and file_path.suffix.lower() in image_extensions:
                input_image = file_path
                break
    
    assert input_image is not None and input_image.exists(), (
        f"No image file found in {images_dir}. "
        f"Please place at least one image file (jpg, png, etc.) in the Images folder."
    )

    responses_dir = project_root / "Responses"
    responses_dir.mkdir(exist_ok=True)

    json_summary_path = responses_dir / "items_summary.json"

    results = await process_outfit_image(
        outfit_image_path=str(input_image),
        images_output_dir=str(responses_dir),
        json_summary_path=str(json_summary_path),
    )

    # Basic sanity checks
    assert len(results) > 0, "At least one item should be detected"
    for r in results:
        assert os.path.exists(r.image_path), f"Generated image should exist: {r.image_path}"
        assert r.name, "Item name should not be empty"
        assert r.metadata, "Item metadata should not be empty"

    assert json_summary_path.exists()

    # Additionally, create a human-readable text file that pastes all JSON responses
    text_dump_path = responses_dir / "items_summary.txt"
    with open(json_summary_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    with open(text_dump_path, "w", encoding="utf-8") as f:
        for entry in summary:
            f.write(f"Image: {Path(entry['image_path']).name}\n")
            f.write(json.dumps(entry["metadata"], ensure_ascii=False, indent=2))
            f.write("\n\n")

    assert text_dump_path.exists()

