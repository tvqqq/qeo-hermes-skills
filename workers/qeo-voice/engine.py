from __future__ import annotations

import io
import threading
from collections.abc import Callable
from typing import Any

from registry import UnknownVoiceError, VoiceAssetError, VoiceRegistry


class VoiceBusyError(RuntimeError):
    """A synthesis is already in progress."""


class VoiceSynthesisError(RuntimeError):
    """The voice backend failed to synthesize audio."""


def _default_backend_factory() -> Any:
    from vieneu import Vieneu

    return Vieneu(mode="v3turbo")


def _default_wav_encoder(audio: Any) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, audio, 48000, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


class VieNeuVoiceEngine:
    def __init__(
        self,
        registry: VoiceRegistry,
        *,
        backend_factory: Callable[[], Any] | None = None,
        wav_encoder: Callable[[Any], bytes] | None = None,
    ) -> None:
        self.registry = registry
        self._backend_factory = backend_factory or _default_backend_factory
        self._wav_encoder = wav_encoder or _default_wav_encoder
        self._backend: Any | None = None
        self._ready = False
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._ready

    def start(self) -> None:
        if self._ready:
            return
        try:
            backend = self._backend_factory()
            for voice in self.registry.voices.values():
                backend.add_voice(
                    name=voice.slug,
                    ref_audio=str(voice.reference_path),
                    denoise=voice.denoise,
                    use_ref_codes=voice.use_ref_codes,
                    save=False,
                )
            self._backend = backend
            self._ready = True
        except Exception as exc:
            self._backend = None
            self._ready = False
            raise VoiceSynthesisError("Failed to start VieNeu voice engine") from exc

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        if not self._ready or self._backend is None:
            raise VoiceSynthesisError("Voice engine is not ready")
        config = self.registry.resolve(voice)
        if not self._lock.acquire(blocking=False):
            raise VoiceBusyError("Voice engine is busy")
        try:
            audio = self._backend.infer(
                text=text,
                voice=config.slug,
                use_ref_codes=config.use_ref_codes,
                temperature=config.temperature,
                top_k=config.top_k,
                top_p=config.top_p,
                repetition_penalty=config.repetition_penalty,
                max_chars=config.max_chars,
                silence_p=config.silence_p,
                crossfade_p=config.crossfade_p,
            )
            return self._wav_encoder(audio)
        except UnknownVoiceError:
            raise
        except VoiceBusyError:
            raise
        except Exception as exc:
            raise VoiceSynthesisError("VieNeu synthesis failed") from exc
        finally:
            self._lock.release()
