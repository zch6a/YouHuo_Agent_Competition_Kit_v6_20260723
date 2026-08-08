from __future__ import annotations

import json
import tempfile
from pathlib import Path

from youhuo.api import create_app

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="youhuo-openapi-v4-") as tmp:
        app = create_app(Path(tmp) / "openapi.db", demo_mode=True)
        schema = app.openapi()
    output = ROOT / "xiaoyi/plugin_openapi_v4.generated.json"
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Generated {output.relative_to(ROOT)} with {len(schema.get('paths', {}))} paths")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
