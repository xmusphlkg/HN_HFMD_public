#!/usr/bin/env python3
"""Convenience entry point for a fresh-history public export."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hfmd.privacy.export import export_public_repository  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--synthetic-source", type=Path)
    parser.add_argument("--synthetic-results-source", type=Path)
    parser.add_argument("--no-git", action="store_true")
    args = parser.parse_args()
    result = export_public_repository(
        source_root=ROOT,
        destination=args.destination,
        allowlist_path=ROOT / "public_repo" / "allowlist.json",
        synthetic_source=args.synthetic_source,
        synthetic_results_source=args.synthetic_results_source,
        initialize_git=not args.no_git,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
