"""Read-only diagnostics used by the offline benchmark evaluator.

Nothing in this module changes parser weights or feeds expected labels back
into inference.  Class/id/path information is displayed only as diagnostics.
"""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from novel_extractor.analyzer.catalog import CatalogDetector
from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.analyzer.navigation import ChapterNavigationDetector
from novel_extractor.analyzer.pagination import (
    CatalogPaginationDetector,
    ContentPaginationDetector,
    _NEXT_CATALOG_WORDS,
    has_page_marker,
    page_title,
)
from novel_extractor.fetcher.http import FetchError, Fetcher
from novel_extractor.models import FetchedPage


FAILURE_TAXONOMY = (
    "FETCH_ERROR",
    "ENCODING_ERROR",
    "PAGE_TYPE_FALSE_POSITIVE",
    "PAGE_TYPE_FALSE_NEGATIVE",
    "PAGE_TYPE_WRONG_CLASS",
    "CONTENT_FALSE_POSITIVE",
    "CONTENT_TRUNCATED",
    "CONTENT_NOISE_INCLUDED",
    "CONTENT_STATUS_WRONG",
    "CATALOG_NOT_FOUND",
    "CATALOG_WRONG_GROUP",
    "CATALOG_WRONG_DIRECTION",
    "CATALOG_PAGINATION_MISSED",
    "CONTENT_PAGINATION_MISSED",
    "CONTENT_PAGINATION_OVERMERGED",
    "NAVIGATION_WRONG_RELATION",
    "METADATA_WRONG_TITLE",
    "METADATA_WRONG_AUTHOR",
    "ACCESS_PAGE_MISCLASSIFIED",
    "CHAPTER_MISSING",
    "READING_ORDER_WRONG",
    "EXPORT_INCOMPLETE_NOT_REPORTED",
)


def sample_type_for(case_data: dict[str, Any]) -> str:
    """Return an exclusive reporting bucket while retaining provenance elsewhere."""

    tags = set(case_data.get("scenario_tags") or [])
    suite = case_data.get("suite")
    input_kinds = {page.get("input_kind") for page in case_data.get("pages") or []}
    if suite == "CN_DYNAMIC_INPUT" or "BROWSER_DOM" in input_kinds:
        return "dynamic"
    if suite == "CN_ACCESS_STATE" or tags & {
        "anti_bot", "challenge", "http_403", "http_200_challenge",
        "restricted", "paywall", "login_required",
    }:
        return "challenge"
    if case_data.get("source_type") == "real_capture":
        return "real_fixture"
    return "synthetic"


def page_type_failure_category(expected: str, actual: str) -> str:
    if expected == "UNKNOWN" and actual != "UNKNOWN":
        return "PAGE_TYPE_FALSE_POSITIVE"
    if expected != "UNKNOWN" and actual == "UNKNOWN":
        return "PAGE_TYPE_FALSE_NEGATIVE"
    return "PAGE_TYPE_WRONG_CLASS"


def _tag_path(tag: Tag | None) -> str | None:
    if tag is None:
        return None
    parts: list[str] = []
    current: Tag | None = tag
    while isinstance(current, Tag) and current.name != "[document]":
        part = current.name
        if current.get("id"):
            part += f"#{current.get('id')}"
        classes = current.get("class") or []
        if classes:
            part += "." + ".".join(str(item) for item in classes[:3])
        parts.append(part)
        current = current.parent if isinstance(current.parent, Tag) else None
    return " > ".join(reversed(parts))


def _common_ancestor(tags: list[Tag]) -> Tag | None:
    if not tags:
        return None
    first_chain: list[Tag] = []
    current: Tag | None = tags[0]
    while isinstance(current, Tag):
        first_chain.append(current)
        current = current.parent if isinstance(current.parent, Tag) else None
    ancestor_sets = []
    for tag in tags[1:]:
        chain: set[int] = set()
        current = tag
        while isinstance(current, Tag):
            chain.add(id(current))
            current = current.parent if isinstance(current.parent, Tag) else None
        ancestor_sets.append(chain)
    for candidate in first_chain:
        if all(id(candidate) in chain for chain in ancestor_sets):
            return candidate
    return tags[0]


