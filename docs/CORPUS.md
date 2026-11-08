# Corpus

Source: public FAST-NUCES documents. The reviewed download snapshot contains **9 documents:
7 PDFs with 279 physical pages, plus 2 HTML pages**. HTML pages are not counted toward
the 40-page minimum. URLs, byte sizes and hashes are in `corpus/MANIFEST.md`; selected
versions and download hash pins are in `corpus/sources.yaml`.
The source snapshot was downloaded on 2026-11-04 UTC and its review was completed on
2026-11-05 PKT. Measured results are recorded in `docs/evidence/corpus-audit.json`.

| # | Required property | Document(s) that provide it | Evidence or notes |
| --- | --- | --- | --- |
| 1 | At least 6 documents, 40 pages | All 9 sources below; 279 PDF pages | Counted with pypdf; all downloaded successfully and passed hash verification. |
| 2 | Two versions of one policy | Undergraduate Academic Rules, revised August 2023, and June 2026 edition | Older cover/revision page checked with OCR; newer title page identifies June 2026. The selected 2023 edition has `superseded: true`; 2026 has `false`. This does not assume every clause changed. |
| 3 | Scanned, image-only PDF | Faculty Entrepreneurship / Technical Start-ups Policy, May 2022 | 8 pages, zero extracted text on every page, and zero font rows from `pdffonts`. The first page was rendered and visually checked as a scan; diagnostic OCR recovers readable policy text. |
| 4 | A table with real information | 2026 Academic Rules, PDF page 12, section 2.3 | Visually checked the grade/points table, with two Grade/Points column pairs. Preserve each grade-to-points relationship when extracting. Annual reports and the fee page supply additional tables. |
| 5 | Long definitions | Student Handbook 2026, PDF pages 12–15 | Definitions and lettered subclauses for academic misconduct and harassment cross paragraph/page boundaries. PDF page 14 was visually reviewed; keep the heading and associated subclauses together. |
| 6 | A deliberately absent topic | Current Islamabad campus shuttle stops and departure timetable | General transport/hostel references exist, so broad transport or hostel questions are not suitable abstention cases. Route notices and the transport/hostel prospectus section are excluded. The specific current timetable is outside the selected source scope; source-review checks are recorded below. |
| 7 | Exact-term content | 2026 Academic Rules sections 2.3 and 5.4; prospectus rules; fee and grading pages | Clause IDs, grade values, CGPA thresholds and fees are present. Clause numbers differ between the prospectus summary and the full handbook, so references must include the source. |

## Selected documents

| Local source | Version | PDF pages | Pages with no extracted text | Superseded |
| --- | --- | ---: | ---: | --- |
| `undergraduate-academic-rules-aug-2023.pdf` | 2023-08 | 26 | 24 | yes |
| `academic-rules-handbook-jun-2026.pdf` | 2026-06 | 58 | 4 | no |
| `prospectus-2026-academic-rules-and-regulations.pdf` | 2026 | 5 | 0 | no |
| `student-handbook-jun-2026.pdf` | 2026-06 | 64 | 4 | no |
| `annual-report-2019-20.pdf` | 2019-20 | 33 | 0 | no |
| `annual-report-2023-24.pdf` | 2023-24 | 85 | 0 | no |
| `faculty-entrepreneurship-and-technical-start-ups-policy.pdf` | 2022-05 | 8 | 8 | no |
| `fee-structure-page.html` | snapshot-2026-11-04 | — | — | no |
| `grading-page.html` | snapshot-2026-11-04 | — | — | no |

Annual reports are separate historical records, not replacement editions of one policy;
the newer report does not automatically make the older year's facts superseded. HTML
versions identify a captured snapshot, not a publication date asserted by the university.
The initial fetch records its UTC date in `_index.json`.

## Acquisition and integrity

```bash
python3 corpus/fetch.py
python3 corpus/fetch.py --verify
```

Downloads run one at a time with pauses and reuse cached files. The fetcher checks cached
bytes before reuse, rejects empty responses and HTML returned at PDF URLs, prevents source
filename collisions, and checks configured SHA-256 pins before writing a new download.
Verification fails for an empty manifest, missing configured sources, missing files,
changed bytes or a manifest inconsistent with a source pin. Offline tests cover these
failure cases without contacting the university.

`--force` downloads again; it does not bypass a hash pin. If a public URL changes, review
the new document and its date before deliberately updating its pin, version and manifest.
Live HTML is particularly liable to change, so a future fresh download may correctly
refuse to match this snapshot. The repository does not include a mirror of university
files. `corpus/raw/`, extracted review text, OCR text and page previews are all ignored.

## Review and extraction implications

```bash
docker run --rm --network none \
  --mount "type=bind,source=$(pwd)/corpus,target=/corpus" \
  rahbar-indexer:dev python /corpus/audit.py
docker run --rm --network none \
  --mount "type=bind,source=$(pwd)/corpus,target=/corpus" \
  rahbar-indexer:dev python /corpus/audit.py --ocr
```

The audit records page counts, text-layer availability, font output and exact repeated
text pages in ignored `corpus/raw/audit.json`. Diagnostic OCR processes textless pages
and merges source-review text into `corpus/raw/text/*.review.txt`. These are source
inspection aids, not retriever output or the implemented production extraction stage.
Some textless pages are blank/decorative; do not describe all 40 such pages as scans.
All 40 pages were processed by diagnostic OCR: 34 produced text and 6 still produced
none. This is an extraction-availability result, not a measured OCR accuracy score.
OCR can misread clause numbers and punctuation, so golden answers must be checked against
the original rendered pages.

Use 1-based physical PDF page numbers in chunk metadata. Printed numbering differs:
the grading table on PDF page 12 is printed page 6. The older scan and the new editions
need different extraction handling. Repeated headers/footers must be removed without
stripping meaningful section headings, grade tables or definition subclauses.

The chosen absent topic is intentionally narrower than "transport". Review covered all
9 source texts, including diagnostic OCR and the HTML snapshots. Searching found no
"shuttle", "bus route" or "departure" occurrences; three "timetable" occurrences refer
to academic scheduling. The Annual Report 2023-24 transport section on PDF page 78 was
also read directly: it describes general transport availability without naming the
current Islamabad stops or their departure times. Keyword counts alone do not establish
semantic absence. Do not use a must-abstain question if later sources reveal its answer;
re-check this topic whenever the corpus is expanded.

The production pipeline and historical real-model indexing/evaluation were subsequently
completed; see PIPELINE.md for 950 default chunks and the measured quality results.
This acquisition audit establishes source coverage, not lossless OCR.
