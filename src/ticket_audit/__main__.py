"""Run the ticket audit on a batch.

    uv run python -m ticket_audit data/generated/audit                  # generator-truth engine (no OCR)
    uv run python -m ticket_audit data/generated/audit --engine azure   # Azure Document Intelligence
"""
import argparse
from pathlib import Path

from ticket_audit.extract.azure import AzureExtractor
from ticket_audit.extract.truth import TruthExtractor
from ticket_audit.pipeline import run_batch


ROOT = Path(__file__).resolve().parents[2]


def make_extractor(engine: str, batch_dir: Path, max_pages: int):
    if engine == "truth":
        return TruthExtractor(batch_dir / "truth" / "documents.json")
    return AzureExtractor.from_env(ROOT / ".env", raw_dir=batch_dir / "out" / "azure" / "raw", max_pages=max_pages)


def main() -> None:
    ap = argparse.ArgumentParser(description="Audit a batch of tickets against dispatch and rates.")
    ap.add_argument("batch", type=Path, help="batch folder with inbox/ and tms.sqlite")
    ap.add_argument("--engine", default="truth", choices=["truth", "azure"])
    ap.add_argument("--max-pages", type=int, default=300,
                    help="stop before sending more than this many pages to Azure in one run (free tier: 500/month)")
    args = ap.parse_args()
    s = run_batch(args.batch, make_extractor(args.engine, args.batch, args.max_pages))
    print(f"run {s.run_id}: {s.documents} documents ({s.extracted_now} read now, rest from cache)")
    print(f"  approved {s.approved} · approved with standby added {s.approved_adjusted} · "
          f"exceptions {s.exceptions} · missing tickets {s.missing_tickets}")
    print(f"  outputs in {s.out_dir}")


if __name__ == "__main__":
    main()
