# Benchmark Failure Analysis

Baseline: `baseline_v0` (`offline-20260917-100826`)

The run was offline. Results below keep synthetic, real_fixture, challenge, and dynamic cases separate.

## Dataset counts

- Synthetic: `7`
- Real fixture: `0`
- Challenge: `1`
- Dynamic: `0`

The challenge case is synthetic by provenance but is excluded from the ordinary synthetic reporting bucket.

## Baseline metric counts

| Metric | Success | Failure | Denominator | Samples | Abstentions |
|---|---:|---:|---:|---:|---:|
| `access_status_accuracy` | 22 | 1 | 23 | 23 | 0 |
| `body_noise_exclusion` | 2 | 1 | 3 | 3 | 0 |
| `catalog_direction_accuracy` | 0 | 3 | 3 | 3 | 0 |
| `catalog_precision` | 8 | 0 | 8 | 3 | 0 |
| `catalog_recall` | 8 | 7 | 15 | 3 | 0 |
| `content_precision_chars` | 6262 | 1293 | 7555 | 20 | 1 |
| `content_retained_chars` | 6262 | 816 | 7078 | 20 | 1 |
| `content_status_accuracy` | 16 | 2 | 18 | 18 | 1 |
| `logical_chapter_presence` | 4 | 5 | 9 | 9 | 0 |
| `metadata_suppression` | 0 | 2 | 2 | 2 | 0 |
| `navigation_accuracy` | 2 | 0 | 2 | 2 | 0 |
| `page_type_accuracy` | 17 | 6 | 23 | 23 | 0 |
| `pagination_merge_accuracy` | 2 | 2 | 4 | 4 | 0 |
| `pagination_relation_accuracy` | 1 | 2 | 3 | 3 | 0 |
| `partial_failure_reported` | 1 | 0 | 1 | 1 | 0 |
| `reading_chain_exact` | 1 | 2 | 3 | 3 | 0 |
| `unsafe_body_rejection` | 5 | 0 | 5 | 5 | 0 |

## Page type confusion matrix

Rows are expected labels; columns are predicted labels.

| Expected \ Predicted | BOOK_PAGE | CATALOG_PAGE | CHAPTER_PAGE | UNKNOWN |
|---|---:|---:|---:|---:|
| BOOK_PAGE | 0 | 0 | 0 | 2 |
| CATALOG_PAGE | 0 | 1 | 0 | 2 |
| CHAPTER_PAGE | 0 | 0 | 14 | 2 |
| UNKNOWN | 0 | 0 | 0 | 2 |

Misclassifications:

- `syn_catalog_pagination / catalog_1`: CATALOG_PAGE -> UNKNOWN
- `syn_catalog_pagination / catalog_2`: CATALOG_PAGE -> UNKNOWN
- `syn_encoding_bytes / conflict_page`: CHAPTER_PAGE -> UNKNOWN
- `syn_fragment_identity / fragment_1`: BOOK_PAGE -> UNKNOWN
- `syn_fragment_identity / fragment_2`: BOOK_PAGE -> UNKNOWN
- `syn_text_structures / short_prologue`: CHAPTER_PAGE -> UNKNOWN

## Failure taxonomy distribution

| Category | Count | Case ids |
|---|---:|---|
| `FETCH_ERROR` | 0 | — |
| `ENCODING_ERROR` | 2 | `syn_encoding_bytes` |
| `PAGE_TYPE_FALSE_POSITIVE` | 0 | — |
| `PAGE_TYPE_FALSE_NEGATIVE` | 6 | `syn_catalog_pagination`, `syn_encoding_bytes`, `syn_fragment_identity`, `syn_text_structures` |
| `PAGE_TYPE_WRONG_CLASS` | 0 | — |
| `CONTENT_FALSE_POSITIVE` | 0 | — |
| `CONTENT_TRUNCATED` | 3 | `syn_catalog_pagination`, `syn_content_pagination`, `syn_text_structures` |
| `CONTENT_NOISE_INCLUDED` | 7 | `syn_catalog_pagination`, `syn_content_pagination`, `syn_partial_failure`, `syn_text_structures` |
| `CONTENT_STATUS_WRONG` | 2 | `syn_access_states`, `syn_text_structures` |
| `CATALOG_NOT_FOUND` | 2 | `syn_catalog_pagination` |
| `CATALOG_WRONG_GROUP` | 0 | — |
| `CATALOG_WRONG_DIRECTION` | 3 | `syn_catalog_pagination`, `syn_volume_reset_table` |
| `CATALOG_PAGINATION_MISSED` | 2 | `syn_catalog_pagination` |
| `CONTENT_PAGINATION_MISSED` | 0 | — |
| `CONTENT_PAGINATION_OVERMERGED` | 2 | `syn_catalog_pagination`, `syn_content_pagination` |
| `NAVIGATION_WRONG_RELATION` | 0 | — |
| `METADATA_WRONG_TITLE` | 2 | `syn_access_states` |
| `METADATA_WRONG_AUTHOR` | 0 | — |
| `ACCESS_PAGE_MISCLASSIFIED` | 1 | `syn_access_states` |
| `CHAPTER_MISSING` | 5 | `syn_catalog_pagination` |
| `READING_ORDER_WRONG` | 2 | `syn_catalog_pagination`, `syn_content_pagination` |
| `EXPORT_INCOMPLETE_NOT_REPORTED` | 0 | — |

