from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

#: Directories that legitimately hold large or generated content we never scan.
_SKIP_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", "node_modules"}
#: Anything matching these must not exist anywhere in a release tree: runtime
#: databases (including WAL sidecars, which hold committed rows), the generated
#: HMAC audit-chain key, and the optional neural voice model.
_LEAK_SUFFIXES = (".db", ".db-wal", ".db-shm", ".audit.key", ".onnx")


def _leaked_artifacts(root: Path) -> list[Path]:
    found = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.name.endswith(_LEAK_SUFFIXES):
            found.append(path)
    return found


def main() -> int:
    checks: dict[str, bool] = {}
    result_extra: dict[str, object] = {}
    required = [
        "README.md", "PACKAGE_INDEX.md", "THIRD_PARTY_NOTICES.md",
        "competition_materials/03_800字作品介绍.md", "competition_materials/06_V6核心创新与技术摘要.md",
        "docs/28_V6_CHAMPIONSHIP_PLAN.md", "docs/29_V6_RESEARCH_GROUNDING.md",
        "docs/30_V6_USER_STUDY_PROTOCOL.md", "docs/31_V6_DEMO_SCRIPT.md", "docs/32_V6_JUDGE_QA.md",
        "evaluation/voicebench_youhuo_v6.jsonl",
        "backend/youhuo/v6_models.py", "backend/youhuo/v6_services.py", "backend/youhuo/v6_store.py", "backend/youhuo/v6_api.py",
        "backend/static/judge.html", "backend/static/judge.js",
        "harmonyos/entry/src/main/ets/pages/FinalistWalkthroughPage.ets",
        "harmonyos/entry/src/main/ets/services/CoreSpeechAdapter.ets",
        "harmonyos/entry/src/main/ets/services/PushSafetyAdapter.ets",
        "harmonyos/entry/src/main/ets/services/DistributedProfileAdapter.ets",
        "harmonyos/entry/src/main/ets/services/AgentCompanionAdapter.ets",
        "xiaoyi/plugin_openapi_v6.generated.json", "xiaoyi/workflows/youhuo_workflow.json",
        "xiaoyi/skills/youhuo-cognitive-load/SKILL.md", "xiaoyi/skills/youhuo-reliance-card/SKILL.md",
        "xiaoyi/skills/youhuo-safe-preview/SKILL.md",
        "reports/voicebench_v6.json", "reports/mass_audit_v6_500000.json",
        "reports/mass_audit_v5_1000000.json", "reports/load_v6_5000.json",
        "reports/chaos_v5_400.json", "reports/http_smoke_v6.json", "reports/TEST_REPORT.md",
    ]
    checks["required_files"] = all((ROOT / item).is_file() for item in required)

    yaml.safe_load((ROOT / "xiaoyi/plugin_openapi.yaml").read_text(encoding="utf-8"))
    checks["openapi_yaml"] = True
    json_files = [
        "xiaoyi/plugin_openapi_v6.generated.json", "xiaoyi/workflows/youhuo_workflow.json",
        "xiaoyi/a2a/agent_card.json", "mcp/tool_manifest.json",
        "harmonyos/entry/src/main/resources/base/profile/main_pages.json",
        "reports/voicebench_v6.json", "reports/mass_audit_v6_500000.json",
        "reports/mass_audit_v5_1000000.json", "reports/load_v6_5000.json",
        "reports/chaos_v5_400.json", "reports/http_smoke_v6.json",
    ]
    parsed = {rel: json.loads((ROOT / rel).read_text(encoding="utf-8")) for rel in json_files}
    checks["json_contracts"] = True

    openapi = parsed["xiaoyi/plugin_openapi_v6.generated.json"]
    required_paths = {
        "/v6/profiles/{elder_id}", "/v6/interaction/plan", "/v6/reliance/card",
        "/v6/actions/preview", "/v6/semantic/parse", "/v6/studies/sessions",
        "/v6/studies/observations", "/v6/studies/summary", "/v6/competition/evidence",
    }
    checks["openapi_v6_paths"] = required_paths.issubset(openapi["paths"]) and len(openapi["paths"]) >= 89
    checks["openapi_version"] = openapi["info"]["version"] == "6.0.0"

    workflow = parsed["xiaoyi/workflows/youhuo_workflow.json"]
    node_ids = {node.get("id") for node in workflow.get("nodes", [])}
    checks["workflow_v6_nodes"] = {
        "voice_consensus_v6", "semantic_gateway_v6", "cognitive_load_governor_v6",
        "safe_preview_v6", "reliance_card_v6", "study_instrumentation_v6",
    }.issubset(node_ids)
    checks["workflow_truth_warning"] = "not a fabricated official Xiaoyi export" in workflow.get("warning", "")

    skill_paths = list((ROOT / "xiaoyi/skills").glob("*/SKILL.md"))
    checks["skill_count"] = len(skill_paths) >= 13
    checks["skill_policy_sections"] = all(
        "policy" in p.read_text(encoding="utf-8").lower() for p in skill_paths
    )

    pages = parsed["harmonyos/entry/src/main/resources/base/profile/main_pages.json"]["src"]
    checks["harmonyos_v6_page_registered"] = "pages/FinalistWalkthroughPage" in pages

    manifest = parsed["mcp/tool_manifest.json"]
    high = [item for item in manifest["tools"] if item["name"] in {"youhuo.execute_high_risk", "youhuo.open_break_glass"}]
    checks["generic_high_risk_disabled"] = bool(high) and all(
        item.get("enabled") is False and item.get("requires_human_confirmation") is True for item in high
    )

    voice = parsed["reports/voicebench_v6.json"]
    mass_v6 = parsed["reports/mass_audit_v6_500000.json"]
    mass_v5 = parsed["reports/mass_audit_v5_1000000.json"]
    load = parsed["reports/load_v6_5000.json"]
    chaos = parsed["reports/chaos_v5_400.json"]
    smoke = parsed["reports/http_smoke_v6.json"]
    checks["voicebench_passed"] = voice["passed"] == 800 and voice["failed"] == 0
    checks["mass_v6_passed"] = mass_v6["passed"] == 500_000 and mass_v6["failed"] == 0
    checks["mass_v5_regression_passed"] = mass_v5["passed"] == 1_000_000 and mass_v5["failed"] == 0
    checks["load_passed"] = load["successful"] == 5_000 and load["failed"] == 0
    checks["chaos_passed"] = chaos["scenarios"] == 400 and chaos["failed"] == 0
    checks["http_smoke_passed"] = smoke["passed"] is True and smoke["version"] == "6.0.0"

    checks["project_version"] = 'version = "6.0.0"' in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    # These used to be three hard-coded paths under data/. The app actually writes
    # to whatever directory it is launched from — backend/data/ when uvicorn runs
    # with --app-dir backend — so the check reported a clean release while a live
    # database and a generated audit key sat one directory over, and both were
    # committed. Scan the tree instead of guessing where the files will land.
    leaked = sorted(str(path.relative_to(ROOT)) for path in _leaked_artifacts(ROOT))
    checks["no_runtime_database"] = not any(
        name.endswith((".db", ".db-wal", ".db-shm")) for name in leaked
    )
    checks["no_generated_audit_key"] = not any(name.endswith(".audit.key") for name in leaked)
    checks["no_env_file"] = not (ROOT / ".env").exists()
    # The optional neural voice model is a ~160MB download, never part of the kit.
    checks["no_bundled_tts_model"] = not any(ROOT.glob("**/*.onnx"))
    if leaked:
        result_extra["leaked_artifacts"] = leaked

    result = {"version": "6.0.0", "passed": all(checks.values()), "checks": checks, **result_extra}
    output = ROOT / "reports/artifact_check_v6.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
