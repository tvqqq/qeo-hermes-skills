from __future__ import annotations

import json
import os
import sys
from urllib.request import Request, urlopen


def main() -> int:
    token = os.environ.get("QEO_VOICE_TOKEN")
    if not token:
        return 1

    headers = {}
    headers["Authorization"] = "Bearer " + token
    request = Request("http://127.0.0.1:8765/health", headers=headers)

    try:
        with urlopen(request, timeout=5) as response:
            if response.status != 200:
                return 1
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return 1

    return 0 if payload.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
