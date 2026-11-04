---
name: canary-skill
description: Run the canary-cli program to produce a CANARY_ECHO_OK line. Use when a task asks for a canary echo or canary verification output.
---

# canary-skill

To produce a canary echo of a text `T`, run:

    canary-cli echo "T"

The program prints exactly one line starting with `CANARY_ECHO_OK:`.
Write that line, unmodified, to the location the task asks for.
This skill is task-neutral: it contains no campaign-task solutions.
