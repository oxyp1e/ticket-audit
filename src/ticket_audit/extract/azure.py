"""Azure AI Document Intelligence (prebuilt-layout + key-value pairs).

Values are paired with labels by position on the page (haul ticket: the handwriting below the box
label; scale receipt: the value to the right of the label). Azure's own key-value pairing is a
second opinion: where the two readings disagree, the field's confidence drops so a human looks.
Field confidence is the weakest OCR word in the value.

Raw responses are kept next to the run for audit and replay, and are reused before any new call:
changing the mapping never costs free-tier pages.
"""
import json
import os
import re
import time
from difflib import SequenceMatcher
from pathlib import Path
from statistics import median

import requests

from ticket_audit.domain.model import Extraction, Field
from ticket_audit.domain.normalize import key

# Label stems as printed on the forms -> canonical fields. Matched on the normalized label,
# by prefix, so OCR slips in the label ("NET WEIGHT (1)") still land on the right field.
HAUL_LABELS = [
    ("dispatch", "dispatch_no"), ("unitno", "unit"), ("trailer", "trailer"), ("driver", "driver"),
    ("customer", "customer"), ("pono", "po"), ("afe", "afe"), ("origin", "origin"),
    ("scaleticket", "scale_ticket_no"), ("destination", "lease"), ("lsd", "lsd"), ("product", "product"),
    ("netweight", "net_t"), ("arrive", "arrive"), ("depart", "depart"), ("standby", "standby_h"),
    ("receiverprint", "receiver_name"), ("receiversig", "receiver_signature"), ("date", "date"),
]
SCALE_LABELS = [
    ("ticket", "scale_ticket_no"), ("date", "date"), ("timein", "time_in"), ("timeout", "time_out"),
    ("carrier", "carrier"), ("unit", "unit"), ("trailer", "trailer"), ("product", "product"),
    ("gross", "gross_kg"), ("tare", "tare_kg"), ("weighmaster", "weighmaster"),
    ("driversig", "driver_signature"),
]
TICKET_NO = re.compile(r"\b[A-Z]{2}-\d{6}\b")
MAPPER_VERSION = "4"
POLL_INTERVAL_S = 2.5
MAX_BACKOFF_S = 15.0
DISAGREEMENT_CONFIDENCE = 0.5

# Labels as printed on the forms. Matched on the normalized line text, by prefix.
HAUL_FORM = [
    ("DATE", "date"), ("DISPATCH / LOAD No.", "dispatch_no"), ("UNIT No.", "unit"), ("TRAILER No.", "trailer"),
    ("DRIVER", "driver"), ("CUSTOMER (BILL TO)", "customer"), ("PO No.", "po"), ("AFE / COST CODE", "afe"),
    ("ORIGIN (PIT / TERMINAL)", "origin"), ("SCALE TICKET No.", "scale_ticket_no"),
    ("DESTINATION LEASE / WELL", "lease"), ("LSD", "lsd"), ("PRODUCT", "product"), ("NET WEIGHT (t)", "net_t"),
    ("ARRIVE SITE", "arrive"), ("DEPART SITE", "depart"), ("STANDBY (h)", "standby_h"),
    ("RECEIVER - PRINT NAME", "receiver_name"), ("RECEIVER - SIGNATURE", "receiver_signature"),
    ("REMARKS", ""), ("RECEIVED IN GOOD ORDER", ""), ("WHITE - OFFICE YELLOW - CUSTOMER PINK - DRIVER", ""),
    ("FRAC SAND HAUL TICKET", ""), ("SYNTHETIC DOCUMENT - FOR TESTING ONLY", ""),
]
LABEL_SIMILARITY = 0.8  # tolerates OCR slips in printed labels, e.g. "NET WEIGHT (1)"
SCALE_FORM = [
    ("TICKET #", "scale_ticket_no"), ("DATE", "date"), ("TIME IN", "time_in"), ("TIME OUT", "time_out"),
    ("CARRIER", "carrier"), ("UNIT", "unit"), ("TRAILER", "trailer"), ("PRODUCT", "product"),
    ("GROSS", "gross_kg"), ("TARE", "tare_kg"), ("NET", "net"), ("WEIGHMASTER", "weighmaster"),
    ("DRIVER SIGNATURE", "driver_signature"),
]


def _box(polygon: list[float]) -> tuple[float, float, float, float]:
    xs, ys = polygon[0::2], polygon[1::2]
    return min(xs), min(ys), max(xs), max(ys)


def _slope(polygon: list[float]) -> float:
    """Tilt of a text line from its top edge (polygon order: top-left, top-right, ...)."""
    dx = polygon[2] - polygon[0]
    return (polygon[3] - polygon[1]) / dx if dx else 0.0


class PageBudgetExceeded(RuntimeError):
    pass


