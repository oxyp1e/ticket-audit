from pathlib import Path
from typing import Protocol

from ticket_audit.domain.model import Extraction


class Extractor(Protocol):
    name: str
    model_version: str

    def extract(self, path: Path, sha256: str) -> Extraction:
        """Read one document. Blank fields are left out, as a real OCR engine would."""
        ...
