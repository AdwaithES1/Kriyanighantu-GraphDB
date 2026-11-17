"""Refresh the whole dataset in Neo4j from the three Excel files, then rebuild the synonym graph.

This replaces the old Excel -> MongoDB script. It deletes the existing entries and inserts the
spreadsheet rows, so edits made in the data-entry portal since the last export are lost.

  python pipeline/import_excel.py                    from dataset/data/
  python pipeline/import_excel.py --dir excel        from another folder
  python pipeline/import_excel.py --if-empty --wait 180   only if the database has no entries (used at start-up)

Expected files: "Look-up entry.xlsx", "Root-Entry.xlsx", "Verb-Entries.xlsx".
"""
import argparse
import sys
from pathlib import Path

import pandas as pd
from neo4j import GraphDatabase

import entries
import load_neo4j
from settings import connection

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "dataset" / "data"


def read_excel(folder, kind):
    """Rows of one spreadsheet as entry dicts (text, None for empty cells), in file order."""
    spec = entries.KINDS[kind]
    path = Path(folder) / spec["file"]
    if not path.exists():
        raise SystemExit(f"Excel file not found: {path}")
    frame = pd.read_excel(path, dtype=str).dropna(how="all")
    renamed = {column: spec["excel"][str(column).strip()] for column in frame.columns
               if str(column).strip() in spec["excel"]}
    missing = [f for f in spec["required"] if f not in renamed.values()]
    if missing:
        raise SystemExit(f"{path.name}: no column for {', '.join(missing)}. Columns found: {list(frame.columns)}")
    frame = frame.rename(columns=renamed)[list(dict.fromkeys(renamed.values()))]
    frame = frame.astype(object).where(pd.notna(frame), None)
    return frame.to_dict(orient="records")


def main():
    parser = argparse.ArgumentParser(description="Refresh the dataset in Neo4j from the Excel files.")
    parser.add_argument("--dir", default=str(DEFAULT_DIR), help="folder holding the three .xlsx files")
    parser.add_argument("--if-empty", action="store_true", help="do nothing if the database already has entries")
    parser.add_argument("--wait", type=int, default=0, metavar="SECONDS", help="wait this long for Neo4j to start")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    uri, auth, database = connection()
    with GraphDatabase.driver(uri, auth=auth, notifications_min_severity="OFF") as driver:
        load_neo4j.wait_for(driver, args.wait)
        with driver.session(database=database) as session:
            if args.if_empty and entries.count(session):
                print("Dataset already in the database; skipping the Excel import.")
                return
            rows = {kind: read_excel(args.dir, kind) for kind in entries.KINDS}
            print(f"Excel folder: {args.dir}")
            for kind, items in rows.items():
                print(f"  {entries.KINDS[kind]['file']:<22} {len(items)} rows "
                      f"(replacing {entries.count(session, kind)} existing entries)")
            entries.replace_all(session, rows)
            report = entries.rebuild_graph(session)
            print("Entries now:", {kind: entries.count(session, kind) for kind in entries.KINDS})
            print("Synonym graph:", load_neo4j.counts(session))
            print(f"Verbs without a usable meaning: {report['verbs_without_shade']}")
            print("Dataset successfully refreshed.")


if __name__ == "__main__":
    main()
