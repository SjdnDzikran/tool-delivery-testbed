#!/usr/bin/env python3
"""Verifier for the Brave capability smoke [ours]."""
from __future__ import annotations

import os
import sys
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import check, finish, load_json_file, parse_artifacts  # noqa: E402

TASK_ID = "cap_brave"


def main() -> int:
    artifacts = parse_artifacts(sys.argv[1:])
    checks = []
    result = load_json_file(os.path.join(artifacts, "brave.json"),
                            os.path.join(artifacts, "verification.json"))
    ok = isinstance(result, dict)
    checks.append(check("brave.json is an object", ok, f"got {type(result).__name__}"))
    if not ok:
        return finish(TASK_ID, artifacts, checks)
    keys = set(result)
    keys_ok = keys == {"url", "title"}
    checks.append(check("exact keys {url,title}", keys_ok, f"got {sorted(keys)}"))
    url = result.get("url")
    is_url = isinstance(url, str) and urlparse(url).scheme in ("http", "https")
    checks.append(check("url is http(s)", bool(is_url), repr(url)[:120]))
    title = result.get("title")
    title_ok = isinstance(title, str) and len(title.strip()) > 0
    checks.append(check("title is a non-empty string", title_ok))
    haystack = f"{url or ''} {title or ''}".lower()
    topic_ok = "gadjah mada" in haystack or "ugm.ac.id" in haystack
    checks.append(check("result is about Gadjah Mada", topic_ok, haystack[:160]))
    return finish(TASK_ID, artifacts, checks)


if __name__ == "__main__":
    sys.exit(main())
