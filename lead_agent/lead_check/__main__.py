"""python -m lead_agent.lead_check <csv>... --out <xlsx> [--top-n 3]

Prints the chat summary (no names) and writes the workbook.
"""
import argparse
import json
import os
from pathlib import Path

from .engine import run_lead_check
from .workbook import write_workbook

ap = argparse.ArgumentParser()
ap.add_argument("csv", nargs="+")
ap.add_argument("--out", required=True)
ap.add_argument("--top-n", type=int)
a = ap.parse_args()
result = run_lead_check([(os.path.basename(c), Path(c).read_bytes()) for c in a.csv], top_n=a.top_n)
write_workbook(result, a.out)
print(json.dumps(result["summary"], indent=2))
