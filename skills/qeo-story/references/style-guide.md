# Qeo Story Shot — Visual Style Guide

## Canonical output

| Property | Value |
|---|---:|
| Canvas | 1080 × 1920 px |
| Ratio | 9:16 |
| Format | PNG |
| Default preset | `qeo-green` |
| Copyright | `@QeoQeo` |

## Default Qeo green

The approved reference uses a diagonal green field. The standalone renderer approximates that visual with:

- Bottom-left: `#8CF3B5`
- Top-right: `#249D71`
- The other two corners naturally blend near the midpoint.

## Screenshot card

- The source image itself is the card; there is no separate white wrapper or internal padding.
- Maximum width: canvas width minus 132 px safe margin on each side.
- Maximum height: 1480 px.
- Corner radius: 34 px.
- QeoBench-style soft black shadow: 50% intensity, 135° angle, 10 px offset, 34 px blur.
- A subtle 2 px white edge at low opacity keeps dark screenshots crisp against the gradient.
- Source image keeps its full aspect ratio and is never cropped by default.

## Vertical composition

- Screenshot visual center: approximately y=900 px.
- Screenshot top never rises above ~110 px.
- Screenshot bottom stays at or above ~1650 px.
- This leaves a dedicated lower zone for copyright and story UI breathing room.

## Copyright

- Text: `@QeoQeo` by default.
- Position: lower-right, aligned to the same 132 px horizontal safe margin.
- Bottom breathing room: ~132 px.
- Bold white text with a soft dark shadow for contrast.

## Background presets

| Preset | Bottom-left | Top-right |
|---|---|---|
| `qeo-green` | `#8CF3B5` | `#249D71` |
| `qeo` | `#7C3AED` | `#06B6D4` |
| `mango` | `#FFE259` | `#FFA751` |
| `mojito` | `#1D976C` | `#93F9B9` |
| `stellar` | `#7474BF` | `#348AC7` |
| `midnight-city` | `#232526` | `#414345` |
