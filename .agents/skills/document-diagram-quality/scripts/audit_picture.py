#!/usr/bin/env python3
"""Audit a raster asset without writing or changing any image.

Pillow is required. Placement/crop/mapping are caller-supplied, not inferred
from a document. Outer near-background bounds are measurement candidates,
not safe crop instructions or a readability verdict.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageColor, ImageOps


def positive_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("must be a positive finite number")
    return number


def tolerance_value(value: str) -> int:
    number = int(value)
    if not 0 <= number <= 254:
        raise argparse.ArgumentTypeError("must be between 0 and 254")
    return number


def audit(
    source: Path,
    *,
    width_mm: float | None = None,
    height_mm: float | None = None,
    mapping: str = "unknown",
    crop_box: tuple[int, int, int, int] | None = None,
    background: str = "#FFFFFF",
    tolerance: int = 12,
) -> dict:
    if (width_mm is None) != (height_mm is None):
        raise ValueError("provide both width_mm and height_mm")
    if width_mm is not None and (
        not math.isfinite(width_mm)
        or not math.isfinite(height_mm)
        or width_mm <= 0
        or height_mm <= 0
    ):
        raise ValueError("placement dimensions must be positive finite numbers")
    if mapping not in {"unknown", "stretch", "contain"}:
        raise ValueError("mapping must be unknown, stretch, or contain")
    if mapping != "unknown" and width_mm is None:
        raise ValueError("known mapping requires placement dimensions")
    if not 0 <= tolerance <= 254:
        raise ValueError("tolerance must be between 0 and 254")

    source = source.resolve(strict=True)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    with Image.open(source) as original:
        raster_format = original.format
        metadata_dpi = original.info.get("dpi")
        stored_size = original.size
        frames = getattr(original, "n_frames", 1)
        orientation = original.getexif().get(274, 1)
        # Apply display orientation only in memory, to audit the visible asset.
        image = ImageOps.exif_transpose(original).convert("RGBA")
    oriented_size = image.size
    if crop_box is None:
        crop_box = (0, 0, image.width, image.height)
    left, top, right, bottom = crop_box
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError("crop_box must be a non-empty in-bounds pixel rectangle")
    viewport = image.crop(crop_box)
    rgb = ImageColor.getrgb(background)
    if len(rgb) != 3:
        raise ValueError("background must be an opaque RGB color")
    composite = Image.alpha_composite(
        Image.new("RGBA", viewport.size, (*rgb, 255)), viewport
    ).convert("RGB")
    difference = ImageChops.difference(
        composite, Image.new("RGB", viewport.size, rgb)
    )
    red, green, blue = difference.split()
    max_channel = ImageChops.lighter(ImageChops.lighter(red, green), blue)
    foreground = max_channel.point(lambda v: 255 if v > tolerance else 0)
    bounds = foreground.getbbox()
    pixel_count = viewport.width * viewport.height
    foreground_pixels = foreground.histogram()[255]
    margins = None
    outer_fraction = None
    if bounds is not None:
        margins = {
            "left": bounds[0],
            "top": bounds[1],
            "right": viewport.width - bounds[2],
            "bottom": viewport.height - bounds[3],
        }
        outer_fraction = 1 - (
            (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) / pixel_count
        )

    placement = None
    if width_mm is not None:
        source_ratio = viewport.width / viewport.height
        box_ratio = width_mm / height_mm
        placement = {
            "box_mm": [width_mm, height_mm],
            "mapping": mapping,
            "box_aspect_ratio": box_ratio,
            "source_viewport_aspect_ratio": source_ratio,
            "box_to_source_aspect_ratio": box_ratio / source_ratio,
            "effective_ppi": None,
            "relative_x_to_y_scale": None,
            "verdict": "unknown: crop and transforms were not resolved by this tool",
        }
        if mapping == "stretch":
            placement.update(
                mapped_image_mm=[width_mm, height_mm],
                effective_ppi={
                    "x": viewport.width * 25.4 / width_mm,
                    "y": viewport.height * 25.4 / height_mm,
                },
                relative_x_to_y_scale=box_ratio / source_ratio,
                scale_difference_percent=(box_ratio / source_ratio - 1) * 100,
                verdict="measurement only; caller asserts axis-aligned viewport fills box",
            )
        elif mapping == "contain":
            scale = min(width_mm / viewport.width, height_mm / viewport.height)
            placed_width = viewport.width * scale
            placed_height = viewport.height * scale
            placement.update(
                mapped_image_mm=[placed_width, placed_height],
                effective_ppi={"x": 25.4 / scale, "y": 25.4 / scale},
                relative_x_to_y_scale=1.0,
                scale_difference_percent=0.0,
                unused_box_extent_mm={
                    "horizontal_total": max(0.0, width_mm - placed_width),
                    "vertical_total": max(0.0, height_mm - placed_height),
                },
                verdict="measurement only; caller asserts aspect-preserving contain mapping",
            )

    after = hashlib.sha256(source.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("input changed during audit; discard this report")
    return {
        "schema_version": 1,
        "analysis_only": True,
        "source": str(source),
        "sha256": before,
        "source_unchanged": True,
        "raster": {
            "format": raster_format,
            "stored_pixels": list(stored_size),
            "exif_orientation": orientation,
            "oriented_pixels": list(oriented_size),
            "frame_count": frames,
            "audited_frame": 0,
            "metadata_dpi_not_effective_ppi": metadata_dpi,
        },
        "viewport": {
            "crop_box_in_oriented_pixels": list(crop_box),
            "right_bottom_exclusive": True,
            "pixels": list(viewport.size),
        },
        "outer_space_candidates": {
            "background_rgb": list(rgb),
            "max_channel_distance_tolerance": tolerance,
            "foreground_bbox_in_viewport_pixels": list(bounds) if bounds else None,
            "outer_margins_px": margins,
            "outside_bbox_area_fraction": outer_fraction,
            "background_like_pixel_fraction": 1 - foreground_pixels / pixel_count,
            "no_foreground_detected": bounds is None,
        },
        "placement": placement,
        "limits": [
            "No image, source document, or vector is written or edited.",
            "Near-background bounds are candidates, not safe crop instructions.",
            "Internal whitespace, faint features, labels, and relations need visual review.",
            "Document crop, rotation, skew, and transforms are not parsed.",
            "PPI and scale measurements do not certify readability or semantic fidelity.",
            "Only the first frame is audited when an asset has multiple frames.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    parser.add_argument("--width-mm", type=positive_float)
    parser.add_argument("--height-mm", type=positive_float)
    parser.add_argument(
        "--mapping", choices=["unknown", "stretch", "contain"], default="unknown",
        help="caller-verified mapping; unknown suppresses effective PPI/distortion claims",
    )
    parser.add_argument(
        "--crop-box", type=int, nargs=4, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"),
        help="oriented-source pixel viewport; right/bottom exclusive; analysis only",
    )
    parser.add_argument("--background", default="#FFFFFF", help="opaque RGB color")
    parser.add_argument("--tolerance", type=tolerance_value, default=12)
    parser.add_argument("--report", type=Path, help="JSON path; defaults to stdout")
    args = parser.parse_args()
    if args.report and (
        args.report.suffix.lower() != ".json"
        or args.report.resolve() == args.image.resolve()
        or (
            args.report.exists()
            and args.image.exists()
            and os.path.samefile(args.report, args.image)
        )
    ):
        parser.error("--report must be a JSON path different from the input")
    try:
        result = audit(
            args.image, width_mm=args.width_mm, height_mm=args.height_mm,
            mapping=args.mapping,
            crop_box=tuple(args.crop_box) if args.crop_box else None,
            background=args.background, tolerance=args.tolerance,
        )
    except (OSError, ValueError, RuntimeError) as error:
        parser.error(str(error))
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
