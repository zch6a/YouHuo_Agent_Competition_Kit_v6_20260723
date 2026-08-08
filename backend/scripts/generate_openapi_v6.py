from __future__ import annotations

import json
import tempfile
from pathlib import Path

from youhuo.api import create_app

ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        app = create_app(Path(td) / "openapi.db", demo_mode=True)
        try:
            schema = app.openapi()
        finally:
            # Windows refuses to delete an open SQLite file, so the app's
            # connection must be closed before the temp directory unwinds.
            app.state.db.close()
    output = ROOT / "xiaoyi/plugin_openapi_v6.generated.json"
    output.write_text(json.dumps(schema, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "paths": len(schema.get("paths", {})), "version": schema.get("info", {}).get("version")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
