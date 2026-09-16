"""Generate local benchmark fixtures (guide task 16).

Run once to (re)build benchmarks/sites/*; the benchmark itself never touches
the network. Keeping the generator in-repo documents how each fixture was
authored and makes it easy to add structurally different sites.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent / "sites"

SENTENCES = [
    "山道在雾里若隐若现，少年握紧行囊继续向上。",
    "钟声从谷底传来，一圈一圈荡开，惊起满树飞鸟。",
    "他记得师父说过，修行如逆水行舟，不进则退。",
    "夜色渐深，篝火明明灭灭，映着他清瘦的侧脸。",
    "远处的城池灯火渐次亮起，像撒在黑绸上的碎金。",
    "风穿过林梢，卷起几片落叶，又轻轻放下。",
]


def paragraphs(prefix: str, count: int = 12, sep: str = "</p><p>") -> str:
    body = [
        f"{prefix}第{i}段，{SENTENCES[i % len(SENTENCES)]}" for i in range(1, count + 1)
    ]
    return f"<p>{sep.join(body)}</p>"


def br_lines(prefix: str, count: int = 14) -> str:
    return "<br>".join(
        f"{prefix}第{i}行，{SENTENCES[i % len(SENTENCES)]}" for i in range(1, count + 1)
    )


def chapter_html(title: str, body_html: str, prev=None, nxt=None, catalog=None,
                 next_page=None, prev_page=None, extra_nav="") -> str:
    links = []
    if prev_page:
        links.append(f'<a href="{prev_page}">上一页</a>')
    if next_page:
        links.append(f'<a href="{next_page}">下一页</a>')
    if prev:
        links.append(f'<a href="{prev}">上一章</a>')
    if catalog:
        links.append(f'<a href="{catalog}">目录</a>')
    if nxt:
        links.append(f'<a href="{nxt}">下一章</a>')
    links.append(extra_nav)
    nav = '<div class="page-nav">' + "".join(links) + "</div>" if any(links) else ""
    pagination = '<div class="pages">' + "".join(links[:2]) + "</div>" if (next_page or prev_page) else ""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{title}_小说站</title></head>
<body>
<h1>{title}</h1>
<div id="content">{body_html}</div>
{pagination}{nav}
</body></html>
"""


def catalog_html(book_title: str, entries, next_href=None, prev_href=None, og=True) -> str:
    og_tags = (
        f'<meta property="og:novel:book_name" content="{book_title}">'
        f'<meta property="og:novel:author" content=" benchmark 作者">'
        if og
        else ""
    )
    links = "".join(f'<li><a href="{url}">{title}</a></li>' for title, url in entries)
    pagination = ""
    if prev_href or next_href:
        pagination = (
            '<div class="pages">'
            + (f'<a href="{prev_href}">上一页</a>' if prev_href else "")
            + (f'<a href="{next_href}">下一页</a>' if next_href else "")
            + "</div>"
        )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">{og_tags}<title>{book_title}最新章节列表</title></head>
<body>
<h1>{book_title}</h1>
<ul class="chapter-list">{links}</ul>
{pagination}
</body></html>
"""


def book_html(book_title: str, catalog_href: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{book_title} - 详情</title></head>
<body>
<h1>{book_title}</h1>
<div class="info">作者：benchmark 作者 类型：测试</div>
<div class="intro">内容简介：这是 benchmark 用的虚构书籍简介，讲述一个少年的修行故事。</div>
<div><a href="{catalog_href}">开始阅读</a> <a href="{catalog_href}">查看目录</a></div>
</body></html>
"""


