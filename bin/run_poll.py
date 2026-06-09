from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from btc_tracker.config import load_config
from btc_tracker.db import init_db, seed_thresholds
from btc_tracker.poller import run_poll_cycle

config = load_config()
init_db(config.database_path)
seed_thresholds(config.database_path, config.seed_high_threshold, config.seed_low_threshold)
result = run_poll_cycle(config)
print(json.dumps(result, indent=2, default=str))
