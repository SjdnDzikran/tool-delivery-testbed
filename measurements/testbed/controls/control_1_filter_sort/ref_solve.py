#!/usr/bin/env python3
"""Independent reference solution for control_1_filter_sort [ours].

Reads fixtures/records.json and writes expected/result.json using a
straightforward implementation that shares no code with verify.py. The
expected output is committed; agents never see it.
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    with (HERE / "fixtures" / "records.json").open(encoding="utf-8") as fh:
        records = json.load(fh)
    selected = [r for r in records
                if r["department"] == "Engineering" and r["salary"] >= 90000]
    selected.sort(key=lambda r: (-r["salary"], r["name"]))
    result = [{"id": r["id"], "name": r["name"], "salary": r["salary"]}
              for r in selected]
    out_dir = HERE / "expected"
    out_dir.mkdir(exist_ok=True)
    with (out_dir / "result.json").open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote expected/result.json ({len(result)} records)")


if __name__ == "__main__":
    main()