def write_site(site_id: str, files: dict[str, str | bytes], expected: dict) -> None:
    site_dir = ROOT / site_id
    site_dir.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        path = site_dir / name
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
    (site_dir / "expected.json").write_text(
        json.dumps(expected, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )
    print(f"wrote {site_id}: {len(files)} files")


def main() -> None:
    if ROOT.exists():
        import shutil

        shutil.rmtree(ROOT)

    # --- site001: <p> paragraphs, ascending catalog -------------------------
    titles = [f"第{i}章 落霞{i}" for i in range(1, 7)]
    files = {
        "catalog.html": catalog_html("落霞孤鹜", list(zip(titles, [f"{i}.html" for i in range(1, 7)]))),
        **{
            f"{i}.html": chapter_html(
                t, paragraphs("正文"), prev=f"{i - 1}.html" if i > 1 else None,
                nxt=f"{i + 1}.html" if i < 6 else None, catalog="catalog.html",
            )
            for i, t in enumerate(titles, start=1)
        },
    }
    write_site("site001_paragraph_ascending", files, {
        "start": "catalog.html",
        "pages": {"catalog.html": "CATALOG_PAGE", **{f"{i}.html": "CHAPTER_PAGE" for i in range(1, 7)}},
        "metadata": {"book_title": "落霞孤鹜", "author": " benchmark 作者"},
        "catalog": {"titles": titles, "direction": "ASCENDING"},
        "chapter_order": titles,
        "content_must_contain": {t: ["钟声从谷底传来"] for t in titles},
        "content_statuses": {t: "CONTENT_OK" for t in titles},
    })

    # --- site002: <br> lines, descending catalog ----------------------------
    titles = [f"第{i}章 听雪{i}" for i in range(1, 7)]
    files = {
        "catalog.html": catalog_html("听雪楼", list(zip(reversed(titles), [f"{i}.html" for i in reversed(range(1, 7))])), og=False),
        **{
            f"{i}.html": chapter_html(t, br_lines("正文"))
            for i, t in enumerate(titles, start=1)
        },
    }
    write_site("site002_br_descending", files, {
        "start": "catalog.html",
        "pages": {"catalog.html": "CATALOG_PAGE", **{f"{i}.html": "CHAPTER_PAGE" for i in range(1, 7)}},
        "catalog": {"titles": titles, "direction": "DESCENDING"},
        "chapter_order": titles,  # after direction correction
    })

    # --- site003: GBK encoded pages -----------------------------------------
    titles = [f"第{i}章 归尘{i}" for i in range(1, 7)]
    files: dict[str, str | bytes] = {}
    for name, html in {
        "catalog.html": catalog_html("归尘记", list(zip(titles, [f"{i}.html" for i in range(1, 7)]))),
        **{
            f"{i}.html": chapter_html(t, paragraphs("正文"))
            for i, t in enumerate(titles, start=1)
        },
    }.items():
        files[name] = html.replace('charset="utf-8"', 'charset="gbk"').encode("gbk")
    write_site("site003_gbk", files, {
        "start": "catalog.html",
        "encodings": {"catalog.html": "gb18030", "1.html": "gb18030"},
        "pages": {"catalog.html": "CATALOG_PAGE", **{f"{i}.html": "CHAPTER_PAGE" for i in range(1, 7)}},
        "catalog": {"titles": titles, "direction": "ASCENDING"},
        "chapter_order": titles,
    })

    # --- site004: in-chapter pagination --------------------------------------
    titles = [f"第{i}章 断浪{i}" for i in range(1, 7)]
    def misleading_chapter_nav_page(page_no: int, body_html: str, next_href: str) -> str:
        """A chapter page whose site-logo h1 precedes a chapter h2 and whose
        in-chapter page turn is misleadingly labelled 下一章.  A competing
        recommendation block is deliberately dense enough to beat naive text
        density unless chapter-title proximity is considered."""
        nav = (
            '<div class="read_btn"><a href="catalog.html">上一章</a>'
            '<a href="catalog.html">章节目录</a><a>保存书签</a>'
            '<a href="history.html">阅读记录</a>'
            f'<a href="{next_href}">下一章</a></div>'
        )
        recommendations = "".join(
            f'<section><h3><a href="/book/{i}">热门作品{i}</a></h3>'
            f'<p>关于热门作品{i}的长篇推荐介绍，情节跌宕起伏，人物命运交错，'
            '欢迎收藏推荐并继续阅读后续内容。这段介绍故意比普通单段更长。</p></section>'
            for i in range(1, 8)
        )
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>第1章第{page_no}页_断浪小说站</title></head>
<body>
<h1 class="site-title">示例小说网</h1>
<div class="chapter-shell">
<h2 class="chapter-title">第1章（第{page_no}页）</h2>
{nav}
{body_html}
{nav}
</div>
<div class="recommendations"><h2>热门小说推荐</h2>{recommendations}</div>
</body></html>
"""

    files = {
        "catalog.html": catalog_html("断浪", list(zip(titles, [f"{i}.html" for i in range(1, 7)]))),
        "1.html": misleading_chapter_nav_page(1, paragraphs("上半"), "1_2.html"),
        "1_2.html": misleading_chapter_nav_page(2, paragraphs("下半"), "2.html"),
        **{
            f"{i}.html": chapter_html(t, paragraphs("正文"))
            for i, t in zip(range(2, 7), titles[1:])
        },
    }
    write_site("site004_content_pagination", files, {
        "start": "catalog.html",
        "pages": {"catalog.html": "CATALOG_PAGE", **{f"{i}.html": "CHAPTER_PAGE" for i in range(1, 7)}},
        "catalog": {"titles": titles, "direction": "ASCENDING"},
        "chapter_order": titles,
        "content_pagination": {"第1章 断浪1": 2},
        "content_must_contain": {"第1章 断浪1": ["上半", "下半"]},
        "content_must_not_contain": {"第1章 断浪1": ["保存书签", "阅读记录", "热门小说推荐"]},
    })

    # --- site005: catalog pagination -----------------------------------------
    titles = [f"第{i}章 惊鸿{i}" for i in range(1, 17)]
    files = {
        "list.html": catalog_html("惊鸿照影", list(zip(titles[:10], [f"{i}.html" for i in range(1, 11)])), next_href="list_2.html"),
        "list_2.html": catalog_html("惊鸿照影", list(zip(titles[10:], [f"{i}.html" for i in range(11, 17)]))),
        **{
            f"{i}.html": chapter_html(t, paragraphs("正文"))
            for i, t in enumerate(titles, start=1)
        },
    }
    write_site("site005_catalog_pagination", files, {
        "start": "list.html",
        "pages": {"list.html": "CATALOG_PAGE", "list_2.html": "CATALOG_PAGE", **{f"{i}.html": "CHAPTER_PAGE" for i in range(1, 17)}},
        "catalog": {"titles": titles, "direction": "ASCENDING"},
        "catalog_total_entries": 16,
        "chapter_order": titles,
    })

    # --- site006: random chapter URLs ----------------------------------------
    slugs = ["9f3a", "ab77", "k201", "xd04", "m8qz", "e55t"]
    titles = [f"第{i}章 折戟{i}" for i in range(1, 7)]
    files = {
        "catalog.html": catalog_html("折戟沉沙", list(zip(titles, [f"ch_{s}.html" for s in slugs]))),
        **{
            f"ch_{s}.html": chapter_html(t, paragraphs("正文"))
            for s, t in zip(slugs, titles)
        },
    }
    write_site("site006_random_urls", files, {
        "start": "catalog.html",
        "pages": {"catalog.html": "CATALOG_PAGE", **{f"ch_{s}.html": "CHAPTER_PAGE" for s in slugs}},
        "catalog": {"titles": titles, "direction": "ASCENDING"},
        "chapter_order": titles,
    })

    # --- site007: query-string chapter URLs ----------------------------------
    ids = [82, 91, 103, 117, 128, 136]
    titles = [f"第{i}章 长歌{i}" for i in range(1, 7)]
    url_map = {f"chapter_{i}": f"chapter.html?id={i}" for i in ids}
    files = {
        "catalog.html": catalog_html("长歌行", list(zip(titles, [f"chapter.html?id={i}" for i in ids]))),
        **{
            f"chapter_{i}.html": chapter_html(t, paragraphs("正文"))
            for i, t in zip(ids, titles)
        },
    }
    write_site("site007_query_urls", files, {
        "start": "catalog.html",
        "url_map": url_map,
        "pages": {"catalog.html": "CATALOG_PAGE", **{f"chapter_{i}.html": "CHAPTER_PAGE" for i in ids}},
        "catalog": {"titles": titles, "direction": "ASCENDING"},
        "chapter_order": titles,
    })

    # --- site008: restricted / failed pages ----------------------------------
    titles = [f"第{i}章 空山{i}" for i in range(1, 7)]
    files = {
        "catalog.html": catalog_html("空山语", list(zip(titles, [f"{i}.html" for i in range(1, 7)]))),
        "1.html": chapter_html("第1章 空山1", paragraphs("正文"), catalog="catalog.html"),
        "2.html": chapter_html("第2章 空山2", "本章节为VIP章节，订阅后阅读。", catalog="catalog.html"),
        "3.html": chapter_html("第3章 空山3", "请先登录后阅读本章节内容。", catalog="catalog.html"),
        "4.html": chapter_html("第4章 空山4", "", catalog="catalog.html"),
        "5.html": chapter_html("第5章 空山5", paragraphs("正文")),
        "6.html": chapter_html("第6章 空山6", paragraphs("正文")),
    }
    files["4.html"] = files["4.html"].replace('<div id="content"></div>', '<div id="content"><br><br></div>')
    write_site("site008_restricted", files, {
        "start": "catalog.html",
        "pages": {"catalog.html": "CATALOG_PAGE", **{f"{i}.html": "CHAPTER_PAGE" for i in range(1, 7)}},
        "catalog": {"titles": titles, "direction": "ASCENDING"},
        "chapter_order": titles,
        "content_statuses": {
            "第1章 空山1": "CONTENT_OK",
            "第2章 空山2": "PAYWALL",
            "第3章 空山3": "LOGIN_REQUIRED",
            "第4章 空山4": "EMPTY_CONTENT",
            "第5章 空山5": "CONTENT_OK",
            "第6章 空山6": "CONTENT_OK",
        },
    })

    # --- site009: no catalog, traversal only ---------------------------------
    titles = [f"第{i}章 逐流{i}" for i in range(1, 5)]
    files = {
        **{
            f"{i}.html": chapter_html(
                t, paragraphs("正文"),
                prev=f"{i - 1}.html" if i > 1 else None,
                nxt=f"{i + 1}.html" if i < 4 else None,
            )
            for i, t in enumerate(titles, start=1)
        },
    }
    write_site("site009_no_catalog", files, {
        "start": "2.html",
        "pages": {f"{i}.html": "CHAPTER_PAGE" for i in range(1, 5)},
        "catalog": None,
        "navigation": {
            "2.html": {"previous": "1.html", "next": "3.html", "catalog": None},
            "3.html": {"previous": "2.html", "next": "4.html", "catalog": None},
        },
        "chapter_order": titles,
    })

    # --- site010: ads inside content + book detail start ---------------------
    titles = [f"第{i}章 望岳{i}" for i in range(1, 7)]
    files = {
        "index.html": book_html("望岳台", "catalog.html"),
        "catalog.html": catalog_html("望岳台", list(zip(titles, [f"{i}.html" for i in range(1, 7)]))),
        **{
            f"{i}.html": chapter_html(
                t, paragraphs("正文") + "<p>广告位：全网最低价折扣手游充值</p>"
            )
            for i, t in enumerate(titles, start=1)
        },
    }
    write_site("site010_ads_and_book_start", files, {
        "start": "index.html",
        "pages": {
            "index.html": "BOOK_PAGE",
            "catalog.html": "CATALOG_PAGE",
            **{f"{i}.html": "CHAPTER_PAGE" for i in range(1, 7)},
        },
        "metadata": {"book_title": "望岳台"},
        "catalog": {"titles": titles, "direction": "ASCENDING"},
        "chapter_order": titles,
        "content_must_contain": {t: ["山道在雾里"] for t in titles},
    })

    site011_collapsed_quanben()
    site012_onclick_catalog()

    print("done")


def _sub_numbered_part(main: int, sub: int, prev_id: int | None, next_id: int | None) -> str:
    """A per-part chapter page with 上一页/目录/下一页 style navigation
    (chapter hops labelled as pagination words, like quanben)."""
    body = "".join(
        f"<p>p{main}-{sub}第{j}段，山道在雾里若隐若现，少年握紧行囊继续向上。</p>"
        for j in range(1, 13)
    )
    nav = "<div class='page-nav'>"
    if prev_id is not None:
        nav += f'<a href="{prev_id}.html">上一页</a>'
    nav += '<a href="catalog.html">目录</a>'
    if next_id is not None:
        nav += f'<a href="{next_id}.html">下一页</a>'
    nav += "</div>"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>第{main}章 {sub} 折叠目录书</title></head>
<body>
<h1>第{main}章 {sub}</h1>
<div id="content">{body}</div>
{nav}
</body></html>
"""


def site011_collapsed_quanben() -> None:
    """The real-world pattern from quanben.io: collapsed catalog expanded by
    a JSONP loader (custom JS encoder), sub-numbered part chapters, chapter
    hops labelled 上一页/下一页, and a transient throttled empty shell.

    Works through two paths: with quickjs the JSONP expansion recovers the
    middle; without it the gap-fill walks 下一页 links. Either way the book
    must complete, which keeps the fixture honest on both configurations.
    """
    titles: list[tuple[int, int, int]] = []  # (main, sub, file_id)
    file_id = 1
    for main in range(1, 22):
        parts = 3 if main in (2, 3) else 2  # vary part counts
        for sub in range(1, parts + 1):
            titles.append((main, sub, file_id))
            file_id += 1
    by_id = {t[2]: t for t in titles}

    def nav_ids(current: int) -> tuple[int | None, int | None]:
        ids = sorted(by_id)
        pos = ids.index(current)
        return (
            ids[pos - 1] if pos > 0 else None,
            ids[pos + 1] if pos < len(ids) - 1 else None,
        )

    files: dict[str, str | bytes] = {}

    # Static catalog: head cluster (mains 1-5) + marker + tail (19-21).
    head_ids = [t[2] for t in titles if t[0] <= 5]
    tail_ids = [t[2] for t in titles if t[0] >= 19]
    head_links = "".join(
        f'<li><a href="{i}.html">第{by_id[i][0]}章 {by_id[i][1]}</a></li>' for i in head_ids
    )
    tail_links = "".join(
        f'<li><a href="{i}.html">第{by_id[i][0]}章 {by_id[i][1]}</a></li>' for i in tail_ids
    )
    files["catalog.html"] = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta property="og:novel:book_name" content="折叠目录书">
<meta property="og:novel:author" content="折叠 作者">
<title>折叠目录书最新章节列表</title>
<script>
function scramble(s){{return 'P' + s.length + 'X';}}
var callback='6ebc42';
function load_more(book){{
  document.getElementById('detail').innerHTML='<div>[ loading... ]</div>';
  var head=document.getElementsByTagName('head').item(0);
  var el=document.createElement('script');
  el.src='/index.php?c=book&a=list.jsonp&callback='+callback+'&book_id='+book+'&b='+scramble(callback);
  head.appendChild(el);
}}
</script>
</head><body>
<h1>折叠目录书</h1>
<ul class="list3">{head_links}</ul>
<div class="content_more" id="detail"><div class="more">...
<a href="javascript:void(0)" onclick="load_more('42')">[展开完整列表]</a> ...</div></div>
<ul class="list3">{tail_links}</ul>
</body></html>
"""

    # All part pages (chained via 下一页 so the no-quickjs path can walk them).
    for main, sub, i in titles:
        prev_id, next_id = nav_ids(i)
        files[f"{i}.html"] = _sub_numbered_part(main, sub, prev_id, next_id)

    # JSONP response for the hidden middle (mains 6-18).
    middle_ids = [t[2] for t in titles if 6 <= t[0] <= 18]
    middle_links = "".join(
        f'<li><a href="{i}.html">第{by_id[i][0]}章 {by_id[i][1]}</a></li>' for i in middle_ids
    )
    payload = json.dumps({"id": "42", "content": f'<ul class="list3">{middle_links}</ul>'})
    files["jsonp_middle.html"] = f'd6ebc42({payload});'

    part_titles = [f"第{m}章 {s}" for m, s, _i in titles]
    merged_titles = [f"第{m}章" for m in sorted({t[0] for t in titles})]
    write_site("site011_collapsed_quanben", files, {
        "start": "catalog.html",
        "url_map": {"jsonp_middle": "index.php?c=book&a=list.jsonp&callback=6ebc42&book_id=42&b=P6X"},
        "shell_first_fetch": ["20.html"],
        "requires_quickjs": True,
        "expansion_required": True,
        "pages": {
            "catalog.html": "CATALOG_PAGE",
            **{f"{i}.html": "CHAPTER_PAGE" for _m, _s, i in titles},
        },
        "metadata": {"book_title": "折叠目录书", "author": "折叠 作者"},
        "catalog": {"titles": part_titles, "direction": "ASCENDING"},
        "catalog_total_entries": len(titles),
        "chapter_order": merged_titles,
        "content_must_contain": {
            "第1章": ["p1-1", "p1-2"],
            "第10章": ["p10-1", "p10-2"],
            "第21章": ["p21-1", "p21-2"],
        },
        "navigation": {
            f"{head_ids[-1]}.html": {"previous": None, "next": None, "catalog": "catalog.html"},
        },
    })


def site012_onclick_catalog() -> None:
    """Chapter list rendered as <a onclick="read_tz(id)"> with no href; the
    page's JS builds the URL from an id via a template expression. The local
    sandbox must execute read_tz per id to recover the catalog."""
    titles = {i: f"第{i}章 灵东{i}" for i in range(1, 9)}
    links = "".join(
        f'<li><a onclick="read_tz({i}00);">{t}</a></li>' for i, t in titles.items()
    )
    catalog = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta property="og:novel:book_name" content="灵东传">
<meta property="og:novel:author" content="灵东 作者">
<title>灵东传章节列表</title>
<script>
function read_tz(cid){{ location.href = cid + '.html'; }}
</script>
</head><body>
<h1>灵东传</h1>
<ul class="list">{links}</ul>
</body></html>
"""
    files: dict[str, str | bytes] = {"catalog.html": catalog}
    for i, t in titles.items():
        body = "".join(
            f"<p>p{i}第{j}段，山道在雾里若隐若现，少年握紧行囊继续向上。</p>"
            for j in range(1, 13)
        )
        files[f"{i}00.html"] = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>{t}</title></head>
<body><h1>{t}</h1><div id="content">{body}</div></body></html>
"""
    write_site("site012_onclick_catalog", files, {
        "start": "catalog.html",
        "requires_quickjs": True,
        "pages": {
            "catalog.html": "CATALOG_PAGE",
            **{f"{i}00.html": "CHAPTER_PAGE" for i in titles},
        },
        "metadata": {"book_title": "灵东传", "author": "灵东 作者"},
        "catalog": {"titles": list(titles.values()), "direction": "ASCENDING"},
        "catalog_total_entries": len(titles),
        "chapter_order": list(titles.values()),
        "content_must_contain": {"第1章 灵东1": ["p1"], "第8章 灵东8": ["p8"]},
    })


if __name__ == "__main__":
    main()