## Per-case failure diagnostics

### syn_access_states / challenge_403

- Sample type: `challenge`
- Metric: `content_status_accuracy`
- Failure category: `CONTENT_STATUS_WRONG`
- Confidence: `0.7`
- Expected: `ANTI_BOT`
- Actual: `ACCESS_RESTRICTED`
- Diagnostics: `{"reason": "HTTP 403 forbidden-ish"}`

### syn_access_states / challenge_403

- Sample type: `challenge`
- Metric: `access_status_accuracy`
- Failure category: `ACCESS_PAGE_MISCLASSIFIED`
- Confidence: `0.7`
- Expected: `ANTI_BOT`
- Actual: `ACCESS_RESTRICTED`
- Diagnostics: `{"reason": "HTTP 403 forbidden-ish"}`

### syn_access_states / challenge_403

- Sample type: `challenge`
- Metric: `metadata_suppression`
- Failure category: `METADATA_WRONG_TITLE`
- Confidence: `0.45`
- Expected: `{"book_title": null, "author": null}`
- Actual: `{"book_title": "Just"}`
- Diagnostics: `{"unsafe_for_metadata": true}`

### syn_access_states / challenge_200

- Sample type: `challenge`
- Metric: `metadata_suppression`
- Failure category: `METADATA_WRONG_TITLE`
- Confidence: `0.45`
- Expected: `{"book_title": null, "author": null}`
- Actual: `{"book_title": "Just"}`
- Diagnostics: `{"unsafe_for_metadata": true}`

### syn_catalog_pagination / catalog_1

- Sample type: `synthetic`
- Metric: `page_type_accuracy`
- Failure category: `PAGE_TYPE_FALSE_NEGATIVE`
- Confidence: `0.4`
- Expected: `CATALOG_PAGE`
- Actual: `UNKNOWN`
- Diagnostics: `{"reason": "no type reached threshold or top scores too close (chapter=0.10, catalog=0.10, book=0.40)"}`

### syn_catalog_pagination / catalog_1

- Sample type: `synthetic`
- Metric: `catalog_recall`
- Failure category: `CATALOG_NOT_FOUND`
- Confidence: `0.1`
- Expected: `[["第1章", "https://synthetic.invalid/catalog/ch1"], ["第2章", "https://synthetic.invalid/catalog/ch2"], ["第3章", "https://synthetic.invalid/catalog/ch3"], ["第4章", "https://synthetic.invalid/catalog/ch4"]]`
- Actual: `[]`
- Diagnostics: `{"parser_selected_group": null, "top_scored_group": "catalog_group_1", "parser_result_reason": "largest chapter-link cluster has only 4 anchors (< 5)", "candidates": [{"candidate_id": "catalog_group_1", "parent_dom_path": "html > body > ul", "link_count": 4, "chapter_title_match_count": 4, "chapter_title_match_ratio": 1.0, "average_anchor_text_length": 3.0, "link_text_ratio": 1.0, "dom_depth": 3, "url_similarity": 1.0, "final_score": 0.25, "positive_reasons": ["chapter title match ratio=1.00", "dominant URL directory ratio=1.00"], "penalties": ["chapter-like cluster below parser minimum 5"], "target_urls": ["https://synthetic.invalid/catalog/ch1", "https://synthetic.invalid/catalog/ch2", "https://synthetic.invalid/catalog/ch3", "https://synthetic.invalid/catalog/ch4"], "parser_selected": false}], "expected_group": "catalog_group_1", "expected_group_overlap": 4, "expected_group_not_selected_reason": "expected group was below the parser minimum of 5 chapter-like anchors"}`

### syn_catalog_pagination / catalog_1

