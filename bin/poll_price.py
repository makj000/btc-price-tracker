from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from btc_tracker.config import load_config
from btc_tracker.db import init_db
from btc_tracker.poller import run_poll_cycle


def main() -> int:
    config = load_config()
    init_db(config.database_path)

    try:
        result = run_poll_cycle(config)
    except Exception as exc:
        print(f"poll failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
