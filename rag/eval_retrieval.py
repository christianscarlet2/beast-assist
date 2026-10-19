#!/usr/bin/env python3
"""Retrieval quality, measured: for each question in rag/questions.yaml, is a passage from the expected
course (and, when given, a lesson whose title contains the expected words) in the top k?

Reports hit@1, hit@k and MRR (mean reciprocal rank). Use it to compare chunk sizes, embedding models
or k before trusting the answers. Exit 1 if hit@k is under --min."""
import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from ask import retrieve  # noqa: E402


def relevant(hit: dict, q: dict) -> bool:
    if q.get("course") and hit["track"] != q["course"]:
        return False
    want = q.get("title_contains")
    return not want or want.lower() in hit["title"].lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--min", type=float, default=0.7)
    a = ap.parse_args()
    qs = yaml.safe_load((Path(__file__).parent / "questions.yaml").read_text())
    h1 = hk = rr = 0.0
    for q in qs:
        hits = retrieve(q["question"], a.k)
        rank = next((i for i, h in enumerate(hits, 1) if relevant(h, q)), None)
        h1 += rank == 1
        hk += rank is not None
        rr += 1 / rank if rank else 0
        print(f"{'hit ' + str(rank) if rank else 'MISS  '}  {q['question'][:70]}")
    n = len(qs)
    print(f"\nhit@1 {h1 / n:.2f}   hit@{a.k} {hk / n:.2f}   MRR {rr / n:.2f}   ({n} questions)")
    return 0 if hk / n >= a.min else 1


if __name__ == "__main__":
    sys.exit(main())