- Sample type: `synthetic`
- Metric: `catalog_direction_accuracy`
- Failure category: `CATALOG_WRONG_DIRECTION`
- Confidence: `0.1`
- Expected: `ASCENDING`
- Actual: `UNKNOWN`
- Diagnostics: `{"parser_selected_group": null, "top_scored_group": "catalog_group_1", "parser_result_reason": "largest chapter-link cluster has only 4 anchors (< 5)", "candidates": [{"candidate_id": "catalog_group_1", "parent_dom_path": "html > body > ul", "link_count": 4, "chapter_title_match_count": 4, "chapter_title_match_ratio": 1.0, "average_anchor_text_length": 3.0, "link_text_ratio": 1.0, "dom_depth": 3, "url_similarity": 1.0, "final_score": 0.25, "positive_reasons": ["chapter title match ratio=1.00", "dominant URL directory ratio=1.00"], "penalties": ["chapter-like cluster below parser minimum 5"], "target_urls": ["https://synthetic.invalid/catalog/ch1", "https://synthetic.invalid/catalog/ch2", "https://synthetic.invalid/catalog/ch3", "https://synthetic.invalid/catalog/ch4"], "parser_selected": false}]}`

### syn_catalog_pagination / catalog_1

- Sample type: `synthetic`
- Metric: `pagination_relation_accuracy`
- Failure category: `CATALOG_PAGINATION_MISSED`
- Confidence: `0.62`
- Expected: `{"type": "NEXT_CATALOG_PAGE", "target_page_id": "catalog_2", "target_url": "https://synthetic.invalid/catalog/list-2", "evidence": "next page link"}`
- Actual: `{"anchor_text": "下一页", "target_url": "https://synthetic.invalid/catalog/list-2", "predicted_relation": "UNKNOWN", "relation_confidence": 0.62, "positive_reasons": ["anchor text contains '下一页'"], "penalties": ["page type is UNKNOWN, so pagination kind cannot be assigned"]}`
- Diagnostics: `{"relation_candidates": [{"anchor_text": "下一页", "target_url": "https://synthetic.invalid/catalog/list-2", "predicted_relation": "UNKNOWN", "relation_confidence": 0.62, "positive_reasons": ["anchor text contains '下一页'"], "penalties": ["page type is UNKNOWN, so pagination kind cannot be assigned"]}]}`

### syn_catalog_pagination / catalog_2

- Sample type: `synthetic`
- Metric: `page_type_accuracy`
- Failure category: `PAGE_TYPE_FALSE_NEGATIVE`
- Confidence: `0.4`
- Expected: `CATALOG_PAGE`
- Actual: `UNKNOWN`
- Diagnostics: `{"reason": "no type reached threshold or top scores too close (chapter=0.10, catalog=0.10, book=0.40)"}`

### syn_catalog_pagination / catalog_2

- Sample type: `synthetic`
- Metric: `catalog_recall`
- Failure category: `CATALOG_NOT_FOUND`
- Confidence: `0.1`
- Expected: `[["第4章", "https://synthetic.invalid/catalog/ch4"], ["第5章", "https://synthetic.invalid/catalog/ch5"], ["第6章", "https://synthetic.invalid/catalog/ch6"]]`
- Actual: `[]`
- Diagnostics: `{"parser_selected_group": null, "top_scored_group": "catalog_group_1", "parser_result_reason": "largest chapter-link cluster has only 3 anchors (< 5)", "candidates": [{"candidate_id": "catalog_group_1", "parent_dom_path": "html > body > ul", "link_count": 3, "chapter_title_match_count": 3, "chapter_title_match_ratio": 1.0, "average_anchor_text_length": 3.0, "link_text_ratio": 1.0, "dom_depth": 3, "url_similarity": 1.0, "final_score": 0.25, "positive_reasons": ["chapter title match ratio=1.00", "dominant URL directory ratio=1.00"], "penalties": ["chapter-like cluster below parser minimum 5"], "target_urls": ["https://synthetic.invalid/catalog/ch4", "https://synthetic.invalid/catalog/ch5", "https://synthetic.invalid/catalog/ch6"], "parser_selected": false}], "expected_group": "catalog_group_1", "expected_group_overlap": 3, "expected_group_not_selected_reason": "expected group was below the parser minimum of 5 chapter-like anchors"}`

### syn_catalog_pagination / catalog_2

