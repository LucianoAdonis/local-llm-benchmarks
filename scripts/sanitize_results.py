#!/usr/bin/env python3
"""Copy benchmark JSON into a public folder while redacting local paths and secrets."""
from __future__ import annotations
import argparse
import json
import re
from pathlib import Path

SECRET_RE = re.compile(r"(?i)\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_]{20,})\b")
WINDOWS_USER_PATH_RE = re.compile(r"(?i)[A-Z]:\\Users\\[^\\/\"']+")
LOCAL_URL_RE = re.compile(r"(?i)https?://(?:127\.0\.0\.1|localhost)(?::\d+)?")


def clean(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if re.search(r"(?i)^(api[_-]?key|access[_-]?token|refresh[_-]?token|token|credential|secret|authorization)$", str(key)) and item:
                result[key] = "<REDACTED>"
            else:
                result[key] = clean(item)
        return result
    if isinstance(value, list):
        return [clean(item) for item in value]
    if isinstance(value, str):
        value = WINDOWS_USER_PATH_RE.sub("<USER_HOME>", value)
        value = LOCAL_URL_RE.sub("<LOCAL_API_URL>", value)
        return SECRET_RE.sub("<REDACTED_SECRET>", value)
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    data = json.loads(args.source.read_text(encoding="utf-8-sig"))
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(json.dumps(clean(data), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
