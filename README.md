# RidePulse AI 🌐🚴

**Global cycling Voice-of-Customer radar — turning scattered, multilingual user complaints into traceable, rankable, actionable product opportunities.**

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-203%20passed-brightgreen)](tests/)
[![Models](https://img.shields.io/badge/LLM-GPT--6%20family-412991)](https://platform.openai.com/docs/models)
[![Pipeline](https://img.shields.io/badge/CI-weekly%20automation-success)](.github/workflows/weekly-pipeline.yml)

---

## 📌 Status: the full pipeline runs end-to-end

Verified on a real run (`RUN-20260813-211103`, 2026-08-13). This is not a concept demo — every artifact is committed to the repo.

| Stage | Result |
|---|---|
| Input | 37 real user reviews (DATASET v1, frozen 2026-08-13; 12 platforms / 24 source pages; 5 Chinese / 32 English) |
| Classification | 37/37 first-pass LLM classification, JSON-Schema-constrained output |
| Independent review | 37/37 second-pass review by a **different model**, blind to the first pass; 21 fully agreed, 16 had field-level conflicts |
| Human adjudication | All 12 conflicts adjudicated by hand, each with a written rationale (`adjudication_record.csv`) |
| Semantic clustering | 21 need clusters, covering every record, merged across platforms and languages |
| Evidence cards | 21 cards (`EC-2026-0001` … `EC-2026-0021`) with problem statement, root-cause hypothesis, recommended action, evidence URLs |
| Evaluation | Against a two-annotator gold set (18/20 paired): theme_primary accuracy 88.9% / macro-F1 75.4% |
| Tests | **203 automated tests passing** |
| Model layer | OpenAI **GPT-6 family**, three tiers: `gpt-6-luna` classify / `gpt-6-sol` review / `gpt-6-astra` evidence cards |
| Continuous operation | Weekly GitHub Actions pipeline: collect → classify → review → cluster → score → cards, on schedule and on push; conflicts auto-open an issue, failures auto-alert |

Full results, metric definitions and known limitations: [`03_system_results_m4.md`](03_system_results_m4.md) and `output/RUN-20260813-211103/`.

---

## 📖 Why this exists

Magene (迈金科技) is a Chinese cycling-tech company whose brands — Magene, Onelap, EXAR — cover GPS bike computers, power meters, smart trainers and sensors, sold in 100+ countries.

Their user feedback is scattered across App Store, Google Play, forums, social media and support tickets: high volume, many languages, deeply fragmented. The company does not lack data. What it lacks is the ability to turn fragmented complaints from *outcome language* ("sync broke again") into *root-cause hypotheses* backed by traceable evidence that a product team can actually act on.

This is not a theoretical problem. In 2025 a Garmin cache-file defect bricked thousands of Edge devices; in 2024 Strava's API restrictions broke a generation of third-party integrations. Even category leaders pay for failing to hear their users in time. RidePulse AI targets exactly that gap.

---

## 🏗️ Architecture (implemented)

```
collect → normalize → classify → independent review → human adjudication → cluster → priority scoring → evidence cards
```

| Stage | Status | What it does |
|---|---|---|
| Collect | ✅ | Public, compliant sources (App Store RSS, forums, media). Keeps URL / timestamp / platform / language for every record |
| Normalize | ✅ | Field validation, PII redaction, translation, source ledger; invalid records rejected |
| Classify | ✅ | `gpt-6-luna` first pass: sentiment, theme, scenario, severity, 5-way need type, JTBD, purchase impact; low-confidence fields flagged for review |
| Independent review | ✅ | `gpt-6-sol` re-judges every record **without seeing the first pass**; field-level conflict detection; conflicts go to a human queue — the system never auto-asserts a conclusion |
| Human adjudication | ✅ | Every conflict decided individually and recorded; fully auditable |
| Clustering | ✅ | Multilingual embeddings (default `text-embedding-3-large`, 3072-d; local MiniLM fallback) + theme bucketing + deterministic agglomerative clustering on cosine distance |
| Priority scoring | ✅ | Six weighted dimensions in pure code (evidence 15 + reproducibility 20 + frequency 15 + severity 20 + actionability 15 + purchase impact 15). **The model never scores.** |
| Evidence cards | ✅ | `gpt-6-astra` generates, code validates. Citations to original ID / URL / timestamp are mandatory; a card that cannot be traced back is voided automatically |

### Design principles

- **Evidence chain over vibes.** Every insight must cite an original record ID, URL and timestamp. Unresolvable citations void the card.
- **Models only where models belong.** Deterministic code handles what code can decide; statistics handle clustering; the scoring formula is 100% code.
- **Two models plus a human.** Disagreement between the first pass and the review is never silently resolved — it goes to a person.
- **Hypotheses, not verdicts.** The model proposes root causes; a product manager confirms them.
- **Tier by task, not by flagship.** Cheap tier for high-volume classification, general tier where independence matters, flagship tier where long-context synthesis decides quality.
- **Endpoint-agnostic.** All three model names and the base URL are environment variables; any OpenAI-compatible endpoint works by changing config.

---

## 🤖 Model integration (GPT-6 family)

Classification, review and card generation all call OpenAI GPT-6 — but deliberately **not at the same tier**. Cost and capability are matched to the task:

> **Migration note:** the weekly pipeline originally ran on a domestic model (MiniMax M3). The full pipeline worked, but in practice it fell short of the GPT-6 family on cross-lingual semantic boundaries and structured-output stability — with adaptive thinking on by default, a single classification took 10.5 s (2.2 s with it off), and output carried a `<think>` prefix that had to be stripped. The default models were therefore moved to GPT-6 across the board.

| Stage | Default model | Reasoning effort | Rationale |
|---|---|---|---|
| First-pass classification | `gpt-6-luna` | `low` | One call per record, fixed output shape, dozens to hundreds of calls per run — volume matters, per-call reasoning depth does not |
| Independent review | `gpt-6-sol` | `medium` | The point of review is an independent second opinion, so it must be a different model; it also has to catch the first pass's borderline calls |
| Evidence cards | `gpt-6-astra` | `high` | Each card synthesizes several cross-lingual evidence items under strict citation constraints — the 1.05M-token context and stronger synthesis directly determine card quality |

**GPT-6 parameter handling** is built in, so callers never think about it. Since GPT-6, the sampling parameters `temperature` / `top_p` are gone — sending them is an error, not a silent downgrade. Reasoning depth moved to `reasoning_effort`, whose legal values are `low` / `medium` / `high` / `xhigh` / `max`; `none` and `minimal` no longer exist. The client resolves capabilities from the model name: it omits sampling parameters for GPT-6, clamps unsupported effort levels to `low`, and — if the server rejects a parameter — drops that parameter and retries once. Swapping models cannot take the pipeline down.

Every run's `run_report.md` and `usage_log.json` record the requested model, the model that actually answered, the reasoning effort and the reasoning-token count. If the response model does not match the request (an endpoint silently remapping model names), that is logged as a separate warning.

Embeddings default to `text-embedding-3-large` (3072-d) on the same endpoint; the CI weekly pipeline uses a local multilingual model so it costs no API quota.

---

## 🧪 Quick start

```bash
# Install
pip install -e .

# Environment (.env, never committed; see .env.example)
#   OPENAI_API_KEY=sk-...            # the only required value (LLM_API_KEY also accepted)
#   LLM_PRIMARY_MODEL=gpt-6-luna     # first-pass classification
#   LLM_REVIEW_MODEL=gpt-6-sol       # independent review (must differ from the classifier)
#   LLM_EVIDENCE_MODEL=gpt-6-astra   # evidence cards
#   Omit the three model variables to use the defaults above; LLM_BASE_URL defaults to https://api.openai.com/v1

# Verify connectivity first (--live sends one minimal request and checks the responding model name)
python -m ridepulse.cli check-llm --live

# Run the full pipeline (requires an LLM; use --offline for a keyless demo baseline)
python -m ridepulse.cli run --input data/verified/feedback_verified.csv

# Reproduce the evaluation against the gold set
python -m ridepulse.cli evaluate --run-id RUN-20260813-211103 --gold data/verified/annotation_gold.csv

# Streamlit workbench (5 pages: evidence cards / run overview / clusters / evaluation / human review)
streamlit run app.py

# Full test suite
pytest   # 203 passed
```

> The official run's artifacts are committed: `output/RUN-20260813-211103/` — model outputs, review outputs, human-final outputs, clusters, priority scores, evidence cards, metrics, error cases and charts.

---

## 📁 Repository layout

```
ridepulse-ai/
├── README.md                              # This file
├── SECURITY.md                            # Threat model and known gaps
├── 03_system_results_m4.md                # Delivery report (config / stats / evaluation / limits)
├── DATA_CONTRACT_v1.md / .json            # Label taxonomy and field-level data contract
├── src/ridepulse/                         # Core package
│   ├── pipeline.py                        # End-to-end orchestration
│   ├── classify.py / review.py            # Dual-model classification and independent review
│   ├── clustering.py / embedding.py       # Theme-bucketed clustering and multilingual embeddings
│   ├── scoring.py                         # Six-dimension priority scoring (pure code)
│   ├── evidence.py                        # Evidence-card generation and validation
│   ├── evaluation.py                      # Metrics (Accuracy / F1 / Kappa)
│   ├── dedup.py / normalize.py / ingest.py / validation.py
│   ├── database.py / delivery.py / feishu_client.py
│   ├── collectors/                        # Public connectors (App Store RSS, etc.)
│   ├── llm_client.py / config.py / models.py
│   └── cli.py                             # validate / collect / run / resume / evaluate / check-llm / push-feishu
├── app.py                                 # Streamlit workbench (5 pages)
├── data/
│   ├── classification_schema.json         # Classification JSON Schema v1.0
│   ├── verified/                          # DATASET v1 (frozen)
│   │   ├── feedback_verified.csv          # 37 official records (redacted)
│   │   ├── source_ledger_verified.csv     # Source ledger (resolvable URLs)
│   │   ├── annotation_gold.csv            # Two-annotator gold set
│   │   ├── DATASET_V1_FROZEN.md
│   │   ├── dataset_summary.md
│   │   └── data_quality_report.md
│   └── auto/                              # Weekly pipeline data area (pool / cursors / human decisions)
├── prompts/
│   ├── classify_v1.md
│   └── review_v1.md
├── agents/                                # Prompt templates (understander / reviewer / governor)
├── docs/                                  # Problem analysis, solution design, references
├── scripts/                               # Weekly orchestration / evaluation / adjudication backfill / PDF / Excel
├── .github/workflows/weekly-pipeline.yml  # Weekly automation (schedule + push)
├── tests/                                 # 203 tests
├── output/RUN-20260813-211103/            # Full artifacts of the official run
└── team_outputs/liang/                    # Business review deliverables
```

---

## 📊 Evaluation and known limitations (disclosed honestly)

Against a 20-record, two-annotator gold set (18/20 paired; `F0030`/`F0031` differ by dataset version):

| Metric | Value |
|---|---|
| theme_primary accuracy / macro-F1 | 88.9% / 75.4% |
| need_type accuracy | 61.1% |
| severity accuracy | 50.0% (weighted Kappa 0.375) |
| purchase_impact accuracy | 5.6% (label-definition mismatch — see below) |
| Human review rate | 55.6% (low-confidence and conflicting fields routed to humans) |

- **Severity is systematically over-estimated by one level.** All 9 errors are one level higher than gold; none are lower. This is now encoded in the human review rule: reviewers are asked to consider dropping severity by one level.
- **purchase_impact discrepancy is a labelling problem, not a model problem.** Gold only contains `influence` / `blocker`; the model also emits `unknown`. That is a definition gap that data governance needs to close.
- **A 55.6% review rate means the gate is working.** Dual-model review plus human adjudication is designed to escalate whenever it is uncertain; a low review rate would not be a better number.

---

## 👥 Team

| Role | Name | Background | Focus |
|---|---|---|---|
| Lead / system integration | Zhang Zhongbao | Software Engineering | AI architecture, mathematical modelling, software delivery |
| Source verification & business review | Li Ang | Business Administration | Cyclist perspective, product commercialization, competitor research |
| Data governance & evaluation | Feng Jingqin | Geographic Information Science | GIS, Python data analysis, visualization |

The three backgrounds form a loop: industry judgement → data validation → product execution.

---

## 📚 References

- [`docs/01_problem_analysis.md`](docs/01_problem_analysis.md) — problem framing and industry analysis
- [`docs/02_solution_design.md`](docs/02_solution_design.md) — technical design
- [`docs/04_references.txt`](docs/04_references.txt) — full reference list (PeopleForBikes / road.cc / The Verge / BGE-M3 / OpenAI GPT-6 docs)
- Full source ledger (S01–S20, with excerpts and access dates): `data/verified/source_ledger_verified.csv`

---

## 📄 License

MIT. Raw sensitive data (`data/raw/`) and secrets (`.env`) are never committed; DATASET v1 is redacted and shipped with the repo.

> ⚠️ **Security status:** this project has not undergone a formal security review. Its core data flow is *untrusted public review text → LLM → downstream decisions*, which makes prompt injection a real attack surface. See [`SECURITY.md`](SECURITY.md) for the threat model and the scope we want reviewed.

---

*RidePulse AI — so that every cycling user's voice can be heard, traced and acted on.*
