from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    yaml.safe_load((ROOT / "xiaoyi/plugin_openapi.yaml").read_text(encoding="utf-8"))
    count = 0
    for path in ROOT.rglob("*.json"):
        if any(part in {".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        json.loads(path.read_text(encoding="utf-8"))
        count += 1
    print(f"All YAML/JSON contracts OK ({count} JSON files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
