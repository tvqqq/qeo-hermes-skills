from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageChops, ImageFont, ImageOps


def fit_inside(source_width: int, source_height: int, max_width: int, max_height: int) -> tuple[int, int]:
    """Return the largest integer size inside the bounds without changing aspect ratio."""
    if min(source_width, source_height, max_width, max_height) <= 0:
        raise ValueError("Image and bounds dimensions must be positive")
    scale = min(max_width / source_width, max_height / source_height)
    return max(1, round(source_width * scale)), max(1, round(source_height * scale))


def make_diagonal_gradient(size: tuple[int, int], start: str, end: str) -> Image.Image:
    """Create a bottom-left → top-right two-color RGB gradient."""
    width, height = size
    if width <= 0 or height <= 0:
        raise ValueError("Gradient dimensions must be positive")

    x_row = Image.new("L", (width, 1))
    x_row.putdata([round(255 * x / max(1, width - 1)) for x in range(width)])
    x_ramp = x_row.resize((width, height))

    y_col = Image.new("L", (1, height))
    y_col.putdata([round(255 * y / max(1, height - 1)) for y in range(height)])
    y_ramp = y_col.resize((width, height))

    mask = ImageChops.add(x_ramp, ImageOps.invert(y_ramp), scale=2.0)
    return ImageOps.colorize(mask, black=start, white=end).convert("RGB")


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    from PIL import ImageDraw

    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), radius=max(0, radius), fill=255)
    return mask


def load_bold_font(size: int) -> ImageFont.ImageFont:
    """Use a user-provided/system bold font and degrade safely to Pillow's default."""
    candidates = [
        os.environ.get("QEO_STORY_FONT"),
        "DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(str(Path(candidate).expanduser()), size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def downscale_if_needed(image: Image.Image, max_dimension: int = 4096) -> Image.Image:
    """Limit working-set size while preserving aspect ratio and image quality."""
    if max(image.size) <= max_dimension:
        return image
    resized = image.copy()
    resized.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
    return resized
