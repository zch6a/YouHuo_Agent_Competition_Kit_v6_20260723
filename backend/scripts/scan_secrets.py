from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXCLUDES = {".git", ".venv", "__pycache__", ".pytest_cache"}
PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{24,}", re.I),
    re.compile(r"(?:api[_-]?key|secret)\s*[:=]\s*['\"][^'\"]{12,}['\"]", re.I),
]


def main() -> int:
    findings: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in EXCLUDES for part in path.parts):
            continue
        if path.suffix.lower() in {".zip", ".png", ".jpg", ".jpeg", ".db", ".pyc"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in PATTERNS:
            for match in pattern.finditer(text):
                value = match.group(0)
                if "replace_me" in value or "example.invalid" in value:
                    continue
                findings.append(f"{path.relative_to(ROOT)}: {value[:50]}")
    if findings:
        print("Potential secrets found:")
        print("\n".join(findings))
        return 1
    print("Secret scan passed: no credential-like values detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