- Sample type: `synthetic`
- Metric: `catalog_direction_accuracy`
- Failure category: `CATALOG_WRONG_DIRECTION`
- Confidence: `0.1`
- Expected: `ASCENDING`
- Actual: `UNKNOWN`
- Diagnostics: `{"parser_selected_group": null, "top_scored_group": "catalog_group_1", "parser_result_reason": "largest chapter-link cluster has only 3 anchors (< 5)", "candidates": [{"candidate_id": "catalog_group_1", "parent_dom_path": "html > body > ul", "link_count": 3, "chapter_title_match_count": 3, "chapter_title_match_ratio": 1.0, "average_anchor_text_length": 3.0, "link_text_ratio": 1.0, "dom_depth": 3, "url_similarity": 1.0, "final_score": 0.25, "positive_reasons": ["chapter title match ratio=1.00", "dominant URL directory ratio=1.00"], "penalties": ["chapter-like cluster below parser minimum 5"], "target_urls": ["https://synthetic.invalid/catalog/ch4", "https://synthetic.invalid/catalog/ch5", "https://synthetic.invalid/catalog/ch6"], "parser_selected": false}]}`

### syn_catalog_pagination / catalog_2

- Sample type: `synthetic`
- Metric: `pagination_relation_accuracy`
- Failure category: `CATALOG_PAGINATION_MISSED`
- Confidence: `None`
- Expected: `{"type": "PREVIOUS_CATALOG_PAGE", "target_page_id": "catalog_1", "target_url": "https://synthetic.invalid/catalog/list-1", "evidence": "previous page link"}`
- Actual: `{"predicted_relation": null, "target_url": null}`
- Diagnostics: `{"relation_candidates": []}`

### syn_catalog_pagination / ch1

- Sample type: `synthetic`
- Metric: `pagination_merge_accuracy`
- Failure category: `CONTENT_PAGINATION_OVERMERGED`
- Confidence: `None`
- Expected: `{"source_urls": ["https://synthetic.invalid/catalog/ch1"]}`
- Actual: `{"source_urls": ["https://synthetic.invalid/catalog/list-1", "https://synthetic.invalid/catalog/list-2"]}`
- Diagnostics: `{"crawler_warnings": ["no catalog found; falling back to chapter-link traversal"]}`

### syn_catalog_pagination / logical:ch1

- Sample type: `synthetic`
- Metric: `content_retained_chars`
- Failure category: `CONTENT_TRUNCATED`
- Confidence: `None`
- Expected: `{"reference_length": 321}`
- Actual: `{"predicted_length": 45, "matched_characters": 21}`
- Diagnostics: `{"source_urls": ["https://synthetic.invalid/catalog/list-1", "https://synthetic.invalid/catalog/list-2"]}`

### syn_catalog_pagination / logical:ch1

- Sample type: `synthetic`
- Metric: `content_precision_chars`
- Failure category: `CONTENT_NOISE_INCLUDED`
- Confidence: `None`
- Expected: `{"reference_length": 321}`
- Actual: `{"predicted_length": 45, "matched_characters": 21}`
- Diagnostics: `{"source_urls": ["https://synthetic.invalid/catalog/list-1", "https://synthetic.invalid/catalog/list-2"]}`

### syn_catalog_pagination / ch2

- Sample type: `synthetic`
- Metric: `logical_chapter_presence`
- Failure category: `CHAPTER_MISSING`
- Confidence: `None`
- Expected: `{"chapter_id": "ch2", "title": "第2章", "source_page_ids": ["chapter_2"], "reference_text_path": "../../fixtures/synthetic/syn_catalog_pagination/reference/logical_2.txt", "complete_within_case": true}`
- Actual: `null`
- Diagnostics: `{"crawler_warnings": ["no catalog found; falling back to chapter-link traversal"]}`

### syn_catalog_pagination / ch3

- Sample type: `synthetic`
- Metric: `logical_chapter_presence`
- Failure category: `CHAPTER_MISSING`
- Confidence: `None`
- Expected: `{"chapter_id": "ch3", "title": "第3章", "source_page_ids": ["chapter_3"], "reference_text_path": "../../fixtures/synthetic/syn_catalog_pagination/reference/logical_3.txt", "complete_within_case": true}`
- Actual: `null`
- Diagnostics: `{"crawler_warnings": ["no catalog found; falling back to chapter-link traversal"]}`

### syn_catalog_pagination / ch4

- Sample type: `synthetic`
- Metric: `logical_chapter_presence`
- Failure category: `CHAPTER_MISSING`
- Confidence: `None`
- Expected: `{"chapter_id": "ch4", "title": "第4章", "source_page_ids": ["chapter_4"], "reference_text_path": "../../fixtures/synthetic/syn_catalog_pagination/reference/logical_4.txt", "complete_within_case": true}`
- Actual: `null`
- Diagnostics: `{"crawler_warnings": ["no catalog found; falling back to chapter-link traversal"]}`

### syn_catalog_pagination / ch5

