"""Tests for Human-assisted Correction (guide task 25)."""

from __future__ import annotations

from novel_extractor.correction import (
    ask_direction,
    choose,
    choose_catalog_link,
    confirm,
)
from novel_extractor.models import CatalogDirection


def test_confirm_yes_no():
    assert confirm("继续?", input_fn=lambda p: "y") is True
    assert confirm("继续?", input_fn=lambda p: "n") is False
    # re-prompts on garbage
    answers = iter(["maybe", "y"])
    assert confirm("继续?", input_fn=lambda p: next(answers)) is True


def test_choose_returns_index_or_none():
    assert choose("选", ["a", "b"], input_fn=lambda p: "2") == 1
    assert choose("选", ["a", "b"], input_fn=lambda p: "") is None
    answers = iter(["9", "x", "1"])
    assert choose("选", ["a", "b"], input_fn=lambda p: next(answers)) == 0
    assert choose("选", [], input_fn=lambda p: "1") is None


def test_ask_direction_reverses_on_demand():
    assert ask_direction(CatalogDirection.UNKNOWN, input_fn=lambda p: "d") is CatalogDirection.DESCENDING
    assert ask_direction(CatalogDirection.UNKNOWN, input_fn=lambda p: "") is CatalogDirection.UNKNOWN


def test_choose_catalog_link_picks_url():
    picked = choose_catalog_link(
        ["http://e.com/all.html", "http://e.com/toc.html"],
        input_fn=lambda p: "2",
    )
    assert picked == "http://e.com/toc.html"
    assert choose_catalog_link(["http://e.com/all.html"], input_fn=lambda p: "") is None
