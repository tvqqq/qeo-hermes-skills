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

## Card

- White `#FFFFFF`.
- Maximum width: canvas width minus 84 px safe margin on each side.
- Maximum height: 1480 px.
- Internal padding: 46 px.
- Corner radius: 34 px.
- Soft black shadow: slight down/right offset, broad blur, low opacity.
- Source image keeps its full aspect ratio and is never cropped by default.
- Source image gets a subtle 18 px clip radius.

## Vertical composition

- Card visual center: approximately y=900 px.
- Card top never rises above ~110 px.
- Card bottom stays at or above ~1650 px.
- This leaves a dedicated lower zone for copyright and story UI breathing room.

## Copyright

- Text: `@QeoQeo` by default.
- Position: lower-right, aligned to the same 84 px horizontal safe margin.
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
