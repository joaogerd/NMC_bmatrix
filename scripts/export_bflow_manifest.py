#!/usr/bin/env python3
"""Convert the neutral MPAS product manifest into the BFLOW input contract."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

EXPECTED = ("valid_time", "f048_state", "f024_state", "f048_restart", "f024_restart")


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read and validate the MPAS manifest emitted by ``mpaswf``.

    Parameters
    ----------
    path : pathlib.Path
        Input tab-separated MPAS product manifest.

    Returns
    -------
    list[dict[str, str]]
        Validated manifest rows.
    """
    if not path.is_file():
        raise FileNotFoundError(f"MPAS manifest does not exist: {path}")
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED:
            raise ValueError(f"Unexpected MPAS manifest columns: {reader.fieldnames!r}")
        rows = list(reader)
    if not rows:
        raise ValueError("MPAS manifest has no forecast pairs.")
    for row in rows:
        for field in EXPECTED:
            if not row.get(field):
                raise ValueError(f"Empty {field} in MPAS manifest row: {row!r}")
        for field in ("f048_state", "f024_state", "f048_restart", "f024_restart"):
            product = Path(row[field])
            if not product.is_file() or product.stat().st_size == 0:
                raise FileNotFoundError(f"Manifest product is absent or empty: {product}")
    return rows


def main() -> int:
    """Write a BFLOW ``valid_time/f048/f024`` manifest from MPAS products."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="mpaswf MPAS product manifest")
    parser.add_argument("--output", type=Path, required=True, help="BFLOW manifest path")
    args = parser.parse_args()

    rows = read_rows(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=("valid_time", "f048", "f024"), delimiter="\t")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {"valid_time": row["valid_time"], "f048": row["f048_state"], "f024": row["f024_state"]}
            )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
