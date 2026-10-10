"""Check publishable files without printing any matched credential values."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(  # noqa: S603 -- fixed Git command, no user input
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
    )
    names = {p.decode() for p in result.stdout.split(b"\0") if p}
    patterns = [
        re.compile(r"gh[pousr]_" + r"[A-Za-z0-9]{30,}"),
        re.compile(r"github_pat_" + r"[A-Za-z0-9_]{30,}"),
        re.compile(r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"postgres(?:ql)?://[^\s/:]+:[^\s/@]+@"),
    ]
    failures: list[str] = []
    for name in sorted(names):
        path = root / name
        if (
            "Analizar mercados deportivos" in name
            or path.name.startswith("real_bets")
            or (path.name.startswith("sports-capture-") and path.suffix == ".json")
            or path.suffix in {".dump", ".backup", ".pem", ".key"}
            or (path.name.startswith(".env") and path.name != ".env.example")
        ):
            failures.append(f"Forbidden public file: {name}")
            continue
        if not path.is_file():
            continue
        content = path.read_text(errors="replace")
        for number, line in enumerate(content.splitlines(), 1):
            if any(pattern.search(line) for pattern in patterns):
                failures.append(f"Potential credential: {name}:{number}")
    if failures:
        print("\n".join(failures))
        return 1
    print(
        f"Public file check passed ({len(names)} files; no source transcript or credentials found)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
