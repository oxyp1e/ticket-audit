"""Run the ticket audit on a batch.

    uv run python -m ticket_audit data/generated/audit             # generator-truth engine (no OCR)
"""
import argparse
from pathlib import Path

from ticket_audit.extract.truth import TruthExtractor
from ticket_audit.pipeline import run_batch


def make_extractor(engine: str, batch_dir: Path):
    if engine == "truth":
        return TruthExtractor(batch_dir / "truth" / "documents.json")
    raise SystemExit(f"unknown engine: {engine}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit a batch of tickets against dispatch and rates.")
    ap.add_argument("batch", type=Path, help="batch folder with inbox/ and tms.sqlite")
    ap.add_argument("--engine", default="truth", choices=["truth"])
    args = ap.parse_args()
    s = run_batch(args.batch, make_extractor(args.engine, args.batch))
    print(f"run {s.run_id}: {s.documents} documents ({s.extracted_now} read now, rest from cache)")
    print(f"  approved {s.approved} · approved with standby added {s.approved_adjusted} · "
          f"exceptions {s.exceptions} · missing tickets {s.missing_tickets}")
    print(f"  outputs in {s.out_dir}")


if __name__ == "__main__":
    main()