- Sample type: `synthetic`
- Metric: `logical_chapter_presence`
- Failure category: `CHAPTER_MISSING`
- Confidence: `None`
- Expected: `{"chapter_id": "ch5", "title": "第5章", "source_page_ids": ["chapter_5"], "reference_text_path": "../../fixtures/synthetic/syn_catalog_pagination/reference/logical_5.txt", "complete_within_case": true}`
- Actual: `null`
- Diagnostics: `{"crawler_warnings": ["no catalog found; falling back to chapter-link traversal"]}`

### syn_catalog_pagination / ch6

- Sample type: `synthetic`
- Metric: `logical_chapter_presence`
- Failure category: `CHAPTER_MISSING`
- Confidence: `None`
- Expected: `{"chapter_id": "ch6", "title": "第6章", "source_page_ids": ["chapter_6"], "reference_text_path": "../../fixtures/synthetic/syn_catalog_pagination/reference/logical_6.txt", "complete_within_case": true}`
- Actual: `null`
- Diagnostics: `{"crawler_warnings": ["no catalog found; falling back to chapter-link traversal"]}`

### syn_catalog_pagination / syn_catalog_pagination

- Sample type: `synthetic`
- Metric: `reading_chain_exact`
- Failure category: `READING_ORDER_WRONG`
- Confidence: `None`
- Expected: `["ch1", "ch2", "ch3", "ch4", "ch5", "ch6"]`
- Actual: `["ch1"]`
- Diagnostics: `{"predicted_chapter_count": 1}`

### syn_content_pagination / logical:ch1

- Sample type: `synthetic`
- Metric: `content_precision_chars`
- Failure category: `CONTENT_NOISE_INCLUDED`
- Confidence: `None`
- Expected: `{"reference_length": 587}`
- Actual: `{"predicted_length": 626, "matched_characters": 587}`
- Diagnostics: `{"source_urls": ["https://synthetic.invalid/pagination/ch1-1", "https://synthetic.invalid/pagination/ch1-2"]}`

### syn_content_pagination / ch2

- Sample type: `synthetic`
- Metric: `pagination_merge_accuracy`
- Failure category: `CONTENT_PAGINATION_OVERMERGED`
- Confidence: `None`
- Expected: `{"source_urls": ["https://synthetic.invalid/pagination/ch2"]}`
- Actual: `{"source_urls": ["https://synthetic.invalid/pagination/ch1-2"]}`
- Diagnostics: `{"crawler_warnings": ["no catalog found; falling back to chapter-link traversal", "重复章节节点：第1章 海路（第2页） duplicates 第1章 海路（第1页） (['https://synthetic.invalid/pagination/ch1-2'])"]}`

### syn_content_pagination / logical:ch2

- Sample type: `synthetic`
- Metric: `content_retained_chars`
- Failure category: `CONTENT_TRUNCATED`
- Confidence: `None`
- Expected: `{"reference_length": 440}`
- Actual: `{"predicted_length": 311, "matched_characters": 272}`
- Diagnostics: `{"source_urls": ["https://synthetic.invalid/pagination/ch1-2"]}`

### syn_content_pagination / logical:ch2

- Sample type: `synthetic`
- Metric: `content_precision_chars`
- Failure category: `CONTENT_NOISE_INCLUDED`
- Confidence: `None`
- Expected: `{"reference_length": 440}`
- Actual: `{"predicted_length": 311, "matched_characters": 272}`
- Diagnostics: `{"source_urls": ["https://synthetic.invalid/pagination/ch1-2"]}`

### syn_content_pagination / syn_content_pagination

- Sample type: `synthetic`
- Metric: `reading_chain_exact`
- Failure category: `READING_ORDER_WRONG`
- Confidence: `None`
- Expected: `["ch1", "ch2"]`
- Actual: `["ch1", "ch2"]`
- Diagnostics: `{"predicted_chapter_count": 3}`

### syn_encoding_bytes / conflict_page

- Sample type: `synthetic`
- Metric: `page_type_accuracy`
- Failure category: `PAGE_TYPE_FALSE_NEGATIVE`
- Confidence: `0.5`
- Expected: `CHAPTER_PAGE`
- Actual: `UNKNOWN`
- Diagnostics: `{"reason": "no type reached threshold or top scores too close (chapter=0.47, catalog=0.10, book=0.50)"}`

### syn_encoding_bytes / conflict_page

- Sample type: `synthetic`
- Metric: `content_retained_chars`
- Failure category: `ENCODING_ERROR`
- Confidence: `0.99`
- Expected: `{"reference_length": 343}`
- Actual: `{"predicted_length": 519, "matched_characters": 15}`
- Diagnostics: `{"reason": "DOM density winner <article>: text=519, punct=8, link_ratio=0.00, paragraphs=8; trafilatura agrees (ratio=0.90)"}`