def diagnose_catalog_groups(html: str, base_url: str, result) -> dict[str, Any]:
    """Expose the same chapter-anchor clusters and score used by CatalogDetector."""

    detector = CatalogDetector()
    soup = BeautifulSoup(html, "lxml")
    items = detector._collect_chapter_anchors(soup)  # benchmark introspection only
    clusters = detector._cluster_by_parent(items) if items else []
    clusters = sorted(
        clusters,
        key=lambda cluster: (detector._cluster_score(cluster), len(cluster)),
        reverse=True,
    )
    selected_urls = {item.url for item in result.chapters}
    candidates: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters, start=1):
        parents = [item[3] for item in cluster if isinstance(item[3], Tag)]
        root = _common_ancestor(parents)
        anchors = []
        if root is not None:
            anchors = [
                anchor for anchor in root.find_all("a")
                if anchor.get("href") and not str(anchor.get("href")).startswith(("javascript:", "#", "mailto:"))
            ]
        if not anchors:
            anchors = [parent.find("a") for parent in parents if parent.find("a")]
        texts = [anchor.get_text(strip=True) for anchor in anchors]
        chapter_matches = []
        for anchor in anchors:
            text = anchor.get_text(strip=True)
            match = detector._chapter.parse(text)
            if match is not None and match.confidence >= 0.85:
                chapter_matches.append(anchor)
        link_count = len(anchors)
        match_count = len(chapter_matches)
        match_ratio = match_count / link_count if link_count else 0.0
        average_length = sum(len(text) for text in texts) / link_count if link_count else 0.0
        all_text_length = sum(len(text) for text in texts)
        matched_text_length = sum(len(anchor.get_text(strip=True)) for anchor in chapter_matches)
        link_text_ratio = matched_text_length / all_text_length if all_text_length else 0.0
        dirnames = [detector._dirname(str(anchor.get("href"))) for anchor in anchors]
        dominant_count = Counter(dirnames).most_common(1)[0][1] if dirnames else 0
        url_similarity = dominant_count / link_count if link_count else 0.0
        core_score = detector._cluster_score(cluster)
        strong_ratio = sum(
            1
            for _dom, title, _href, _parent in cluster
            if (match := detector._chapter.parse(title)) and match.confidence >= 0.85
        ) / len(cluster) if cluster else 0.0
        final_score = min(0.95, core_score + 0.15 * strong_ratio)
        positives: list[str] = []
        penalties: list[str] = []
        if len(cluster) >= 5:
            positives.append(f"chapter-like cluster size={len(cluster)}")
        else:
            penalties.append("chapter-like cluster below parser minimum 5")
        if match_ratio >= 0.8:
            positives.append(f"chapter title match ratio={match_ratio:.2f}")
        else:
            penalties.append(f"chapter title match ratio={match_ratio:.2f}")
        if url_similarity >= 0.8:
            positives.append(f"dominant URL directory ratio={url_similarity:.2f}")
        else:
            penalties.append(f"low URL directory similarity={url_similarity:.2f}")
        urls = [urljoin(base_url, str(anchor.get("href"))) for anchor in chapter_matches]
        candidates.append(
            {
                "candidate_id": f"catalog_group_{index}",
                "parent_dom_path": _tag_path(root),
                "link_count": link_count,
                "chapter_title_match_count": match_count,
                "chapter_title_match_ratio": round(match_ratio, 6),
                "average_anchor_text_length": round(average_length, 6),
                "link_text_ratio": round(link_text_ratio, 6),
                "dom_depth": len(list(root.parents)) if root is not None else None,
                "url_similarity": round(url_similarity, 6),
                "final_score": round(final_score, 6),
                "positive_reasons": positives,
                "penalties": penalties,
                "target_urls": urls,
                "parser_selected": bool(selected_urls and selected_urls.intersection(urls)),
            }
        )
    selected = next((item["candidate_id"] for item in candidates if item["parser_selected"]), None)
    return {
        "parser_selected_group": selected,
        "top_scored_group": candidates[0]["candidate_id"] if candidates else None,
        "parser_result_reason": result.reason,
        "candidates": candidates,
    }


