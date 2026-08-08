from __future__ import annotations

import json
import tempfile
from pathlib import Path

from youhuo.api import create_app

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        app = create_app(Path(td) / "openapi.db", demo_mode=True)
        schema = app.openapi()
    output = ROOT / "xiaoyi/plugin_openapi_v5.generated.json"
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "paths": len(schema.get("paths", {})), "version": schema.get("info", {}).get("version")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