### syn_encoding_bytes / conflict_page

- Sample type: `synthetic`
- Metric: `content_precision_chars`
- Failure category: `ENCODING_ERROR`
- Confidence: `0.99`
- Expected: `{"reference_length": 343}`
- Actual: `{"predicted_length": 519, "matched_characters": 15}`
- Diagnostics: `{"reason": "DOM density winner <article>: text=519, punct=8, link_ratio=0.00, paragraphs=8; trafilatura agrees (ratio=0.90)"}`

### syn_fragment_identity / fragment_1

- Sample type: `synthetic`
- Metric: `page_type_accuracy`
- Failure category: `PAGE_TYPE_FALSE_NEGATIVE`
- Confidence: `0.4`
- Expected: `BOOK_PAGE`
- Actual: `UNKNOWN`
- Diagnostics: `{"reason": "no type reached threshold or top scores too close (chapter=0.10, catalog=0.10, book=0.40)"}`

### syn_fragment_identity / fragment_2

- Sample type: `synthetic`
- Metric: `page_type_accuracy`
- Failure category: `PAGE_TYPE_FALSE_NEGATIVE`
- Confidence: `0.4`
- Expected: `BOOK_PAGE`
- Actual: `UNKNOWN`
- Diagnostics: `{"reason": "no type reached threshold or top scores too close (chapter=0.10, catalog=0.10, book=0.40)"}`

### syn_partial_failure / logical:ch1

- Sample type: `synthetic`
- Metric: `content_precision_chars`
- Failure category: `CONTENT_NOISE_INCLUDED`
- Confidence: `None`
- Expected: `{"reference_length": 335}`
- Actual: `{"predicted_length": 356, "matched_characters": 335}`
- Diagnostics: `{"source_urls": ["https://synthetic.invalid/partial/chapter-1"]}`

### syn_text_structures / comments_chapter

- Sample type: `synthetic`
- Metric: `content_retained_chars`
- Failure category: `CONTENT_TRUNCATED`
- Confidence: `0.99`
- Expected: `{"reference_length": 410}`
- Actual: `{"predicted_length": 1050, "matched_characters": 390}`
- Diagnostics: `{"reason": "DOM density winner <section>: text=1050, punct=88, link_ratio=0.00, paragraphs=22; trafilatura agrees (ratio=0.77)"}`

### syn_text_structures / comments_chapter

- Sample type: `synthetic`
- Metric: `content_precision_chars`
- Failure category: `CONTENT_NOISE_INCLUDED`
- Confidence: `0.99`
- Expected: `{"reference_length": 410}`
- Actual: `{"predicted_length": 1050, "matched_characters": 390}`
- Diagnostics: `{"reason": "DOM density winner <section>: text=1050, punct=88, link_ratio=0.00, paragraphs=22; trafilatura agrees (ratio=0.77)"}`

### syn_text_structures / comments_chapter

- Sample type: `synthetic`
- Metric: `body_noise_exclusion`
- Failure category: `CONTENT_NOISE_INCLUDED`
- Confidence: `0.99`
- Expected: `{"forbidden_text": "读者评论请勿进入正文"}`
- Actual: `{"included": true}`
- Diagnostics: `{"reason": "DOM density winner <section>: text=1050, punct=88, link_ratio=0.00, paragraphs=22; trafilatura agrees (ratio=0.77)"}`

### syn_text_structures / short_prologue

- Sample type: `synthetic`
- Metric: `page_type_accuracy`
- Failure category: `PAGE_TYPE_FALSE_NEGATIVE`
- Confidence: `0.45`
- Expected: `CHAPTER_PAGE`
- Actual: `UNKNOWN`
- Diagnostics: `{"reason": "no type reached threshold or top scores too close (chapter=0.45, catalog=0.10, book=0.10)"}`

### syn_text_structures / short_prologue

- Sample type: `synthetic`
- Metric: `content_status_accuracy`
- Failure category: `CONTENT_STATUS_WRONG`
- Confidence: `0.6`
- Expected: `CONTENT_OK`
- Actual: `EMPTY_CONTENT`
- Diagnostics: `{"reason": "content suspiciously short (30 chars) with no explicit restriction phrase"}`

### syn_text_structures / short_prologue

