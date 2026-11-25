#!/usr/bin/env python3
"""Copy benchmark JSON into a public folder while redacting local paths and secrets.

Kept for the v1 workflow. The redaction rules now live in ``llmbench/sanitize.py``, which
also covers macOS and Linux home folders, LAN addresses and more key formats. The same
thing is available as ``python -m llmbench sanitize SOURCE DESTINATION``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llmbench.sanitize import clean, sanitize_file  # noqa: E402,F401  (clean is re-exported for older callers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    sanitize_file(args.source, args.destination)


if __name__ == "__main__":
    main()
