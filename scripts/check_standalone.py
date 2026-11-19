"""Report dependency readiness without making a paid model request."""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dsh_bridge import BRIDGE
from dsh_bridge.config import public_config
from dsh_bridge.sdk_backend import sdk_info

def main() -> int:
    print(json.dumps({"python": sys.executable, "sdk": sdk_info(),
                      "config": public_config(BRIDGE.cfg), "status": BRIDGE.status()},
                     ensure_ascii=False, indent=2))
    if "--handshake" in sys.argv:
        result = BRIDGE.reconnect()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        BRIDGE.close()
        return 0 if result["ok"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
