"""Tests for the Inference Cache (guide task 20)."""

from __future__ import annotations

from pathlib import Path

from novel_extractor.cache import InferenceCache
from novel_extractor.fetcher.http import FetchedPage

PAGE = f"""
<html><head><title>第12章 出山_灵东传 - 某站</title></head><body>
<nav><a href="/">首页</a><a href="/sort">分类</a><a href="/rank">排行</a><a href="/login">登录</a></nav>
<h1>第12章 出山</h1>
<div id="content">{''.join(f'<p>第{i}段，山风吹过林梢，主角抬眼望向远方。</p>' for i in range(1, 13))}</div>
<div class="page-nav"><a href="/b/11.html">上一章</a><a href="/b/13.html">下一章</a></div>
</body></html>
"""


def make_page(url="http://e.com/b/12.html"):
    return FetchedPage(
        url=url, final_url=url, status_code=200, raw_bytes=PAGE.encode(),
        html=PAGE, encoding="utf-8", encoding_source="test", encoding_confidence=1.0,
    )


def test_profile_roundtrip_and_persistence(tmp_path):
    cache = InferenceCache(cache_dir=tmp_path / "cache")
    profile = cache.profile_from_page(PAGE, "http://e.com/b/12.html")
    assert profile.host == "e.com"
    assert profile.chapter_dir == "/b"
    assert profile.chapter_dirname_numeric is True
    assert any("content" in str(sig) for sig in profile.content_signature) or profile.content_signature
    cache.put(profile)

    # a new cache instance loads the persisted profile
    cache2 = InferenceCache(cache_dir=tmp_path / "cache")
    loaded = cache2.get("e.com")
    assert loaded is not None
    assert loaded.title_template == profile.title_template
    assert loaded.chapter_dir == profile.chapter_dir


def test_light_validation_passes_on_same_shape(tmp_path):
    cache = InferenceCache(cache_dir=tmp_path)
    profile = cache.profile_from_page(PAGE, "http://e.com/b/12.html")
    cache.put(profile)

    other = PAGE.replace("第12章 出山", "第13章 出山")
    result = cache.validate_light("http://e.com/b/13.html", other, profile)
    assert result.ok
    assert result.diagnostics["passed"] == result.diagnostics["checks"]


def test_light_validation_fails_on_drift(tmp_path):
    cache = InferenceCache(cache_dir=tmp_path)
    profile = cache.profile_from_page(PAGE, "http://e.com/b/12.html")
    cache.put(profile)

    drifted = PAGE.replace("第12章 出山_灵东传 - 某站", "完全改版的另一个站").replace(
        "/b/11.html", "/posts/11/"
    ).replace("/b/13.html", "/posts/13/")
    result = cache.validate_light("http://e.com/posts/13.html", drifted, profile)
    assert not result.ok


def test_invalidation_removes_profile(tmp_path):
    cache = InferenceCache(cache_dir=tmp_path / "cache")
    profile = cache.profile_from_page(PAGE, "http://e.com/b/12.html")
    cache.put(profile)
    assert cache.get("e.com") is not None
    cache.invalidate("e.com")
    assert cache.get("e.com") is None
    assert not (tmp_path / "cache" / "e.com.json").exists()


def test_stale_version_invalidated(tmp_path):
    import json

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    stale = {"host": "e.com", "version": 999}
    (cache_dir / "e.com.json").write_text(json.dumps(stale), encoding="utf-8")

    cache = InferenceCache(cache_dir=cache_dir)
    assert cache.get("e.com") is None
    assert not (cache_dir / "e.com.json").exists()


def test_content_signature_check(tmp_path):
    cache = InferenceCache(cache_dir=tmp_path)
    profile = cache.profile_from_page(PAGE, "http://e.com/b/12.html")
    from bs4 import BeautifulSoup

    node = BeautifulSoup(PAGE, "lxml").find("div", id="content")
    assert cache.check_content_signature(profile, node) is True
    wrong = BeautifulSoup("<div><a href=x>link</a>text</div>", "lxml").div
    assert cache.check_content_signature(profile, wrong) is False


def test_hosts_listing(tmp_path):
    cache = InferenceCache(cache_dir=tmp_path / "cache")
    cache.put(cache.profile_from_page(PAGE, "http://e.com/b/12.html"))
    assert cache.hosts() == ["e.com"]
    cache.clear()
    assert cache.hosts() == []