- Sample type: `synthetic`
- Metric: `content_precision_chars`
- Failure category: `CONTENT_NOISE_INCLUDED`
- Confidence: `0.44999999999999996`
- Expected: `{"reference_length": 24}`
- Actual: `{"predicted_length": 30, "matched_characters": 24}`
- Diagnostics: `{"reason": "no div/article/main/section candidate reached threshold; body fallback; trafilatura agrees (ratio=1.00)"}`

### syn_volume_reset_table / catalog

- Sample type: `synthetic`
- Metric: `catalog_direction_accuracy`
- Failure category: `CATALOG_WRONG_DIRECTION`
- Confidence: `0.55`
- Expected: `MIXED`
- Actual: `UNKNOWN`
- Diagnostics: `{"parser_selected_group": "catalog_group_1", "top_scored_group": "catalog_group_1", "parser_result_reason": "8 chapter-like anchors clustered in DOM (strong_ratio=1.00, url_dir=/volumes)", "candidates": [{"candidate_id": "catalog_group_1", "parent_dom_path": "html > body > table", "link_count": 8, "chapter_title_match_count": 8, "chapter_title_match_ratio": 1.0, "average_anchor_text_length": 10.0, "link_text_ratio": 1.0, "dom_depth": 3, "url_similarity": 1.0, "final_score": 0.55, "positive_reasons": ["chapter-like cluster size=8", "chapter title match ratio=1.00", "dominant URL directory ratio=1.00"], "penalties": [], "target_urls": ["https://synthetic.invalid/volumes/v1-c4", "https://synthetic.invalid/volumes/v1-c3", "https://synthetic.invalid/volumes/v1-c2", "https://synthetic.invalid/volumes/v1-c1", "https://synthetic.invalid/volumes/v2-c4", "https://synthetic.invalid/volumes/v2-c3", "https://synthetic.invalid/volumes/v2-c2", "https://synthetic.invalid/volumes/v2-c1"], "parser_selected": true}]}`

## Catalog failure details

### syn_catalog_pagination / catalog_1

- Parser selected group: `None`
- Expected group: `catalog_group_1`
- Why expected group was not selected: expected group was below the parser minimum of 5 chapter-like anchors

| Candidate | Parent DOM path | Links | Chapter matches | Match ratio | Avg text length | Link text ratio | Depth | URL similarity | Score | Positive reasons | Penalties |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| catalog_group_1 | html > body > ul | 4 | 4 | 1.0 | 3.0 | 1.0 | 3 | 1.0 | 0.25 | ["chapter title match ratio=1.00", "dominant URL directory ratio=1.00"] | ["chapter-like cluster below parser minimum 5"] |

### syn_catalog_pagination / catalog_2

- Parser selected group: `None`
- Expected group: `catalog_group_1`
- Why expected group was not selected: expected group was below the parser minimum of 5 chapter-like anchors

| Candidate | Parent DOM path | Links | Chapter matches | Match ratio | Avg text length | Link text ratio | Depth | URL similarity | Score | Positive reasons | Penalties |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| catalog_group_1 | html > body > ul | 3 | 3 | 1.0 | 3.0 | 1.0 | 3 | 1.0 | 0.25 | ["chapter title match ratio=1.00", "dominant URL directory ratio=1.00"] | ["chapter-like cluster below parser minimum 5"] |

### syn_volume_reset_table / catalog

- Parser selected group: `catalog_group_1`
- Expected group: `None`
- Why expected group was not selected: not applicable

| Candidate | Parent DOM path | Links | Chapter matches | Match ratio | Avg text length | Link text ratio | Depth | URL similarity | Score | Positive reasons | Penalties |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| catalog_group_1 | html > body > table | 8 | 8 | 1.0 | 10.0 | 1.0 | 3 | 1.0 | 0.55 | ["chapter-like cluster size=8", "chapter title match ratio=1.00", "dominant URL directory ratio=1.00"] | [] |

## Pagination relation failure details

### syn_catalog_pagination / catalog_1

- Expected relation/pages: `{"type": "NEXT_CATALOG_PAGE", "target_page_id": "catalog_2", "target_url": "https://synthetic.invalid/catalog/list-2", "evidence": "next page link"}`
- Parser selection/pages: `{"anchor_text": "下一页", "target_url": "https://synthetic.invalid/catalog/list-2", "predicted_relation": "UNKNOWN", "relation_confidence": 0.62, "positive_reasons": ["anchor text contains '下一页'"], "penalties": ["page type is UNKNOWN, so pagination kind cannot be assigned"]}`

| Anchor text | Target URL | Predicted relation | Confidence | Positive reasons | Penalties |
|---|---|---|---:|---|---|
| 下一页 | https://synthetic.invalid/catalog/list-2 | UNKNOWN | 0.62 | ["anchor text contains '下一页'"] | ["page type is UNKNOWN, so pagination kind cannot be assigned"] |

