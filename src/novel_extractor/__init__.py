"""Ruleless Novel Structure Inference Engine.

No source rules. No API keys. No cloud AI.
Paste a novel URL and extract.
"""

from novel_extractor.models import (
    BookMetadata,
    CatalogDirection,
    CatalogEntry,
    CatalogResult,
    ChapterTitleMatch,
    ContentExtraction,
    ContentStatus,
    DetectionResult,
    FetchedPage,
    LogicalChapter,
    PageRelation,
    PageType,
    RelationType,
)

__version__ = "0.1.0"

__all__ = [
    "BookMetadata",
    "CatalogDirection",
    "CatalogEntry",
    "CatalogResult",
    "ChapterTitleMatch",
    "ContentExtraction",
    "ContentStatus",
    "DetectionResult",
    "FetchedPage",
    "LogicalChapter",
    "PageRelation",
    "PageType",
    "RelationType",
    "__version__",
]
