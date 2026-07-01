# Multi-Source Candidate Data Transformer

A Python CLI tool that ingests candidate data from multiple disagreeing sources and produces one clean, canonical, confidence-scored, fully-traceable candidate profile per person, with a runtime-configurable output projection.

**Core principles:** Determinism, explainability, and graceful degradation over feature breadth.

## Key Features

- **Multi-Source Ingestion**: Unifies structured (CSV, ATS JSON) and unstructured (GitHub API, Recruiter Notes) data.
- **Identity Resolution**: Clusters records across sources using email matching and fuzzy name+company fallbacks.
- **Confidence Scoring**: Intelligently scores merged data based on source reliability, extraction method, and cross-source agreement.
- **Dynamic Projection**: Shapes the final JSON output at runtime using a configurable projection schema.
- **Explainability**: Generates a detailed JSON decision log tracing exactly *why* a specific field value won, which sources agreed, and what values lost.
- **Quality Dashboard**: Computes batch-level metrics (field fill rates, confidence distributions, conflict stats).
- **Interactive HTML Report**: Generates a completely self-contained, offline HTML report with charts, a candidate explorer, and interactive decision traces.

## Quick Start

### Installation

```bash
# Clone the repo
cd Multi-Source-Candidate-Data-Transformer

# Install in development mode with test dependencies
pip install -e ".[dev]"
```

### Run with HTML Report (Recommended)

To generate the projected JSON profiles **along with** the interactive HTML report, decision log, and quality dashboard, use the `--report` flag:

```bash
python -m transformer run \
  --csv samples/recruiters.csv \
  --ats samples/ats_export.json \
  --notes "samples/notes/*.txt" \
  --config configs/default.json \
  --out out/profiles.json \
  --report
```

This command produces four artifacts in the `out/` directory:
1. `profiles.json` (The final transformed candidate data)
2. `decision_log.json` (Per-candidate decision traces)
3. `quality_dashboard.json` (Batch-level metrics)
4. `report.html` (Interactive dashboard and explorer)

> [!TIP]
> Open `out/report.html` in any web browser. It is fully self-contained and runs offline with zero dependencies!

### Run with custom config (subset of fields, renamed, no provenance)

```bash
python -m transformer run \
  --csv samples/recruiters.csv \
  --ats samples/ats_export.json \
  --notes "samples/notes/*.txt" \
  --config configs/custom_example.json \
  --out out/profiles_custom.json
```

### Run with GitHub sources (requires internet)

```bash
python -m transformer run \
  --csv samples/recruiters.csv \
  --ats samples/ats_export.json \
  --github-users samples/github_usernames.txt \
  --notes "samples/notes/*.txt" \
  --out out/profiles_full.json
```

### Run tests

```bash
pytest -v
```

## Architecture

The pipeline is implemented as distinct, testable modules:

```
Ingest & Sniff → Adapt → Normalize → Resolve Identity → Merge & Score → Assemble → Project → Validate
```

| Stage | Module | Responsibility |
|-------|--------|---------------|
| Ingest & Sniff | `ingest.py` | Detect source types, wrap as `SourceDocument` with SHA-256 hash |
| Adapt | `adapters/*.py` | Extract `FieldObservation` objects from each source |
| Normalize | `normalize.py` | Phone → E.164, date → YYYY-MM, country → ISO-3166, skill → canonical |
| Resolve Identity | `identity.py` | Cluster observations into per-candidate groups |
| Merge & Score | `merge.py` | Resolve disagreements, compute confidence scores |
| Assemble | `assemble.py` | Build canonical `CandidateProfile` model |
| Project | `project.py` | Apply output projection config (field subset, renames) |
| Validate | `validate.py` | Validate projected output, apply `on_missing` behavior |
| Explain | `explain.py` | Trace merge decisions to produce the Decision Log |
| Dashboard | `dashboard.py`| Calculate batch-level quality metrics |
| Report | `report.py` | Generate the self-contained HTML artifact |

## Supported Sources

| Source | Type | Adapter | Method |
|--------|------|---------|--------|
| Recruiter CSV | Structured | `csv_adapter.py` | `direct` |
| ATS JSON | Structured | `ats_adapter.py` | `alias_map` |
| GitHub API | Unstructured | `github_adapter.py` | `api` |
| Recruiter Notes | Unstructured | `notes_adapter.py` | `regex` / `heuristic` |

