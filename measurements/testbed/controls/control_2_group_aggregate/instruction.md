# Employee Records — Group and Aggregate

The HR system of a small robotics company exported the following snapshot of 24 employee records.

| id | name | department | region | salary | hired |
|---|---|---|---|---:|---:|
| E01 | Luca Osei | Engineering | North | 128400 | 2017 |
| E02 | Yusuf Bergström | Design | East | 84500 | 2021 |
| E03 | Celine Weiss | Marketing | West | 79700 | 2015 |
| E04 | Viktor Everly | Sales | South | 96200 | 2016 |
| E05 | Bruno Lindgren | Engineering | North | 121000 | 2019 |
| E06 | Hiro Holm | Finance | East | 91250 | 2024 |
| E07 | Uma Ackermann | Engineering | West | 118500 | 2019 |
| E08 | Sofia Keller | Design | North | 81200 | 2016 |
| E09 | Farid Caldwell | Marketing | North | 75800 | 2023 |
| E10 | Nils Mercer | Sales | East | 88300 | 2023 |
| E11 | Greta Sorensen | Engineering | West | 112300 | 2018 |
| E12 | Omar Jansen | Finance | South | 84900 | 2015 |
| E13 | Tomas Ulrich | Engineering | North | 104750 | 2024 |
| E14 | Kaya Yilmaz | Design | East | 76900 | 2018 |
| E15 | Ravi Peralta | Marketing | West | 72400 | 2023 |
| E16 | Aiko Nakamura | Sales | South | 83100 | 2015 |
| E17 | Dario Fontaine | Engineering | North | 98600 | 2019 |
| E18 | Pia Dietrich | Finance | East | 79600 | 2019 |
| E19 | Mina Vance | Engineering | West | 104750 | 2020 |
| E20 | Ines Tanaka | Design | North | 71300 | 2021 |
| E21 | Ximena Quist | Marketing | North | 68895 | 2022 |
| E22 | Elsa Rinaldi | Sales | East | 67500 | 2017 |
| E23 | Wren Garza | Engineering | West | 87400 | 2019 |
| E24 | Jonas Ibarra | Engineering | South | 78200 | 2023 |

## Task

Working from the table above, group **all 24 records** by `region` (each record belongs to exactly one region). For every region compute:

1. `headcount` — the number of records in that region (an integer);
2. `total_salary` — the sum of the `salary` values of that region's records (an integer);
3. `avg_salary` — `total_salary` divided by `headcount`, rounded to 2 decimals, rounding half away from zero (a JSON number, not a string).

Write the result to a file named `result.json`. It must be a single valid JSON file encoded as UTF-8, containing one JSON object with exactly one key per region, with the region keys sorted alphabetically. Each region's value must be a JSON object with exactly the keys `headcount`, `total_salary`, and `avg_salary` as defined above. Include no other keys or commentary in the file.
