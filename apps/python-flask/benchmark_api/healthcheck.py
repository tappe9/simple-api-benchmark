"""Container-local readiness probe for the Flask service."""

import json
import sys
import urllib.request


def main() -> int:
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2) as response:
            payload = json.load(response)
            if response.status == 200 and payload == {"status": "ok"}:
                return 0
    except Exception:
        pass
    return 1


if __name__ == "__main__":
    sys.exit(main())
