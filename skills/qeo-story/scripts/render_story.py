from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

try:
    from .image_utils import downscale_if_needed, fit_inside, load_bold_font, make_diagonal_gradient, rounded_mask
    from .presets import PRESETS, get_preset
except ImportError:
    from image_utils import downscale_if_needed, fit_inside, load_bold_font, make_diagonal_gradient, rounded_mask
    from presets import PRESETS, get_preset

CANVAS_SIZE = (1080, 1920)
DEFAULT_FOOTER = "@QeoQeo"
SUPPORTED_FORMATS = {"PNG", "JPEG", "WEBP"}

@dataclass(frozen=True)
class StoryRenderOptions:
    preset: str = "qeo-green"
    footer: str = DEFAULT_FOOTER
    safe_margin: int = 84
    card_radius: int = 34
    card_padding: int = 46
    image_radius: int = 18
    max_card_height: int = 1480
    card_center_y: int = 900
    footer_font_size: int = 38
    footer_bottom_margin: int = 132

def _open_input(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            if source.format not in SUPPORTED_FORMATS:
                supported = ", ".join(sorted(SUPPORTED_FORMATS))
                raise ValueError(f"Unsupported image format '{source.format}'. Supported: {supported}")
            source.draft("RGB", (4096, 4096))
            source.load()
            oriented = ImageOps.exif_transpose(source)
            image = oriented.convert("RGBA")
    except (FileNotFoundError, PermissionError, UnidentifiedImageError, OSError) as exc:
        raise ValueError(f"Could not read input image: {path}") from exc
    return downscale_if_needed(image)

def _validate_options(options: StoryRenderOptions) -> None:
    if not 24 <= options.safe_margin <= 220:
        raise ValueError("safe_margin must be between 24 and 220 pixels")
    if not 0 <= options.card_radius <= 160:
        raise ValueError("card_radius must be between 0 and 160 pixels")
    if not 12 <= options.card_padding <= 140:
        raise ValueError("card_padding must be between 12 and 140 pixels")
    if not 700 <= options.max_card_height <= 1600:
        raise ValueError("max_card_height must be between 700 and 1600 pixels")
    if not 18 <= options.footer_font_size <= 96:
        raise ValueError("footer_font_size must be between 18 and 96 pixels")

def _paste_rounded(base: Image.Image, source: Image.Image, box: tuple[int, int, int, int], radius: int) -> None:
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    resized = source.resize((width, height), Image.Resampling.LANCZOS)
    alpha = resized.getchannel("A")
    mask = rounded_mask((width, height), min(radius, width // 2, height // 2))
    mask = ImageChops.multiply(alpha, mask)
    base.paste(resized, (left, top), mask)

def _draw_card(base: Image.Image, source: Image.Image, options: StoryRenderOptions) -> None:
    canvas_width, canvas_height = CANVAS_SIZE
    max_card_width = canvas_width - (2 * options.safe_margin)
    max_image_width = max_card_width - (2 * options.card_padding)
    max_image_height = options.max_card_height - (2 * options.card_padding)
    image_width, image_height = fit_inside(source.width, source.height, max_image_width, max_image_height)
    card_width = image_width + (2 * options.card_padding)
    card_height = image_height + (2 * options.card_padding)
    left = (canvas_width - card_width) // 2
    top = round(options.card_center_y - card_height / 2)
    min_top, max_bottom = 110, 1650
    if top < min_top:
        top = min_top
    if top + card_height > max_bottom:
        top = max_bottom - card_height
    right, bottom = left + card_width, top + card_height

    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle((left + 8, top + 18, right + 8, bottom + 18), radius=options.card_radius, fill=(0, 0, 0, 78))
    shadow = shadow.filter(ImageFilter.GaussianBlur(26))
    base.alpha_composite(shadow)

    card_layer = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(card_layer).rounded_rectangle((left, top, right, bottom), radius=options.card_radius, fill=(255, 255, 255, 255))
    base.alpha_composite(card_layer)

    image_left = left + (card_width - image_width) // 2
    image_top = top + (card_height - image_height) // 2
    _paste_rounded(base, source, (image_left, image_top, image_left + image_width, image_top + image_height), options.image_radius)

def _draw_footer(base: Image.Image, options: StoryRenderOptions) -> None:
    if not options.footer.strip():
        return
    overlay = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    font = load_bold_font(options.footer_font_size)
    draw = ImageDraw.Draw(overlay)
    bbox = draw.textbbox((0, 0), options.footer, font=font, stroke_width=0)
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = CANVAS_SIZE[0] - options.safe_margin - text_width
    y = CANVAS_SIZE[1] - options.footer_bottom_margin - text_height
    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.text((x + 2, y + 3), options.footer, font=font, fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(4))
    base.alpha_composite(shadow)
    draw.text((x, y), options.footer, font=font, fill=(255, 255, 255, 255))
    base.alpha_composite(overlay)

def render_story(input_path: str | Path, output_path: str | Path, options: StoryRenderOptions | None = None) -> Path:
    options = options or StoryRenderOptions()
    _validate_options(options)
    preset = get_preset(options.preset)
    source_path = Path(input_path).expanduser()
    destination = Path(output_path).expanduser()
    source = _open_input(source_path)
    background = make_diagonal_gradient(CANVAS_SIZE, preset.start, preset.end).convert("RGBA")
    _draw_card(background, source, options)
    _draw_footer(background, options)
    destination.parent.mkdir(parents=True, exist_ok=True)
    background.convert("RGB").save(destination, format="PNG", optimize=True)
    return destination

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render a Qeo-style 1080x1920 story image.")
    parser.add_argument("--input", required=True, help="Input PNG/JPEG/WebP path")
    parser.add_argument("--output", required=True, help="Output PNG path")
    parser.add_argument("--preset", default="qeo-green", help=f"Background preset (default: qeo-green). Choices: {', '.join(sorted(PRESETS))}")
    parser.add_argument("--footer", default=DEFAULT_FOOTER, help=f"Footer/copyright text (default: {DEFAULT_FOOTER})")
    parser.add_argument("--safe-margin", type=int, default=84, help="Horizontal safe margin in pixels (default: 84)")
    parser.add_argument("--card-radius", type=int, default=34, help="White card corner radius in pixels (default: 34)")
    parser.add_argument("--list-presets", action="store_true", help="Print available background presets and exit")
    return parser

def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.list_presets:
        print("\n".join(sorted(PRESETS)))
        return 0
    options = StoryRenderOptions(preset=args.preset, footer=args.footer, safe_margin=args.safe_margin, card_radius=args.card_radius)
    try:
        output = render_story(args.input, args.output, options)
    except ValueError as exc:
        print(f"qeo-story-shot: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
