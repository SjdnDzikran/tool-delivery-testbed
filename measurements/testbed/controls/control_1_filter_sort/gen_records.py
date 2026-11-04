#!/usr/bin/env python3
"""Deterministic fixture generator for control_1_filter_sort [ours].

Writes two artifacts that must stay in sync:

  fixtures/records.json  the 24 synthetic employee records (canonical data)
  instruction.md         the agent-facing task embedding the same records

Regeneration is byte-identical (fixed seed, no clock, no locale
dependence). The committed outputs are canonical; if the table design
changes, rerun ``python3 gen_records.py && python3 ref_solve.py`` and
commit both regenerated files.

Names are synthetic combinations of generic name fragments and do not
refer to real individuals. Salary figures are unitless integers.

Design targets, asserted in ``check_invariants``:

* exactly 7 of 24 records satisfy ``department == "Engineering"`` AND
  ``salary >= 90000`` (target band 6-10);
* both filter conditions are load-bearing: two non-Engineering salaries
  clear 90000, and two Engineering salaries fall below it;
* two selected salaries tie at 104750 so the name-ascending tie-break of
  control_1 is exercised;
* region sizes are North 8 / East 6 / West 6 / South 4; region names have
  distinct initials so case-sensitive and case-insensitive alphabetical
  order agree;
* the North average (749945 / 8 = 93743.125) is a round-half-to-even case,
  the East and West averages have repeating decimal expansions, and the
  South average is exact (85600.0) -- the group/aggregate view that
  control_2_group_aggregate computes over the identical record table.
"""
from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEED = 20260301

DEPARTMENTS = ["Engineering", "Design", "Marketing", "Sales", "Finance"]
REGIONS = ["North", "South", "East", "West"]

FIRST_NAMES = [
    "Aiko", "Bruno", "Celine", "Dario", "Elsa", "Farid", "Greta", "Hiro",
    "Ines", "Jonas", "Kaya", "Luca", "Mina", "Nils", "Omar", "Pia",
    "Ravi", "Sofia", "Tomas", "Uma", "Viktor", "Wren", "Ximena", "Yusuf",
]
LAST_NAMES = [
    "Ackermann", "Bergström", "Caldwell", "Dietrich", "Everly", "Fontaine",
    "Garza", "Holm", "Ibarra", "Jansen", "Keller", "Lindgren", "Mercer",
    "Nakamura", "Osei", "Peralta", "Quist", "Rinaldi", "Sorensen", "Tanaka",
    "Ulrich", "Vance", "Weiss", "Yilmaz",
]

# (department, region, salary) per record, in id order E01..E24.
ROWS = [
    ("Engineering", "North", 128400),  # E01 selected
    ("Design", "East", 84500),         # E02
    ("Marketing", "West", 79700),      # E03
    ("Sales", "South", 96200),         # E04 salary >= 90000 but not Engineering
    ("Engineering", "North", 121000),  # E05 selected
    ("Finance", "East", 91250),        # E06 salary >= 90000 but not Engineering
    ("Engineering", "West", 118500),   # E07 selected
    ("Design", "North", 81200),        # E08
    ("Marketing", "North", 75800),     # E09
    ("Sales", "East", 88300),          # E10
    ("Engineering", "West", 112300),   # E11 selected
    ("Finance", "South", 84900),       # E12
    ("Engineering", "North", 104750),  # E13 selected (salary tie with E19)
    ("Design", "East", 76900),         # E14
    ("Marketing", "West", 72400),      # E15
    ("Sales", "South", 83100),         # E16
    ("Engineering", "North", 98600),   # E17 selected
    ("Finance", "East", 79600),        # E18
    ("Engineering", "West", 104750),   # E19 selected (salary tie with E13)
    ("Design", "North", 71300),        # E20
    ("Marketing", "North", 68895),     # E21 odd salary -> North region total is odd
    ("Sales", "East", 67500),          # E22
    ("Engineering", "West", 87400),    # E23 Engineering but below 90000
    ("Engineering", "South", 78200),   # E24 Engineering but below 90000
]

