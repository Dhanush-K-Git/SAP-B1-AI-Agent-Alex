"""
Generate the tool catalog + example questions from the semantic entities.

Pure Python — no database or API needed. Run from backend/:
    python scripts/build_tools.py --out output

Writes:
    output/tools.json              all generated query-pattern tools
    output/example_questions.json  a spread of demo questions for the UI
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.generator import (  # noqa: E402
    example_questions,
    generate_tools,
    tools_as_dicts,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="output")
    args = parser.parse_args()

    tools = generate_tools()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "tools.json").write_text(
        json.dumps(tools_as_dicts(tools), indent=2), encoding="utf-8"
    )
    questions = example_questions(tools, per_domain=2)
    (out_dir / "example_questions.json").write_text(
        json.dumps(questions, indent=2), encoding="utf-8"
    )

    print(f"Generated {len(tools)} tools across "
          f"{len({t.domain for t in tools})} domains.")
    print(f"Wrote {out_dir/'tools.json'} and {out_dir/'example_questions.json'}\n")
    print("Sample tools:")
    for t in tools[:8]:
        print(f"  [{t.domain:13}] {t.name:32} → {t.result_type}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