### syn_catalog_pagination / catalog_2

- Expected relation/pages: `{"type": "PREVIOUS_CATALOG_PAGE", "target_page_id": "catalog_1", "target_url": "https://synthetic.invalid/catalog/list-1", "evidence": "previous page link"}`
- Parser selection/pages: `null`

| Anchor text | Target URL | Predicted relation | Confidence | Positive reasons | Penalties |
|---|---|---|---:|---|---|

### syn_catalog_pagination / ch1

- Expected relation/pages: `["https://synthetic.invalid/catalog/ch1"]`
- Parser selection/pages: `["https://synthetic.invalid/catalog/list-1", "https://synthetic.invalid/catalog/list-2"]`

| Anchor text | Target URL | Predicted relation | Confidence | Positive reasons | Penalties |
|---|---|---|---:|---|---|

### syn_content_pagination / ch2

- Expected relation/pages: `["https://synthetic.invalid/pagination/ch2"]`
- Parser selection/pages: `["https://synthetic.invalid/pagination/ch1-2"]`

| Anchor text | Target URL | Predicted relation | Confidence | Positive reasons | Penalties |
|---|---|---|---:|---|---|

## Uncovered structure types

- `p_paragraphs` (CN_STATIC_CONTENT): 需要真实快照；候选站点不等于已覆盖
- `br_paragraphs` (CN_STATIC_CONTENT): 尚无本地已确认真实来源；可先自制最小 HTML
- `table_layout` (CN_STATIC_CONTENT): 补充中文旧式 table 布局；20站名单未保证覆盖
- `gbk_gb2312_gb18030` (ENCODING): 必须保留解码前字节；老站身份不是编码证据
- `encoding_conflict` (ENCODING): 先用自制字节样本构造 header/meta 冲突，另补真实案例
- `content_pagination` (CN_STATIC_CONTENT): 需要同一章至少两页和下一章；不能从章节标题的上/下推定网页分页
- `catalog_pagination` (CN_STATIC_CONTENT): 需要至少两个目录页及重叠边界；尚未采集
- `catalog_descending` (CN_STATIC_CONTENT): 候选目标，需以具体快照及导航证据确认
- `volume_number_reset` (CN_STATIC_CONTENT): 分卷文本已检索到；真实 DOM 和章节阅读序需本地标注
- `random_urls` (CN_STATIC_CONTENT): 先构造可复现样例；需补真实非连续 URL 页面链
- `no_catalog` (CN_STATIC_CONTENT): 记录明确 next/previous 链；没有链接不得编造整本顺序
- `comments_ads` (CN_STATIC_CONTENT): 候选干扰场景；保留真实段落结构
- `traditional_simplified` (CN_STATIC_CONTENT): 同模板繁简样本不能拆到开发集和最终测试集
- `single_file_fragment_chapters` (CN_STATIC_CONTENT): 按具体作品确认；保留章节锚点身份
- `restricted_pages` (CN_ACCESS_STATE): 采集当次实际提示；不由站点名称强行打标签
- `anti_bot` (CN_ACCESS_STATE): 当前仅有用户日志，还缺对应 HTTP 响应体
- `dynamic_dom` (CN_DYNAMIC_INPUT): 必须有原始响应/渲染 DOM 对照；不能用工具空输出断言 SPA
- `shift_jis` (CROSS_LANGUAGE): 文件有编码声明；编码正确性仍以字节和人工核对为准
- `non_html_reader` (NON_HTML_NEGATIVE): BookReader 文档不是实际 fixture

## Next three priority problem classes

1. **正文保留、噪声与章节内分页边界** — 12 failure records. 优先检查跨页关系和正文边界是否可由通用证据区分。
2. **目录发现、分组、方向与目录分页** — 7 failure records. 先用候选组诊断确认通用结构性缺口；不得加入 host/class/id 特例。
3. **访问页安全分类与元数据抑制** — 5 failure records. 安全失败会产生伪正文或伪书名，应在通用特征层处理。

## Guardrails and limits

- expected.json was treated as human ground truth and was not modified.
- Inference completed before the evaluator opened expected.json.
- No live network access was used.
- No parser weights or core recognition algorithms were changed.
- Synthetic, real_fixture, challenge, and dynamic results remain separate.
- Only project-authored synthetic cases were executed.
- No real website support or whole-book completeness is claimed.
- BROWSER_DOM and real HTTP capture groups currently have zero eligible cases.
- The repository has no dependency lock file; dependency_lock_hash is null and pyproject.toml is recorded separately.
