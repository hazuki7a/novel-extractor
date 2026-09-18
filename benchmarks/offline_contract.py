"""Offline benchmark case loading and fixture replay.

This module is deliberately blind to ``expected.json``.  It validates only
the acquisition contract in ``case.json`` and turns saved inputs into the
project's normal :class:`FetchedPage` model.  No network client is imported or
used here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from novel_extractor.fetcher.http import FetchError, decode_page_bytes
from novel_extractor.models import FetchedPage


INPUT_KINDS = {"HTTP_BYTES", "BROWSER_DOM", "SYNTHETIC_HTML"}
SUITES = {
    "CN_STATIC_CONTENT",
    "CN_ACCESS_STATE",
    "CN_DYNAMIC_INPUT",
    "ENCODING",
    "CROSS_LANGUAGE",
    "NON_HTML_NEGATIVE",
    "SYNTHETIC_REGRESSION",
}
_CHARSET_RE = re.compile(r"charset\s*=\s*['\"]?([^\s;'\"]+)", re.I)


class CaseValidationError(ValueError):
    """A READY case is incomplete or internally inconsistent."""


class FixtureOutOfScopeError(FetchError):
    """The parser requested a URL that was not captured for this case."""


@dataclass(frozen=True)
class OfflineCase:
    case_dir: Path
    data: dict[str, Any]
    input_root: Path
    pages_by_url: dict[str, dict[str, Any]]
    pages_by_id: dict[str, dict[str, Any]]

    @property
    def case_id(self) -> str:
        return str(self.data["case_id"])

    @property
    def expected_path(self) -> Path:
        return self.case_dir / self.data["expected_path"]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CaseValidationError(f"{path}: JSON root must be an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_case(case_path: Path) -> OfflineCase:
    """Load and fully validate one READY input contract.

    The expected file is checked for existence but is never opened here,
    keeping gold labels outside the inference boundary.
    """

    case_path = case_path.resolve()
    data = _read_json(case_path)
    errors: list[str] = []
    if data.get("document_type") != "benchmark_case":
        errors.append("document_type must be benchmark_case")
    if data.get("annotation_status") != "READY":
        errors.append("only READY cases are executable")
    case_id = data.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        errors.append("case_id must be a nonempty string")
    if data.get("source_type") not in {"synthetic", "real_capture"}:
        errors.append("source_type must be synthetic or real_capture")
    if data.get("suite") not in SUITES:
        errors.append(f"unknown suite {data.get('suite')!r}")

    case_dir = case_path.parent
    input_root_value = data.get("input_root")
    input_root = (case_dir / input_root_value).resolve() if input_root_value else case_dir
    pages = data.get("pages")
    if not isinstance(pages, list) or not pages:
        errors.append("pages must be a nonempty list")
        pages = []

    by_url: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    for page in pages:
        if not isinstance(page, dict):
            errors.append("every page must be an object")
            continue
        page_id = page.get("page_id")
        url = page.get("requested_url")
        kind = page.get("input_kind")
        if not isinstance(page_id, str) or not page_id:
            errors.append("page_id must be nonempty")
            continue
        if page_id in by_id:
            errors.append(f"duplicate page_id: {page_id}")
        by_id[page_id] = page
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            errors.append(f"{page_id}: invalid requested_url")
        elif url in by_url:
            errors.append(f"duplicate requested_url: {url}")
        else:
            by_url[url] = page
        if kind not in INPUT_KINDS:
            errors.append(f"{page_id}: unknown input_kind {kind!r}")
        relative_input = page.get("input_path")
        if not isinstance(relative_input, str) or not relative_input:
            errors.append(f"{page_id}: input_path is required")
            continue
        input_path = input_root / relative_input
        if not input_path.is_file():
            errors.append(f"{page_id}: missing input {input_path}")
            continue
        expected_hash = page.get("input_sha256")
        actual_hash = _sha256(input_path)
        if expected_hash != actual_hash:
            errors.append(f"{page_id}: SHA-256 mismatch")
        metadata_path = page.get("http_metadata_path")
        if kind == "HTTP_BYTES" and not metadata_path:
            errors.append(f"{page_id}: HTTP_BYTES requires http_metadata_path")
        if metadata_path and not (input_root / metadata_path).is_file():
            errors.append(f"{page_id}: missing HTTP metadata")

    entry_page_id = data.get("entry_page_id")
    if entry_page_id is not None and entry_page_id not in by_id:
        errors.append("entry_page_id does not reference a page")
    expected_rel = data.get("expected_path")
    expected_path = case_dir / expected_rel if isinstance(expected_rel, str) else None
    if expected_path is None or not expected_path.is_file():
        errors.append("expected_path is missing")

    rights = data.get("rights_and_privacy", {})
    if not isinstance(rights, dict) or not rights.get("publication_status"):
        errors.append("rights_and_privacy.publication_status is required")
    if errors:
        raise CaseValidationError(f"{case_path}: " + "; ".join(errors))
    return OfflineCase(case_dir, data, input_root, by_url, by_id)


def load_expected(case: OfflineCase) -> dict[str, Any]:
    """Load and validate gold labels for the evaluator or case checker only."""

    expected = _read_json(case.expected_path)
    errors: list[str] = []
    if expected.get("document_type") != "benchmark_expected":
        errors.append("document_type must be benchmark_expected")
    if expected.get("case_id") != case.case_id:
        errors.append("expected.json case_id does not match case.json")
    if expected.get("annotation_status") != "READY":
        errors.append("expected.json is not READY")
    labels = expected.get("page_labels")
    if not isinstance(labels, list):
        errors.append("expected.json page_labels must be a list")
        labels = []
    labelled_ids: set[str] = set()
    for label in labels:
        if not isinstance(label, dict):
            errors.append("every page label must be an object")
            continue
        labelled_id = label.get("page_id")
        if labelled_id not in case.pages_by_id:
            errors.append(f"expected label references unknown page: {labelled_id}")
        if labelled_id in labelled_ids:
            errors.append(f"duplicate expected page label: {labelled_id}")
        labelled_ids.add(labelled_id)
        reference = label.get("content_reference_path")
        if reference and not (case.case_dir / reference).is_file():
            errors.append(f"{labelled_id}: missing content reference")
    for chapter in expected.get("logical_chapters") or []:
        chapter_id = chapter.get("chapter_id", "<unknown>")
        for source_page_id in chapter.get("source_page_ids") or []:
            if source_page_id not in case.pages_by_id:
                errors.append(f"{chapter_id}: unknown source_page_id {source_page_id}")
        reference = chapter.get("reference_text_path")
        if reference and not (case.case_dir / reference).is_file():
            errors.append(f"{chapter_id}: missing logical chapter reference")
    if errors:
        raise CaseValidationError(f"{case.expected_path}: " + "; ".join(errors))
    return expected


class OfflineFixtureFetcher:
    """Replay exactly the URLs declared by one case, and nothing else."""

    def __init__(self, case: OfflineCase):
        self.case = case

    def fetch(self, url: str, *, referer: str | None = None) -> FetchedPage:
        del referer
        page = self.case.pages_by_url.get(url)
        if page is None:
            raise FixtureOutOfScopeError(url, "offline fixture missing / outside captured scope")
        raw = (self.case.input_root / page["input_path"]).read_bytes()
        kind = page["input_kind"]
        headers: dict[str, str] = {}
        status = page.get("http_status")
        final_url = page.get("final_url") or url
        diagnostics = {"offline_input_kind": kind, "page_id": page["page_id"]}

        if kind == "HTTP_BYTES":
            metadata = _read_json(self.case.input_root / page["http_metadata_path"])
            headers = {
                str(key).lower(): str(value)
                for key, value in (metadata.get("headers") or {}).items()
            }
            status = metadata.get("status", status)
            final_url = metadata.get("final_url") or final_url
            content_type = headers.get("content-type", "")
            match = _CHARSET_RE.search(content_type)
            http_charset = match.group(1) if match else None
            html, decision = decode_page_bytes(raw, http_charset)
            encoding = decision.encoding
            encoding_source = decision.source
            encoding_confidence = decision.confidence
            diagnostics.update(decision.diagnostics)
        else:
            html = raw.decode("utf-8")
            encoding = "utf-8"
            encoding_source = "browser_dom" if kind == "BROWSER_DOM" else "synthetic_utf8"
            encoding_confidence = 1.0

        return FetchedPage(
            url=url,
            final_url=str(final_url),
            status_code=int(status if status is not None else 200),
            raw_bytes=raw,
            html=html,
            encoding=encoding,
            encoding_source=encoding_source,
            encoding_confidence=encoding_confidence,
            headers=headers,
            diagnostics=diagnostics,
        )
