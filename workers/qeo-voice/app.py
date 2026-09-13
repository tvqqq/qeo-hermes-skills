from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from engine import VieNeuVoiceEngine, VoiceBusyError, VoiceSynthesisError
from registry import UnknownVoiceError, load_registry


class TTSRequest(BaseModel):
    text: str
    voice: str | None = None


def create_app(engine: Any, token: str) -> FastAPI:
    if not token:
        raise ValueError("Qeo Voice token must not be empty")

    app = FastAPI(title="Qeo Voice Worker", docs_url=None, redoc_url=None)

    def require_auth(authorization: str | None = Header(default=None)) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not hmac.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="unauthorized")
    @app.get("/health", dependencies=[])
    def health(authorization: str | None = Header(default=None)):
        require_auth(authorization)
        if not getattr(engine, "ready", False):
            return JSONResponse(status_code=503, content={"status": "unavailable"})
        return {
            "status": "ok",
            "engine": "v3turbo",
            "default_voice": engine.registry.default_slug,
        }

    @app.post("/v1/tts")
    def synthesize(request: TTSRequest, authorization: str | None = Header(default=None)):
        require_auth(authorization)
        text = request.text.strip()
        if not text:
            return JSONResponse(status_code=400, content={"error": "invalid_text"})
        try:
            audio = engine.synthesize(text, request.voice)
        except UnknownVoiceError:
            return JSONResponse(status_code=400, content={"error": "unknown_voice"})
        except VoiceBusyError:
            return JSONResponse(status_code=503, content={"error": "busy"})
        except VoiceSynthesisError:
            return JSONResponse(status_code=500, content={"error": "synthesis_failed"})
        return Response(content=audio, media_type="audio/wav")

    return app

def load_runtime_settings(env: Any = None) -> dict[str, Any]:
    values = os.environ if env is None else env
    required = (
        "QEO_VOICE_TOKEN",
        "QEO_VOICE_ASSET_ROOT",
        "QEO_VOICE_BIND_HOST",
    )
    missing = [name for name in required if not values.get(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variable: {missing[0]}")

    default_registry = Path(__file__).with_name("voices.json")
    return {
        "token": values["QEO_VOICE_TOKEN"],
        "asset_root": Path(values["QEO_VOICE_ASSET_ROOT"]).expanduser(),
        "bind_host": values["QEO_VOICE_BIND_HOST"],
        "port": int(values.get("QEO_VOICE_PORT", "8765")),
        "registry_path": Path(values.get("QEO_VOICE_REGISTRY", str(default_registry))).expanduser(),
    }


def main() -> None:
    settings = load_runtime_settings()
    registry = load_registry(settings["registry_path"], settings["asset_root"])
    engine = VieNeuVoiceEngine(registry)
    engine.start()
    app = create_app(engine, settings["token"])

    import uvicorn

    uvicorn.run(app, host=settings["bind_host"], port=settings["port"])


if __name__ == "__main__":
    main()
