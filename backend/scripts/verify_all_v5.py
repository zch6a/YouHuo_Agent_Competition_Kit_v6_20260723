from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports"
PYTHON = sys.executable


def run_stage(name: str, command: list[str], *, timeout: int = 240) -> str:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    output_path = REPORTS / f"{name}_console.txt"
    with output_path.open("w", encoding="utf-8") as handle:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            text=True,
            stdout=handle,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
    output = output_path.read_text(encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"{name} failed with code {completed.returncode}\n{output[-4000:]}")
    return output


def validate_contracts() -> str:
    yaml.safe_load((ROOT / "xiaoyi" / "plugin_openapi.yaml").read_text(encoding="utf-8"))
    count = 0
    for path in ROOT.rglob("*.json"):
        if any(part in {".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        json.loads(path.read_text(encoding="utf-8"))
        count += 1
    return f"All YAML/JSON contracts OK ({count} JSON files)\n"


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    for runtime in (ROOT / "data" / "youhuo.db", ROOT / "data" / "youhuo.db.audit.key"):
        runtime.unlink(missing_ok=True)

    sections: list[tuple[str, str]] = []
    stages: list[tuple[str, list[str], int]] = [
        ("compile_v5", [PYTHON, "-m", "compileall", "-q", "backend"], 120),
        ("openapi_v5", [PYTHON, "backend/scripts/generate_openapi_v5.py"], 120),
        ("coverage_erase_v5", [PYTHON, "-m", "coverage", "erase"], 120),
        ("pytest_v5", [PYTHON, "-m", "coverage", "run", "-m", "pytest", "-q", "backend/tests"], 300),
        (
            "coverage_v5",
            [PYTHON, "-m", "coverage", "report", "--include=backend/youhuo/*", "--fail-under=80"],
            120,
        ),
        ("elderbench_v3_regression", [PYTHON, "backend/scripts/run_elderbench.py"], 120),
        ("elderbench_v4", [PYTHON, "backend/scripts/run_elderbench_v4.py"], 120),
        ("elderbench_v5", [PYTHON, "backend/scripts/run_elderbench_v5.py"], 120),
        ("mass_audit_v5", [PYTHON, "backend/scripts/run_mass_audit_v5.py"], 180),
        ("chaos_v5", [PYTHON, "backend/scripts/run_chaos_v5.py"], 180),
        ("secret_scan_v5", [PYTHON, "backend/scripts/scan_secrets.py"], 120),
    ]

    try:
        for name, command, timeout in stages:
            print(f"START {name}", flush=True)
            output = run_stage(name, command, timeout=timeout)
            print(f"PASS {name}", flush=True)
            sections.append((name, output))

        sections.append(("contracts_v5", validate_contracts()))

        node = shutil.which("node")
        if node:
            js_output = ""
            for file in sorted((ROOT / "backend" / "static").glob("*.js")):
                js_output += run_stage(f"node_{file.stem}_v5", [node, "--check", str(file)], timeout=60)
            sections.append(("javascript_v5", js_output + "Browser JavaScript syntax OK\n"))
        else:
            sections.append(("javascript_v5", "Node.js not installed; browser JavaScript syntax check skipped.\n"))

        for runtime in (ROOT / "data" / "youhuo.db", ROOT / "data" / "youhuo.db.audit.key"):
            runtime.unlink(missing_ok=True)
        print("START artifact_check_v5", flush=True)
        artifact_output = run_stage("artifact_check_v5", [PYTHON, "backend/scripts/check_artifacts_v5.py"], timeout=120)
        print("PASS artifact_check_v5", flush=True)
        sections.append(("artifact_check_v5", artifact_output))
    except Exception as exc:
        sections.append(("FAILED", f"{type(exc).__name__}: {exc}\n"))
        content = "".join(f"\n===== {name} =====\n{output}" for name, output in sections)
        (REPORTS / "verify_all_v5.txt").write_text(content, encoding="utf-8")
        print(content)
        return 1

    content = "".join(f"\n===== {name} =====\n{output}" for name, output in sections)
    content += "\n===== FINAL =====\nALL V5 VERIFICATION STAGES PASSED\n"
    (REPORTS / "verify_all_v5.txt").write_text(content, encoding="utf-8")
    print("ALL V5 VERIFICATION STAGES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
