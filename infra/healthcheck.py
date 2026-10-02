from __future__ import annotations

import os
import sys
from urllib.request import urlopen


def main() -> int:
    required = ("FACE_SERVICE_TOKEN", "FACE_MATCH_THRESHOLD", "FACE_MATCH_MARGIN")
    if any(not os.environ.get(name, "").strip() for name in required):
        return 1

    try:
        port = int(os.environ.get("PORT", "8000"))
        with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=4) as response:
            return 0 if response.status == 200 else 1
    except (OSError, ValueError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
