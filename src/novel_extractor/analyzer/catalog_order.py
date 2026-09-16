"""Catalog reading direction detection.

Decides whether a detected chapter list reads ASCENDING (第一章 first) or
DESCENDING (latest chapter first, common on serializing sites). The DOM order
of a catalog must never be treated as the reading order until this detector
has spoken; UNKNOWN means "do not force a direction".
"""

from __future__ import annotations

from typing import Optional, Sequence

from novel_extractor.analyzer.chapter import ChapterTitleDetector
from novel_extractor.models import (
    CatalogDirection,
    CatalogEntry,
    DetectionResult,
)

# An entry pair counts as monotone evidence only when numbers differ, which
# filters "最新章节" blocks repeating the same chapter as the full list.
_MIN_NUMBERED_ENTRIES = 3
_MIN_PAIR_RATIO = 0.85
_SPECIAL_ANCHOR_WEIGHT = 0.08

# Segmented-order repair: a list cut into two ascending runs where the second
# run's numbers sit entirely below the first run's (rotated catalog: a
# "latest/other-page" block in front of the early chapters). The drop at the
# seam must be substantial and both runs near-perfectly monotone.
_SEGMENT_DROP = 3
_SEGMENT_MONOTONE_RATIO = 0.95
_SEGMENT_MIN_RUN = 2


def reorder_segmented(
    entries: Sequence[CatalogEntry],
    chapter_detector: ChapterTitleDetector,
) -> Optional[list[CatalogEntry]]:
    """Repair a two-segment rotated catalog order, or return None.

    16..65 followed by 1..15 (each run strictly ascending, the second run's
    numbers entirely below the first's) reads as 第1章..第65章 after moving
    the second run to the front. Anything noisier stays untouched - the
    caller keeps its direction handling and gap warnings.
    """
    tokens: list[Optional[int]] = []
    for entry in entries:
        match = chapter_detector.parse(entry.title)
        tokens.append(int(match.order_token) if match and match.order_token is not None else None)

    for i in range(len(entries) - 1):
        if tokens[i] is None or tokens[i + 1] is None:
            continue
        if tokens[i + 1] > tokens[i] - _SEGMENT_DROP:
            continue  # not a substantial drop at the seam
        head = [t for t in tokens[: i + 1] if t is not None]
        tail = [t for t in tokens[i + 1 :] if t is not None]
        if len(head) < _SEGMENT_MIN_RUN or len(tail) < _SEGMENT_MIN_RUN:
            continue

        def monotone_ratio(seq: list[int]) -> float:
            pairs = max(1, len(seq) - 1)
            return sum(1 for p, c in zip(seq, seq[1:]) if c > p) / pairs

        if (
            monotone_ratio(head) >= _SEGMENT_MONOTONE_RATIO
            and monotone_ratio(tail) >= _SEGMENT_MONOTONE_RATIO
            and max(tail) <= min(head)
        ):
            return list(entries[i + 1 :]) + list(entries[: i + 1])
    return None


class CatalogOrderDetector:
    def __init__(self, chapter_detector: Optional[ChapterTitleDetector] = None):
        self._chapter = chapter_detector or ChapterTitleDetector()

    def detect(self, entries: Sequence[CatalogEntry]) -> DetectionResult[CatalogDirection]:
        numbered: list[float] = []
        types: list[str] = []
        for entry in entries:
            match = self._chapter.parse(entry.title)
            if match is None:
                continue
            types.append(match.chapter_type)
            if match.order_token is not None:
                numbered.append(match.order_token)

        diagnostics = {
            "total_entries": len(entries),
            "numbered_entries": len(numbered),
            "type_sequence": "".join(t[0] for t in types)[:80],
        }

        pairs_inc = pairs_dec = pairs_flat = 0
        for prev, curr in zip(numbered, numbered[1:]):
            if curr > prev:
                pairs_inc += 1
            elif curr < prev:
                pairs_dec += 1
            else:
                pairs_flat += 1
        total_pairs = pairs_inc + pairs_dec
        diagnostics["pairs_inc"], diagnostics["pairs_dec"] = pairs_inc, pairs_dec

        confidence = 0.0
        direction = CatalogDirection.UNKNOWN
        reason_parts: list[str] = []

        if total_pairs >= _MIN_NUMBERED_ENTRIES - 1 and numbered and len(numbered) >= _MIN_NUMBERED_ENTRIES:
            inc_ratio = pairs_inc / total_pairs
            dec_ratio = pairs_dec / total_pairs
            diagnostics["inc_ratio"] = round(inc_ratio, 3)
            diagnostics["dec_ratio"] = round(dec_ratio, 3)
            if inc_ratio >= _MIN_PAIR_RATIO:
                direction = CatalogDirection.ASCENDING
                confidence = min(0.95, 0.60 + 0.35 * inc_ratio)
                reason_parts.append(
                    f"chapter numbers ascend in DOM order ({pairs_inc}/{total_pairs} pairs)"
                )
            elif dec_ratio >= _MIN_PAIR_RATIO:
                direction = CatalogDirection.DESCENDING
                confidence = min(0.95, 0.60 + 0.35 * dec_ratio)
                reason_parts.append(
                    f"chapter numbers descend in DOM order ({pairs_dec}/{total_pairs} pairs)"
                )
            else:
                reason_parts.append(
                    f"mixed number sequence (inc={pairs_inc}, dec={pairs_dec})"
                )
        else:
            reason_parts.append("not enough numbered chapter titles to judge")

        # Special-title anchors: 序章/楔子 first or 终章/大结局 last means the
        # list reads ascending; the reverse means descending.
        anchor = self._special_anchor(types)
        if anchor:
            diagnostics["special_anchor"] = anchor
            anchor_direction, anchor_reason = anchor
            if direction is CatalogDirection.UNKNOWN:
                direction = anchor_direction
                confidence = 0.55
                reason_parts.append(f"special-title anchor: {anchor_reason}")
            elif direction is anchor_direction:
                confidence = min(0.97, confidence + _SPECIAL_ANCHOR_WEIGHT)
                reason_parts.append(f"special-title anchor agrees: {anchor_reason}")
            else:
                confidence = max(0.30, confidence - 0.15)
                reason_parts.append(f"special-title anchor conflicts: {anchor_reason}")

        if direction is CatalogDirection.UNKNOWN:
            confidence = min(confidence, 0.40)
            reason_parts.append("direction UNKNOWN; DOM order must not be trusted blindly")

        return DetectionResult(
            value=direction,
            confidence=round(confidence, 3),
            reason="; ".join(reason_parts),
            diagnostics=diagnostics,
        )

    @staticmethod
    def _special_anchor(types: Sequence[str]) -> Optional[tuple[CatalogDirection, str]]:
        if not types:
            return None
        head, tail = types[0], types[-1]
        if head == "p" and tail in ("e", "a", "n"):  # prologue ... epilogue/afterword
            return CatalogDirection.ASCENDING, "starts with prologue, ends with ending"
        if head in ("e", "a") and tail == "p":
            return CatalogDirection.DESCENDING, "starts with ending, ends with prologue"
        if head == "e" and len(types) > 1 and types[1] == "n":
            return CatalogDirection.DESCENDING, "epilogue directly before normal chapters"
        if tail == "e" and len(types) > 1 and types[-2] == "n":
            return CatalogDirection.ASCENDING, "epilogue after normal chapters"
        return None
