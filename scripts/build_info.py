"""Run the test suite and the mutation check, and write build-info.json for the site to show.

Run at image build time, so the deployed site states what was tested in the exact code it runs.

    uv run python scripts/build_info.py [--commit SHA]
"""
import argparse
import json
import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Deliberate breaks: each must make a fitness function fail. If one doesn't, the tests can't be trusted.
MUTANTS = [
    ("Signature check removed", "src/ticket_audit/domain/rules.py",
     '    if not h.signed:\n        reasons.append(_r("NO_SIGNATURE"))', "    pass"),
    ("Weight tolerance widened to 5 t", "src/ticket_audit/domain/rules.py",
     '"weight_tolerance_t": 0.05', '"weight_tolerance_t": 5.0'),
    ("Fallback dispatch match auto-approved", "src/ticket_audit/domain/rules.py",
     'ADJUSTMENTS = {"STANDBY_RECOVERED"}', 'ADJUSTMENTS = {"STANDBY_RECOVERED", "FALLBACK_MATCH"}'),
    ("Scale photo hash dropped from invoice lines", "src/ticket_audit/pipeline.py",
     '"scale_sha256": d.scale.doc.sha256', '"scale_sha256": ""'),
    ("Extraction cache bypassed", "src/ticket_audit/pipeline.py",
     "e = store.cached(digest, path.name, extractor.name, extractor.model_version)", "e = None"),
]
FITNESS = {
    "test_every_approved_line_has_verifiable_provenance": "Auditability: every approved line's provenance verifies",
    "test_every_load_gets_exactly_the_outcome_it_should": "Data integrity: every load gets exactly its required outcome",
    "test_killed_run_resumes_with_identical_output": "Reliability: a run killed halfway resumes with identical output",
}


def pytest(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", *args], cwd=ROOT, capture_output=True, text=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--commit", default=None)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build-info.json")
    args = ap.parse_args()
    commit = args.commit or subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                                           capture_output=True, text=True).stdout.strip()

    junit = ROOT / ".pytest-junit.xml"
    run = pytest(f"--junitxml={junit}", "-p", "no:cacheprovider")
    cases = ET.parse(junit).getroot().iter("testcase")
    results = []
    for c in cases:
        failed = c.find("failure") is not None or c.find("error") is not None
        results.append({"name": c.get("name"), "file": c.get("classname"), "passed": not failed})
    junit.unlink()
    fitness = []
    for test, label in FITNESS.items():
        runs = [r for r in results if r["name"].startswith(test)]
        fitness.append({"label": label, "runs": len(runs), "passed": bool(runs) and all(r["passed"] for r in runs)})

    mutants = []
    for label, path, old, new in MUTANTS:
        p = ROOT / path
        src = p.read_text()
        if old not in src:
            mutants.append({"label": label, "caught": False, "by": "mutation no longer applies"})
            continue
        p.write_text(src.replace(old, new))
        try:
            r = pytest("-x", "tests/test_fitness.py", "-p", "no:cacheprovider")
            failed = [ln.split(" ")[1].split("::")[1] for ln in r.stdout.splitlines() if ln.startswith("FAILED")]
            mutants.append({"label": label, "caught": r.returncode != 0, "by": failed[0] if failed else ""})
        finally:
            p.write_text(src)

    info = {
        "commit": commit,
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tests": {"total": len(results), "passed": sum(r["passed"] for r in results)},
        "fitness": fitness,
        "mutants": mutants,
        "suite_passed": run.returncode == 0,
    }
    args.out.write_text(json.dumps(info, indent=1))
    print(f"{info['tests']['passed']}/{info['tests']['total']} tests; fitness "
          f"{sum(f['passed'] for f in fitness)}/{len(fitness)}; mutants caught {sum(m['caught'] for m in mutants)}/{len(mutants)}")
    if not info["suite_passed"] or not all(m["caught"] for m in mutants):
        sys.exit(1)  # never ship an image whose tests fail or can't catch a known break


if __name__ == "__main__":
    main()