## Confidence Formula

The confidence score quantifies how trustworthy each field value is, based on source reliability, extraction method, and cross-source agreement.

### Per-Field Confidence

```
field_confidence = min(base_tier_weight × method_certainty × agreement_boost, 1.0)
```

> Capped at **1.0** — confidence is a normalized certainty score. The agreement boost rewards cross-source confirmation up to absolute certainty but cannot exceed it.

Where:

- **`base_tier_weight`** — how reliable is the source?
  - ATS JSON: **0.9** (structured, from the applicant tracking system)
  - GitHub API: **0.85** (structured, from a live API)
  - Recruiter CSV: **0.7** (structured but manually curated)
  - Recruiter Notes: **0.4** (unstructured free text)

- **`method_certainty`** — how was the value extracted?
  - `direct`: **1.0** (explicit column mapping)
  - `alias_map`: **0.95** (field name translation)
  - `api`: **0.9** (live API response)
  - `regex`: **0.7** (pattern matching)
  - `heuristic`: **0.5** (fuzzy/contextual extraction)

- **`agreement_boost`** — do multiple sources agree?
  - `1.0 + 0.1 × (num_agreeing_sources − 1)`, **capped at 1.3**
  - 1 source agrees (just the winner): boost = 1.0 (no change)
  - 2 sources agree: boost = 1.1
  - 3 sources agree: boost = 1.2
  - 4+ sources agree: boost = 1.3 (maximum)

### Overall Confidence

```
overall_confidence = weighted mean of all populated field confidences
```

Only fields with non-null values contribute to the overall score.

## Identity Resolution Policy

Observations from different sources are clustered into per-candidate groups using a two-tier strategy:

### Strong Key: Email Match (Primary)
If two observations share the same email address (case-insensitive), they are clustered together. This is the most reliable signal.

### Weak Key: Fuzzy Name + Company Match (Fallback)
When no email is available, the system falls back to fuzzy matching using:
- Normalized name comparison via `rapidfuzz` token-sort ratio
- A conservative threshold of ≥ 85% similarity

**Conservative by design:** The system prefers leaving two records unmerged over false-merging two different people into one profile.

## Projection Config

The output shape is fully configurable via a JSON config file:

```json
{
  "fields": [
    {"path": "id", "from": "candidate_id", "type": "string", "required": true},
    {"path": "name", "from": "full_name", "type": "string", "required": true},
    {"path": "contact_emails", "from": "emails", "type": "array", "required": false}
  ],
  "include_confidence": true,
  "include_provenance": false,
  "on_missing": "omit"
}
```

## Explicitly Descoped

| Feature | Reason |
|---------|--------|
| **LinkedIn live scraping** | Violates LinkedIn Terms of Service. Out of scope. |
| **Resume / PDF parsing** | Requires complex document processing libraries (PyPDF, etc.). Out of scope for this version. |
| **LLM-based extraction** | Violates the determinism requirement. Same input must produce byte-identical output. No randomness, no model inference. |

## Project Structure

```
├── configs/             # Configuration files
├── samples/             # Sample input data
├── tests/               # Pytest test suite
├── transformer/         # Main package
│   ├── __init__.py
│   ├── __main__.py          # Entry point
│   ├── cli.py               # Click CLI (handles --report)
│   ├── models.py            # SourceDocument, FieldObservation, ProjectionConfig
│   ├── schema.py            # CandidateProfile (canonical model)
│   ├── ingest.py            # Source detection & wrapping
│   ├── normalize.py         # Phone, date, country, skill normalization
│   ├── identity.py          # Identity resolution / clustering
│   ├── merge.py             # Merge & confidence scoring
│   ├── assemble.py          # Build CandidateProfile
│   ├── project.py           # Output projection
│   ├── validate.py          # Output validation
│   ├── dashboard.py         # Quality dashboard metrics compilation
│   ├── explain.py           # Decision log generation
│   ├── report.py            # Self-contained HTML report generation
│   └── adapters/
│       ├── __init__.py
│       ├── ats_adapter.py
│       ├── base.py
│       ├── csv_adapter.py
│       ├── github_adapter.py
│       └── notes_adapter.py
├── pyproject.toml       # Project metadata and dependencies
└── README.md
```

