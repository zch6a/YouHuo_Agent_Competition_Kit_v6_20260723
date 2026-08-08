"""Syntax-check the browser bundle in the mode each file is actually loaded in.

`node --check` parses as CommonJS, which accepts things that are fatal in an ES
module - a duplicate top-level function declaration, for example, is legal in a
script and a SyntaxError in a module. Since elder.html loads elder.js with
type="module", checking it as a script lets a page-breaking error ship.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "backend/static"
MODULE_SYNTAX = re.compile(r"^\s*(?:import\s|export\s|import\()", re.MULTILINE)


def loaded_as_module(path: Path, html_sources: list[str]) -> bool:
    """A file is a module if it uses module syntax or HTML loads it as one."""
    if MODULE_SYNTAX.search(path.read_text(encoding="utf-8")):
        return True
    pattern = re.compile(
        rf'<script[^>]*type=["\']module["\'][^>]*src=["\'][^"\']*{re.escape(path.name)}["\']'
    )
    return any(pattern.search(html) for html in html_sources)


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("SKIP browser_javascript_v6: Node.js not installed")
        return 0

    html_sources = [p.read_text(encoding="utf-8") for p in STATIC.glob("*.html")]
    failures: list[str] = []
    checked = 0

    for path in sorted(STATIC.glob("*.js")):
        as_module = loaded_as_module(path, html_sources)
        source = path.read_text(encoding="utf-8")
        # The pipes must be UTF-8 explicitly: Windows would otherwise default to
        # the ANSI codepage and fail on the Chinese strings in these files.
        if as_module:
            proc = subprocess.run(
                [node, "--input-type=module", "--check", "-"],
                input=source, text=True, capture_output=True,
                encoding="utf-8", errors="replace", timeout=60,
            )
        else:
            proc = subprocess.run(
                [node, "--check", str(path)], text=True, capture_output=True,
                encoding="utf-8", errors="replace", timeout=60,
            )
        checked += 1
        mode = "module" if as_module else "script"
        if proc.returncode != 0:
            failures.append(f"{path.name} ({mode}):\n{(proc.stderr or proc.stdout).strip()[:600]}")
        else:
            print(f"  ok {path.name} [{mode}]")

    if failures:
        print(f"\nFAIL browser_javascript_v6: {len(failures)} file(s)")
        for item in failures:
            print(f"\n{item}")
        return 1
    print(f"PASS browser_javascript_v6: {checked} file(s)")

    # Behavioural check: the text handed to the synthesiser must be speakable.
    speech = subprocess.run(
        [node, str(ROOT / "backend/scripts/check_speech_text.mjs")],
        text=True, capture_output=True, encoding="utf-8", errors="replace", timeout=60,
    )
    print((speech.stdout or "").strip() or (speech.stderr or "").strip())
    return speech.returncode


if __name__ == "__main__":
    raise SystemExit(main())