INSTRUCTION_TEMPLATE = """# Employee Records — Filter and Sort

The HR system of a small robotics company exported the following snapshot of 24 employee records.

__RECORDS_TABLE__

## Task

Working from the table above:

1. Select every record whose `department` is exactly `Engineering` **and** whose `salary` is at least `90000`.
2. Sort the selected records by `salary` in descending order. If two selected records have the same `salary`, order them by `name` in ascending alphabetical order.
3. Write the result to a file named `result.json`.

`result.json` must be a single valid JSON file encoded as UTF-8, containing a JSON array with one element per selected record, in the sorted order. Each element must be a JSON object with exactly the keys `id`, `name`, and `salary` — in that key order — with the values copied unchanged from the record. Include no other keys, records, or commentary in the file.
"""


def build_records() -> list[dict]:
    rng = random.Random(SEED)
    first = FIRST_NAMES[:]
    last = LAST_NAMES[:]
    rng.shuffle(first)
    rng.shuffle(last)
    records = []
    for index, (department, region, salary) in enumerate(ROWS, start=1):
        records.append({
            "id": f"E{index:02d}",
            "name": f"{first[index - 1]} {last[index - 1]}",
            "department": department,
            "region": region,
            "salary": salary,
            "hired": rng.randint(2015, 2024),
        })
    return records


def _has_third_decimal_five(salaries: list[int]) -> bool:
    """True when the mean's exact decimal expansion ends in 5 at the third decimal."""
    mean = sum(salaries) / len(salaries)
    scaled = mean * 1000
    return abs(scaled - round(scaled)) < 1e-6 and round(scaled) % 10 == 5


def check_invariants(records: list[dict]) -> None:
    assert len(records) == 24
    assert [r["id"] for r in records] == [f"E{i:02d}" for i in range(1, 25)]
    assert len({r["name"] for r in records}) == 24, "names must be unique"
    assert {r["department"] for r in records} == set(DEPARTMENTS)
    assert {r["region"] for r in records} == set(REGIONS)
    for record in records:
        assert isinstance(record["salary"], int) and record["salary"] > 0
        assert isinstance(record["hired"], int) and 2015 <= record["hired"] <= 2024
    selected = [r for r in records
                if r["department"] == "Engineering" and r["salary"] >= 90000]
    assert 6 <= len(selected) <= 10, f"filter selects {len(selected)} records, target 6-10"
    salary_counts = Counter(r["salary"] for r in selected)
    assert any(count >= 2 for count in salary_counts.values()), \
        "no salary tie among the selected records"
    region_sizes = Counter(r["region"] for r in records)
    assert region_sizes == Counter({"North": 8, "East": 6, "West": 6, "South": 4})
    by_region: dict[str, list[int]] = defaultdict(list)
    for record in records:
        by_region[record["region"]].append(record["salary"])
    assert any(_has_third_decimal_five(v) for v in by_region.values()), \
        "no x.xx5-style average rounding case present"


def render_table(records: list[dict]) -> str:
    lines = [
        "| id | name | department | region | salary | hired |",
        "|---|---|---|---|---:|---:|",
    ]
    for record in records:
        lines.append(
            f"| {record['id']} | {record['name']} | {record['department']} "
            f"| {record['region']} | {record['salary']} | {record['hired']} |"
        )
    return "\n".join(lines)


def main() -> None:
    records = build_records()
    check_invariants(records)
    fixtures = HERE / "fixtures"
    fixtures.mkdir(exist_ok=True)
    records_path = fixtures / "records.json"
    records_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    instruction = INSTRUCTION_TEMPLATE.replace("__RECORDS_TABLE__", render_table(records))
    (HERE / "instruction.md").write_text(instruction, encoding="utf-8")
    print(f"wrote {records_path.relative_to(HERE)} and instruction.md "
          f"(24 records, invariants OK)")


if __name__ == "__main__":
    main()
