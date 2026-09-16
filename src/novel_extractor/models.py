"""Core data models shared by every module.

All detection modules return DetectionResult so that confidence and reason
travel with the value. Nothing here is allowed to depend on a specific site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass
class DetectionResult(Generic[T]):
    """Outcome of a heuristic detection step.

    confidence is a float in [0, 1]. reason is a short human readable
    explanation; diagnostics carries optional machine readable details.
    """

    value: T
    confidence: float
    reason: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))

    @property
    def ok(self) -> bool:
        return self.value is not None and self.confidence >= 0.60


@dataclass
class FetchedPage:
    """A fetched HTTP response, kept as raw bytes plus a decoded html str."""

    url: str
    final_url: str
    status_code: int
    raw_bytes: bytes
    html: str
    encoding: str
    encoding_source: str
    encoding_confidence: float
    headers: dict[str, str] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)


class PageType(str, Enum):
    BOOK_PAGE = "BOOK_PAGE"
    CATALOG_PAGE = "CATALOG_PAGE"
    CHAPTER_PAGE = "CHAPTER_PAGE"
    UNKNOWN = "UNKNOWN"


class ContentStatus(str, Enum):
    """Status of the main content of a chapter page.

    Restricted pages must never be silently exported as normal chapters.
    """

    CONTENT_OK = "CONTENT_OK"
    EMPTY_CONTENT = "EMPTY_CONTENT"
    ACCESS_RESTRICTED = "ACCESS_RESTRICTED"
    PAYWALL = "PAYWALL"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    ANTI_BOT = "ANTI_BOT"
    NOT_FOUND = "NOT_FOUND"
    UNKNOWN_FAILURE = "UNKNOWN_FAILURE"


class RelationType(str, Enum):
    """Strictly separated relation kinds.

    Content pagination (a chapter split over several pages), catalog
    pagination (a catalog split over several pages) and chapter hops are
    three different things and must never be merged into one NEXT/PREVIOUS.
    """

    PREVIOUS_CONTENT_PAGE = "PREVIOUS_CONTENT_PAGE"
    NEXT_CONTENT_PAGE = "NEXT_CONTENT_PAGE"
    PREVIOUS_CATALOG_PAGE = "PREVIOUS_CATALOG_PAGE"
    NEXT_CATALOG_PAGE = "NEXT_CATALOG_PAGE"
    PREVIOUS_CHAPTER = "PREVIOUS_CHAPTER"
    NEXT_CHAPTER = "NEXT_CHAPTER"
    CATALOG_LINK = "CATALOG_LINK"


@dataclass
class ChapterTitleMatch:
    """A parsed chapter title."""

    title: str
    chapter_number: Optional[float]
    chapter_type: str  # normal | prologue | interlude | extra | epilogue | afterword | volume
    order_token: Optional[float]  # normalized sortable token, None when unnumbered
    confidence: float
    reason: str
    # Trailing bare-number part index ("第6章 2" -> 2); per-part chapters of
    # one logical chapter carry the same main number with increasing parts.
    sub_number: Optional[int] = None


@dataclass
class ExtractionCandidate:
    """One extraction candidate with explainable scoring (guide task 21)."""

    candidate_id: str                 # dom_density | trafilatura
    score: float
    confidence: float
    positive_reasons: list[str] = field(default_factory=list)
    penalties: list[str] = field(default_factory=list)
    key_features: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContentExtraction:
    """Candidate main content of a page."""

    text: str
    node_tag: str
    confidence: float
    reason: str
    diagnostics: dict[str, Any] = field(default_factory=dict)
    # The winning DOM node (bs4/lxml object), kept for downstream analyzers
    # (pagination, content status). Never serialized.
    node: Optional[Any] = None
    # Explainable candidate records (guide task 21): every candidate that
    # competed, with its own score/reasons/features.
    candidates: list[ExtractionCandidate] = field(default_factory=list)


@dataclass
class BookMetadata:
    """Book level metadata. The exporter must never guess these itself."""

    book_title: Optional[str] = None
    author: Optional[str] = None
    description: Optional[str] = None
    cover_url: Optional[str] = None
    volume_title: Optional[str] = None
    title_confidence: float = 0.0
    title_reason: str = ""
    author_confidence: float = 0.0
    author_reason: str = ""


@dataclass
class CatalogEntry:
    """One chapter entry as found in a catalog, in original DOM order."""

    title: str
    url: str
    source_page_url: str
    dom_index: int


class CatalogDirection(str, Enum):
    ASCENDING = "ASCENDING"
    DESCENDING = "DESCENDING"
    UNKNOWN = "UNKNOWN"


@dataclass
class CatalogResult:
    """Detected catalog: entries in DOM order plus an interpreted direction.

    The DOM order alone is NOT the reading order until the direction has
    been resolved by CatalogOrderDetector.
    """

    chapters: list[CatalogEntry] = field(default_factory=list)
    direction: CatalogDirection = CatalogDirection.UNKNOWN
    source_pages: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""


@dataclass
class PageRelation:
    source_url: str
    target_url: str
    relation_type: RelationType
    confidence: float
    reason: str


@dataclass
class LogicalChapter:
    """A full chapter, with all of its content pages already merged."""

    index: int
    title: str
    source_pages: list[str] = field(default_factory=list)
    content: str = ""
    content_status: ContentStatus = ContentStatus.CONTENT_OK
    confidence: float = 0.0
