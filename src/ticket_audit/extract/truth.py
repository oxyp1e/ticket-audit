"""Generator truth: returns what the generator wrote on each ticket, with the confidence an OCR
engine would plausibly report. Lets the rules be tested end to end with no OCR and no cost."""
import json
from pathlib import Path

from ticket_audit.domain.model import Extraction, Field

CLEAR = 0.99
ILLEGIBLE = 0.45


class TruthExtractor:
    name = "truth"
    model_version = "generator-truth-1"

    def __init__(self, documents_json: Path):
        docs = json.loads(documents_json.read_text())["documents"]
        self._by_file = {d["file"]: d for d in docs}

    def extract(self, path: Path, sha256: str) -> Extraction:
        doc = self._by_file.get(path.name)
        if doc is None:
            return Extraction(path.name, sha256, "unknown", {}, self.name, self.model_version)
        fields = {
            k: Field(v, ILLEGIBLE if k in doc["illegible"] else CLEAR)
            for k, v in doc["fields"].items() if v != ""
        }
        return Extraction(path.name, sha256, doc["kind"], fields, self.name, self.model_version)
