"""Human-assisted Correction (guide task 25 / V2).

Interactive prompts used ONLY when local inference cannot decide (direction
UNKNOWN, no catalog found). The user chooses among machine-generated
candidates - never asked to write CSS selectors, XPath, book-source rules or
API keys. All prompts are injectable (`input_fn`) so they are testable and
usable from CLI or future WebUI alike.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence

from novel_extractor.models import CatalogDirection


def confirm(prompt: str, input_fn: Callable[[str], str] = input,
            output_fn: Callable[[str], None] = print) -> bool:
    answer = input_fn(f"{prompt} [y/n]: ").strip().lower()
    while answer not in ("y", "n", "yes", "no"):
        output_fn("请输入 y 或 n")
        answer = input_fn(f"{prompt} [y/n]: ").strip().lower()
    return answer.startswith("y")


def choose(
    prompt: str,
    options: Sequence[str],
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> Optional[int]:
    """Ask the user to pick one of the options; returns the index or None
    (skip). Every option is a machine-generated candidate."""
    if not options:
        return None
    output_fn(prompt)
    for i, option in enumerate(options, start=1):
        output_fn(f"  [{i}] {option}")
    answer = input_fn(f"选择 1-{len(options)}（回车跳过）: ").strip()
    if not answer:
        return None
    while True:
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return int(answer) - 1
        answer = input_fn(f"无效输入，请输入 1-{len(options)}（回车跳过）: ").strip()
        if not answer:
            return None


def ask_direction(
    current: CatalogDirection,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> CatalogDirection:
    """Direction UNKNOWN: the user decides how the DOM order should read."""
    output_fn(f"目录方向无法自动判断（当前按 DOM 顺序保存）。")
    answer = input_fn("按此顺序保存 [enter/y]，反转保存 [d]，中止 [a]: ").strip().lower()
    while answer not in ("", "y", "d", "a"):
        answer = input_fn("无效输入 [enter/y | d | a]: ").strip().lower()
    if answer == "d":
        return CatalogDirection.DESCENDING
    if answer == "a":
        return CatalogDirection.UNKNOWN  # caller aborts
    return current


def choose_catalog_link(
    candidates: Sequence[str],
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> Optional[str]:
    """No catalog found: the user picks which candidate link to try as the
    catalog page (None = give up and fall back to traversal)."""
    index = choose(
        "检测到以下可能的目录链接，请选择：",
        list(candidates),
        input_fn,
        output_fn,
    )
    return candidates[index] if index is not None else None
