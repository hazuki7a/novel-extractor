# Offline Benchmark implementation status

Status date: 2026-09-17

This file distinguishes implemented evidence from the 20-source collection
plan in `benchmark_sites.json`.  It does not claim support for any real site.

## D01 — Manifest and annotation contract

- The 20-source manifest remains intact: 15 Chinese primary candidates and 5
  special candidates.
- Real captured HTML fixtures: **0**. Reviewed real cases: **0**.
- `case.json` and `expected.json` are separate. Only `READY` cases execute;
  other annotation states are reported as deferred.
- `tools/check_cases.py` checks input existence, SHA-256, exact URL mappings,
  HTTP metadata, page labels, logical chapter references and rights status.
- Files under `templates/` are not discovered as executable cases.

## D02 — Offline input adapter

- `offline_contract.py` supports `HTTP_BYTES`, `BROWSER_DOM` and
  `SYNTHETIC_HTML`.
- `HTTP_BYTES` uses the project's `decode_page_bytes` path with saved HTTP
  metadata. Browser DOM and authored HTML are treated as saved UTF-8 text and
  do not claim an original server encoding.
- URL matching is exact. Query strings and fragments are preserved; two
  fragment URLs may reuse one saved document without losing chapter identity.
- Missing URLs raise an out-of-scope fixture error. There is no live-network
  fallback.

## D03 — Inference and evaluator isolation

- `offline_runner.py` first creates predictions using only `case.json` and
  saved inputs.
- `expected.json` is opened only after inference, inside the evaluator.
- Site IDs, scenario tags, gold selectors and expected content are not passed
  to Analyzer, Crawler, Cleaner or Exporter code.
- Predictions retain module diagnostics in the report.

## D04 — Metrics and error layers

- Reports contain numerator, denominator, sample count and abstention count.
- Suites with no eligible cases use `metrics: null` (N/A), not 100%.
- Results are retained per case, per suite, per site and as page-weighted
  aggregates.
- Failures use the unified taxonomy in `failure_diagnostics.py`; every failure
  includes case/sample type, expected and actual results, confidence, category
  and relevant diagnostics.
- Reports include the page-type confusion matrix, all catalog group candidates
  for catalog failures, and explicit pagination relation candidates.
- Reports record commit, dirty state, dataset/configuration hashes, offline
  mode and cold-cache mode. There is no dependency lock file, so its field is
  explicitly null; `pyproject.toml` has a separate hash.

## D05 — Synthetic framework baseline

Eight project-authored cases cover paragraph and `<br>` bodies, comment
competition, a true short prologue, 403 and 200 challenge pages, GB18030 bytes,
HTTP/meta encoding conflict, chapter pagination, catalog pagination with an
overlap, table layout, descending volume blocks with numbering reset,
same-document fragments, and partial failure with a missing fixture.

They have synthetic provenance. Exclusive reporting keeps seven ordinary
`synthetic` cases and one `challenge` case separate; real_fixture and dynamic
remain empty/N/A.

The frozen `synthetic-contract-v1` baseline executed 8/8 valid cases entirely
offline. Every case currently has at least one strict assertion failure; this
is a real rule baseline, not a framework validation failure. Selected metrics:

| Metric | Numerator / denominator | Value |
|---|---:|---:|
| Page type accuracy | 17 / 23 | 0.739130 |
| Content status accuracy | 16 / 18 | 0.888889 |
| Access status accuracy | 22 / 23 | 0.956522 |
| Unsafe-body rejection | 5 / 5 | 1.000000 |
| Body-noise exclusion | 2 / 3 | 0.666667 |
| Content retained characters | 6262 / 7078 | 0.884713 |
| Content precision characters | 6262 / 7555 | 0.828855 |
| Catalog recall | 8 / 15 | 0.533333 |
| Catalog precision | 8 / 8 | 1.000000 |
| Pagination merge accuracy | 2 / 4 | 0.500000 |
| Pagination relation accuracy | 1 / 3 | 0.333333 |
| Navigation accuracy | 2 / 2 | 1.000000 |
| Partial failure reported | 1 / 1 | 1.000000 |

One normal-content sample was rejected and is reported as an abstention. The
main observed gaps are challenge-page metadata suppression, 403 challenge
classification, long comment competition, HTTP/meta encoding conflicts,
short-prologue handling, catalog pagination and logical chapter merging.

## D06 — Real captures

Not started. The guide requires the user to approve a specific work, page
range and acquisition method first. No candidate site was accessed by this
benchmark work.

## D07 — Frozen version and failure analysis

- Dataset version: `synthetic-contract-v1`
- Frozen comparison point: `reports/baseline_v0.json` and
  `reports/baseline_v0.md`
- Failure analysis: `reports/failure_analysis.json` and
  `reports/failure_analysis.md`
- The older `reports/synthetic-contract-v1/baseline.json` remains historical;
  later algorithm changes compare against `baseline_v0`.
- Real-site coverage remains pending and must not be inferred from the
  synthetic results.
