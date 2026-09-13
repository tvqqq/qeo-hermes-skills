from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GradientPreset:
    """Two-color diagonal gradient from bottom-left to top-right."""

    start: str
    end: str


PRESETS: dict[str, GradientPreset] = {
    "qeo-green": GradientPreset("#8CF3B5", "#249D71"),
    "qeo": GradientPreset("#7C3AED", "#06B6D4"),
    "mango": GradientPreset("#FFE259", "#FFA751"),
    "mojito": GradientPreset("#1D976C", "#93F9B9"),
    "stellar": GradientPreset("#7474BF", "#348AC7"),
    "midnight-city": GradientPreset("#232526", "#414345"),
}


def get_preset(name: str) -> GradientPreset:
    try:
        return PRESETS[name]
    except KeyError as exc:
        available = ", ".join(sorted(PRESETS))
        raise ValueError(f"Unknown preset '{name}'. Available presets: {available}") from exc
