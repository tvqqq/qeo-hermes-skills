from __future__ import annotations

import argparse
import math
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
    safe_margin: int = 132
    card_radius: int = 34
    max_card_height: int = 1480
    card_center_y: int = 900
    shadow_intensity: int = 50
    shadow_angle: int = 135
    shadow_offset: int = 10
    shadow_blur: int = 34
    edge_width: int = 2
    edge_alpha: int = 44
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
    if not 700 <= options.max_card_height <= 1600:
        raise ValueError("max_card_height must be between 700 and 1600 pixels")
    if not 0 <= options.shadow_intensity <= 100:
        raise ValueError("shadow_intensity must be between 0 and 100")
    if not 0 <= options.shadow_offset <= 80:
        raise ValueError("shadow_offset must be between 0 and 80 pixels")
    if not 0 <= options.shadow_blur <= 120:
        raise ValueError("shadow_blur must be between 0 and 120 pixels")
    if not 0 <= options.edge_width <= 8:
        raise ValueError("edge_width must be between 0 and 8 pixels")
    if not 0 <= options.edge_alpha <= 255:
        raise ValueError("edge_alpha must be between 0 and 255")
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
    canvas_width, _ = CANVAS_SIZE
    max_image_width = canvas_width - (2 * options.safe_margin)
    image_width, image_height = fit_inside(
        source.width, source.height, max_image_width, options.max_card_height
    )
    left = (canvas_width - image_width) // 2
    top = round(options.card_center_y - image_height / 2)
    min_top, max_bottom = 110, 1650
    if top < min_top:
        top = min_top
    if top + image_height > max_bottom:
        top = max_bottom - image_height
    right, bottom = left + image_width, top + image_height

    angle = math.radians(options.shadow_angle)
    shadow_x = round(options.shadow_offset * math.cos(angle))
    shadow_y = round(options.shadow_offset * math.sin(angle))
    shadow = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (left + shadow_x, top + shadow_y, right + shadow_x, bottom + shadow_y),
        radius=options.card_radius,
        fill=(0, 0, 0, round(255 * options.shadow_intensity / 100)),
    )
    if options.shadow_blur:
        shadow = shadow.filter(ImageFilter.GaussianBlur(options.shadow_blur))
    base.alpha_composite(shadow)

    _paste_rounded(base, source, (left, top, right, bottom), options.card_radius)

    if options.edge_width and options.edge_alpha:
        edge = Image.new("RGBA", CANVAS_SIZE, (0, 0, 0, 0))
        ImageDraw.Draw(edge).rounded_rectangle(
            (left, top, right - 1, bottom - 1),
            radius=options.card_radius,
            outline=(255, 255, 255, options.edge_alpha),
            width=options.edge_width,
        )
        base.alpha_composite(edge)

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
    parser.add_argument("--safe-margin", type=int, default=132, help="Horizontal safe margin in pixels (default: 132)")
    parser.add_argument("--card-radius", type=int, default=34, help="Screenshot corner radius in pixels (default: 34)")
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
