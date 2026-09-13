from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


class UnknownVoiceError(ValueError):
    """Requested voice is not present in the public registry."""


class VoiceAssetError(ValueError):
    """Voice registry or private reference asset is invalid."""


@dataclass(frozen=True)
class VoiceConfig:
    slug: str
    display_name: str
    engine: str
    profile: str
    reference_path: Path
    denoise: bool
    use_ref_codes: bool
    temperature: float
    top_k: int
    top_p: float
    repetition_penalty: float
    max_chars: int
    silence_p: float
    crossfade_p: float


@dataclass(frozen=True)
class VoiceRegistry:
    default_slug: str
    voices: dict[str, VoiceConfig]

    def resolve(self, slug: str | None) -> VoiceConfig:
        requested = slug or self.default_slug
        try:
            return self.voices[requested]
        except KeyError as exc:
            raise UnknownVoiceError(f"Unknown voice: {requested}") from exc


def _reference_path(asset_root: Path, reference: str) -> Path:
    root = asset_root.expanduser().resolve()
    resolved = (root / reference).resolve()
    if not resolved.is_relative_to(root):
        raise VoiceAssetError("Voice reference must stay under the asset root")
    if not resolved.is_file():
        raise VoiceAssetError(f"Missing voice reference asset: {reference}")
    return resolved

def load_registry(registry_path: Path, asset_root: Path) -> VoiceRegistry:
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    default_slug = payload.get("default")
    raw_voices = payload.get("voices")
    if not isinstance(default_slug, str) or not isinstance(raw_voices, dict):
        raise VoiceAssetError("Invalid voice registry structure")
    if default_slug not in raw_voices:
        raise VoiceAssetError("Default voice is not registered")

    voices: dict[str, VoiceConfig] = {}
    for slug, item in raw_voices.items():
        if not isinstance(item, dict):
            raise VoiceAssetError(f"Invalid voice entry: {slug}")
        reference = item.get("reference")
        if not isinstance(reference, str) or not reference:
            raise VoiceAssetError(f"Missing reference path for voice: {slug}")
        voices[slug] = VoiceConfig(
            slug=slug,
            display_name=str(item["display_name"]),
            engine=str(item["engine"]),
            profile=str(item["profile"]),
            reference_path=_reference_path(asset_root, reference),
            denoise=bool(item["denoise"]),
            use_ref_codes=bool(item["use_ref_codes"]),
            temperature=float(item["temperature"]),
            top_k=int(item["top_k"]),
            top_p=float(item["top_p"]),
            repetition_penalty=float(item["repetition_penalty"]),
            max_chars=int(item["max_chars"]),
            silence_p=float(item["silence_p"]),
            crossfade_p=float(item["crossfade_p"]),
        )
    return VoiceRegistry(default_slug=default_slug, voices=voices)
