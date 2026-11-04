#!/usr/bin/env python3
"""Independent reference solution for control_2_group_aggregate [ours].

Reads fixtures/records.json and writes expected/result.json using a
straightforward implementation that shares no code with verify.py. The
expected output is committed; agents never see it.

avg_salary uses exact decimal arithmetic quantized to two places with
ROUND_HALF_UP (half away from zero), matching the instruction's pinned
"rounded to 2 decimals, rounding half away from zero".
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    with (HERE / "fixtures" / "records.json").open(encoding="utf-8") as fh:
        records = json.load(fh)
    groups: dict[str, dict[str, int]] = {}
    for record in records:
        bucket = groups.setdefault(record["region"], {"headcount": 0, "total_salary": 0})
        bucket["headcount"] += 1
        bucket["total_salary"] += record["salary"]
    result = {}
    for region in sorted(groups):
        stats = groups[region]
        result[region] = {
            "headcount": stats["headcount"],
            "total_salary": stats["total_salary"],
            "avg_salary": float(
                (Decimal(stats["total_salary"]) / Decimal(stats["headcount"]))
                .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        }
    out_dir = HERE / "expected"
    out_dir.mkdir(exist_ok=True)
    with (out_dir / "result.json").open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote expected/result.json ({len(result)} regions)")


if __name__ == "__main__":
    main()