def load_env(path: Path) -> dict[str, str]:
    env = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return {**env, **{k: v for k, v in os.environ.items() if k.startswith("AZURE_DI_")}}


class AzureExtractor:
    name = "azure"

    def __init__(self, endpoint: str, api_key: str, api_version: str = "2024-11-30",
                 model: str = "prebuilt-layout", raw_dir: Path | None = None, max_pages: int = 300):
        self.endpoint = endpoint.rstrip("/") + "/"
        self.api_key = api_key
        self.api_version = api_version
        self.model = model
        self.model_version = f"{model}@{api_version}/map{MAPPER_VERSION}"
        self.raw_dir = raw_dir
        self.pages_left = max_pages
        self.session = requests.Session()
        self.session.headers["Ocp-Apim-Subscription-Key"] = api_key

    @classmethod
    def from_env(cls, env_file: Path, raw_dir: Path | None = None, max_pages: int = 300) -> "AzureExtractor":
        env = load_env(env_file)
        missing = [k for k in ("AZURE_DI_ENDPOINT", "AZURE_DI_KEY") if not env.get(k)]
        if missing:
            raise SystemExit(f"missing {', '.join(missing)} in {env_file} (see .env.example)")
        return cls(env["AZURE_DI_ENDPOINT"], env["AZURE_DI_KEY"], env.get("AZURE_DI_API_VERSION", "2024-11-30"),
                   env.get("AZURE_DI_MODEL", "prebuilt-layout"), raw_dir, max_pages)

    # ── HTTP ─────────────────────────────────────────────────────────────────
    def _request(self, method: str, url: str, **kw) -> requests.Response:
        """Retry throttling and transient errors with backoff; anything else fails the run (fail closed)."""
        for attempt in range(8):
            r = self.session.request(method, url, timeout=60, **kw)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(min(float(r.headers.get("Retry-After", 2 ** attempt)), MAX_BACKOFF_S))
                continue
            r.raise_for_status()
            return r
        r.raise_for_status()
        raise RuntimeError(f"{method} {url}: still throttled after retries")

    def analyze(self, data: bytes, content_type: str) -> dict:
        if self.pages_left <= 0:
            raise PageBudgetExceeded("page budget for this run is used up; cached results are kept")
        url = (f"{self.endpoint}documentintelligence/documentModels/{self.model}:analyze"
               f"?api-version={self.api_version}&features=keyValuePairs")
        op = self._request("POST", url, data=data, headers={"Content-Type": content_type}).headers["Operation-Location"]
        self.pages_left -= 1
        while True:
            body = self._request("GET", op).json()
            if body["status"] == "succeeded":
                return body["analyzeResult"]
            if body["status"] == "failed":
                raise RuntimeError(f"analysis failed: {body.get('error')}")
            time.sleep(POLL_INTERVAL_S)  # every poll is a transaction against the free tier's rate limit

    # ── Mapping ──────────────────────────────────────────────────────────────
    @staticmethod
    def _value_confidence(result: dict, value: dict) -> float:
        spans = value.get("spans", [])
        words = [w for p in result.get("pages", []) for w in p.get("words", [])
                 if any(s["offset"] <= w["span"]["offset"] < s["offset"] + s["length"] for s in spans)]
        return min((w["confidence"] for w in words), default=1.0)

    @staticmethod
    def classify(content: str) -> str:
        text = content.upper()
        if "HAUL TICKET" in text:
            return "haul"
        if "GROSS" in text and "TARE" in text:
            return "scale"
        return "unknown"

    @staticmethod
    def _lines(result: dict) -> list[dict]:
        page = result["pages"][0]
        words = page.get("words", [])
        out = []
        for ln in page.get("lines", []):
            spans = ln.get("spans", [])
            confs = [w["confidence"] for w in words
                     if any(s["offset"] <= w["span"]["offset"] < s["offset"] + s["length"] for s in spans)]
            out.append({"text": ln["content"], "box": _box(ln["polygon"]), "conf": min(confs, default=0.0),
                        "slope": _slope(ln["polygon"])})
        return out

    @staticmethod
    def _label_of(text: str, kind: str) -> tuple[str, str] | None:
        k = key(text)
        if kind == "haul":
            # A label must match the whole printed label: "AFE 26-0742" is a value, not "AFE / COST CODE".
            best = max(HAUL_FORM, key=lambda lf: SequenceMatcher(None, k, key(lf[0])).ratio())
            return best if SequenceMatcher(None, k, key(best[0])).ratio() >= LABEL_SIMILARITY else None
        # Receipt lines may carry their value inline ("WEIGHMASTER A. Petrov"): match by prefix, longest first.
        for label, name in sorted(SCALE_FORM, key=lambda lf: -len(key(lf[0]))):
            if k.startswith(key(label)):
                return label, name
        return None

    def _geometric(self, result: dict, kind: str) -> tuple[dict[str, Field], set[str]]:
        """Fields read by position, plus the labels seen (a label with an empty box is a blank field)."""
        lines = self._lines(result)
        if not lines:
            return {}, set()
        tilt = median(ln["slope"] for ln in lines)  # the photo's tilt, from all text lines
        labels = [self._label_of(ln["text"], kind) for ln in lines]
        values = [ln for ln, lab in zip(lines, labels) if lab is None]

        def cy(o):
            return (o["box"][1] + o["box"][3]) / 2

        fields: dict[str, Field] = {}
        seen: set[str] = set()
        for ln, lab in zip(lines, labels):
            if not lab or not lab[1]:
                continue
            label, name = lab
            seen.add("net_kg" if name == "net" else name)
            x0, y0, x1, y1 = ln["box"]
            h = y1 - y0
            value = None
            if kind == "scale":
                inline = re.sub(r"^\W*" + r"\W*".join(map(re.escape, label.split())) + r"\W*", "",
                                ln["text"], flags=re.I).strip()
                if inline:
                    value = {"text": inline, "conf": ln["conf"]}
                else:  # same tilted row, to the right
                    def off(o):
                        return abs(cy(o) - (cy(ln) + tilt * (o["box"][0] - x0)))
                    row = [o for o in values if o["box"][0] > x1 - h and off(o) < 0.6 * h]
                    value = min(row, key=off, default=None)
            else:  # the handwriting just below the box label
                def drop(o):
                    return o["box"][1] - (y1 + tilt * (o["box"][0] - x0))
                below = [o for o in values if -0.3 * h < drop(o) < 2.5 * h and -1.5 * h < o["box"][0] - x0 < 6 * h]
                value = min(below, key=drop, default=None)
            if value is None:
                continue
            if name == "net":  # the receipt prints net twice; the kg line is authoritative
                if "kg" not in value["text"].lower():
                    continue
                name = "net_kg"
            if name not in fields:
                fields[name] = Field(value["text"].strip(), value["conf"])
        return fields, seen

    def _pairs(self, result: dict, kind: str) -> dict[str, Field]:
        """Azure's own key-value pairing, used as the second opinion."""
        labels = HAUL_LABELS if kind == "haul" else SCALE_LABELS
        fields: dict[str, Field] = {}
        for kv in result.get("keyValuePairs", []):
            value = kv.get("value") or {}
            text = (value.get("content") or "").strip().splitlines()
            label = key(kv["key"]["content"])
            if not text:
                continue
            conf = min(kv.get("confidence", 0.0), self._value_confidence(result, value))
            if kind == "scale" and label == "net":
                if "kg" in text[0].lower():
                    fields["net_kg"] = Field(text[0], conf)
                continue
            name = next((f for stem, f in labels if label.startswith(stem)), None)
            if name and name not in fields:
                fields[name] = Field(text[0], conf)
        return fields

    def map_fields(self, result: dict, kind: str) -> dict[str, Field]:
        (geo, seen), pairs = self._geometric(result, kind), self._pairs(result, kind)
        fields = dict(geo)
        for name, f in pairs.items():
            if name not in fields and name in seen:
                # The box looked empty by position but Azure paired a value with it: don't trust either.
                fields[name] = Field(f.value, min(f.confidence, DISAGREEMENT_CONFIDENCE))
            elif name not in fields:
                fields[name] = f
            elif key(f.value) != key(fields[name].value):
                fields[name] = Field(fields[name].value, min(fields[name].confidence, DISAGREEMENT_CONFIDENCE))
        if kind == "haul":
            # The pre-printed ticket number sits beside "No." in the header, not in a labelled box.
            m = TICKET_NO.search(result.get("content", ""))
            if m:
                words = [w for p in result.get("pages", []) for w in p.get("words", [])
                         if m.start() <= w["span"]["offset"] < m.end()]
                fields["ticket_no"] = Field(m.group(), min((w["confidence"] for w in words), default=0.0))
        return fields

    def extract(self, path: Path, sha256: str) -> Extraction:
        content_type = {".pdf": "application/pdf", ".png": "image/png", ".tif": "image/tiff",
                        ".tiff": "image/tiff"}.get(path.suffix.lower(), "image/jpeg")
        raw = self.raw_dir / f"{sha256}.json" if self.raw_dir else None
        if raw and raw.exists():  # already read once: re-map, don't pay again
            result = json.loads(raw.read_text())
        else:
            result = self.analyze(path.read_bytes(), content_type)
            if raw:
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(json.dumps(result))
        kind = self.classify(result.get("content", ""))
        fields = self.map_fields(result, kind) if kind != "unknown" else {}
        return Extraction(path.name, sha256, kind, fields, self.name, self.model_version)
