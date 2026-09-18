# baseline_v0

- Run status: `COMPLETED_WITH_FAILURES`
- Run id: `offline-20260917-100826`
- Network allowed: `false`
- Code commit: `d4493d997be747615aa5a3dc361c06dc8e2ee3bc`
- Code dirty: `True`
- Dataset hash: `88a463c5831dbd0b198fea6612d96934b9647c1199302ae0b6134428400bc5ed`

## Dataset counts

- synthetic_cases: `7`
- real_fixture_cases: `0`
- challenge_cases: `1`
- dynamic_cases: `0`
- source_provenance: `{'synthetic': 8}`

## Overall metrics

| Metric | Success/numerator | Denominator | Value | Samples |
|---|---:|---:|---:|---:|
| `access_status_accuracy` | 22 | 23 | 0.956522 | 23 |
| `body_noise_exclusion` | 2 | 3 | 0.666667 | 3 |
| `catalog_direction_accuracy` | 0 | 3 | 0.000000 | 3 |
| `catalog_precision` | 8 | 8 | 1.000000 | 3 |
| `catalog_recall` | 8 | 15 | 0.533333 | 3 |
| `content_precision_chars` | 6262 | 7555 | 0.828855 | 20 |
| `content_retained_chars` | 6262 | 7078 | 0.884713 | 20 |
| `content_status_accuracy` | 16 | 18 | 0.888889 | 18 |
| `logical_chapter_presence` | 4 | 9 | 0.444444 | 9 |
| `metadata_suppression` | 0 | 2 | 0.000000 | 2 |
| `navigation_accuracy` | 2 | 2 | 1.000000 | 2 |
| `page_type_accuracy` | 17 | 23 | 0.739130 | 23 |
| `pagination_merge_accuracy` | 2 | 4 | 0.500000 | 4 |
| `pagination_relation_accuracy` | 1 | 3 | 0.333333 | 3 |
| `partial_failure_reported` | 1 | 1 | 1.000000 | 1 |
| `reading_chain_exact` | 1 | 3 | 0.333333 | 3 |
| `unsafe_body_rejection` | 5 | 5 | 1.000000 | 5 |

## Results by sample type

### synthetic

Case count: `7`

| Metric | Success/numerator | Denominator | Value | Samples |
|---|---:|---:|---:|---:|
| `access_status_accuracy` | 21 | 21 | 1.000000 | 21 |
| `body_noise_exclusion` | 0 | 1 | 0.000000 | 1 |
| `catalog_direction_accuracy` | 0 | 3 | 0.000000 | 3 |
| `catalog_precision` | 8 | 8 | 1.000000 | 3 |
| `catalog_recall` | 8 | 15 | 0.533333 | 3 |
| `content_precision_chars` | 6262 | 7555 | 0.828855 | 20 |
| `content_retained_chars` | 6262 | 7078 | 0.884713 | 20 |
| `content_status_accuracy` | 15 | 16 | 0.937500 | 16 |
| `logical_chapter_presence` | 4 | 9 | 0.444444 | 9 |
| `navigation_accuracy` | 2 | 2 | 1.000000 | 2 |
| `page_type_accuracy` | 15 | 21 | 0.714286 | 21 |
| `pagination_merge_accuracy` | 2 | 4 | 0.500000 | 4 |
| `pagination_relation_accuracy` | 1 | 3 | 0.333333 | 3 |
| `partial_failure_reported` | 1 | 1 | 1.000000 | 1 |
| `reading_chain_exact` | 1 | 3 | 0.333333 | 3 |
| `unsafe_body_rejection` | 3 | 3 | 1.000000 | 3 |

### real_fixture

Case count: `0`

| Metric | Success/numerator | Denominator | Value | Samples |
|---|---:|---:|---:|---:|
| — | 0 | 0 | N/A | 0 |

### challenge

Case count: `1`

| Metric | Success/numerator | Denominator | Value | Samples |
|---|---:|---:|---:|---:|
| `access_status_accuracy` | 1 | 2 | 0.500000 | 2 |
| `body_noise_exclusion` | 2 | 2 | 1.000000 | 2 |
| `content_status_accuracy` | 1 | 2 | 0.500000 | 2 |
| `metadata_suppression` | 0 | 2 | 0.000000 | 2 |
| `page_type_accuracy` | 2 | 2 | 1.000000 | 2 |
| `unsafe_body_rejection` | 2 | 2 | 1.000000 | 2 |

### dynamic

Case count: `0`

| Metric | Success/numerator | Denominator | Value | Samples |
|---|---:|---:|---:|---:|
| — | 0 | 0 | N/A | 0 |

## Baseline policy

This is the frozen comparison point for later algorithm changes. A zero denominator is N/A, not 100%. Categories are not merged into one success rate.