def annotate_expected_catalog_group(
    diagnostics: dict[str, Any], expected_entries: list[dict[str, Any]]
) -> dict[str, Any]:
    expected_urls = {item.get("target_url") for item in expected_entries if item.get("target_url")}
    candidates = diagnostics.get("candidates") or []
    overlaps = [
        (len(expected_urls.intersection(candidate.get("target_urls") or [])), candidate)
        for candidate in candidates
    ]
    overlaps.sort(key=lambda item: item[0], reverse=True)
    best_overlap, expected_candidate = overlaps[0] if overlaps else (0, None)
    expected_id = expected_candidate.get("candidate_id") if expected_candidate and best_overlap else None
    selected_id = diagnostics.get("parser_selected_group")
    if expected_id is None:
        why = "expected links were absent from every chapter-title candidate group"
    elif selected_id == expected_id:
        why = "expected group was selected; failure is in another catalog dimension"
    elif expected_candidate.get("chapter_title_match_count", 0) < 5:
        why = "expected group was below the parser minimum of 5 chapter-like anchors"
    elif selected_id is None:
        why = diagnostics.get("parser_result_reason") or "parser rejected all groups"
    else:
        selected = next((item for item in candidates if item["candidate_id"] == selected_id), None)
        why = (
            f"expected score {expected_candidate.get('final_score')} was below selected score "
            f"{selected.get('final_score') if selected else 'unknown'}"
        )
    return {
        **diagnostics,
        "expected_group": expected_id,
        "expected_group_overlap": best_overlap,
        "expected_group_not_selected_reason": why,
    }


def _chapter_number(detector: ChapterTitleDetector, html: str):
    parsed = detector.parse(page_title(html))
    return parsed.order_token if parsed else None


def diagnose_pagination_candidates(
    page: FetchedPage,
    predicted_page_type: str,
    fetcher: Fetcher,
) -> list[dict[str, Any]]:
    """List every next-page/next-chapter anchor and the core relation evidence."""

    soup = BeautifulSoup(page.html, "lxml")
    nav = ChapterNavigationDetector().detect(page.html, page.final_url)
    catalog_detector = CatalogPaginationDetector()
    content_detector = ContentPaginationDetector()
    chapter_detector = ChapterTitleDetector()
    start_number = _chapter_number(chapter_detector, page.html)
    candidates: list[dict[str, Any]] = []

    for anchor in soup.find_all("a"):
        href = anchor.get("href") or ""
        text = anchor.get_text(strip=True)
        lowered = text.lower()
        if not href or href.startswith(("javascript:", "#", "mailto:")):
            continue
        page_word = max((word for word in _NEXT_CATALOG_WORDS if word in lowered), key=len, default=None)
        chapter_word = max(
            (word for word in ("下一章", "下一节", "下一回", "下一话", "next chapter") if word in lowered),
            key=len,
            default=None,
        )
        if page_word is None and chapter_word is None:
            continue
        target = urljoin(page.final_url, href)
        relation = "UNKNOWN"
        confidence = 0.0
        positives: list[str] = []
        penalties: list[str] = []

        if page_word is not None and (chapter_word is None or len(page_word) >= len(chapter_word)):
            score, reasons = catalog_detector._score_target(page.final_url, href, page_word, "next")
            confidence = round(score, 3)
            for reason in reasons:
                if reason.startswith(("target URL leaves", "target equals", "non-adjacent")):
                    penalties.append(reason)
                else:
                    positives.append(reason)
            if predicted_page_type == "CATALOG_PAGE":
                relation = "NEXT_CATALOG_PAGE"
            elif predicted_page_type == "CHAPTER_PAGE":
                relation = "NEXT_CONTENT_PAGE"
            else:
                penalties.append("page type is UNKNOWN, so pagination kind cannot be assigned")
        else:
            confidence = nav.confidence if nav.value.get("next_chapter") == target else 0.0
            positives.append(f"anchor text contains '{chapter_word}'")
            relation = "NEXT_CHAPTER"
            try:
                target_page = fetcher.fetch(target)
                target_number = _chapter_number(chapter_detector, target_page.html)
                if has_page_marker(page_title(target_page.html)) and (
                    start_number is None or target_number is None or int(start_number) == int(target_number)
                ):
                    relation = "NEXT_CONTENT_PAGE"
                    positives.append("target has an explicit page marker for the same logical chapter")
                else:
                    penalties.append("target lacks same-chapter page-marker evidence")
            except FetchError as exc:
                penalties.append(f"target fixture unavailable: {exc.cause}")
        candidates.append(
            {
                "anchor_text": text,
                "target_url": target,
                "predicted_relation": relation,
                "relation_confidence": round(confidence, 3),
                "positive_reasons": positives,
                "penalties": penalties,
            }
        )
    return candidates
