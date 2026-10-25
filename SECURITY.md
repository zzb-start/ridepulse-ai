# Security Policy

## Status

This project has **not** undergone a formal security review. It is maintained by a single developer. This document exists to state that plainly and to enumerate the attack surface, so that a reviewer (human or automated) knows where to look.

We are actively seeking a security review of the areas listed under [Threat model](#threat-model).

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

- Open a private report via GitHub Security Advisories: `Security` tab → `Report a vulnerability`
- Or email the maintainer listed in the repository profile

We aim to acknowledge within 7 days. There is no bug bounty.

## Threat model

RidePulse AI ingests **untrusted public text**, sends it to an LLM, and feeds the LLM's structured output into downstream scoring and clustering. That data flow is the primary reason this project needs security review.

### 1. Prompt injection (highest priority)

**Surface.** Every record classified or reviewed originates from a public channel — App Store reviews, forums, media — where anyone can publish arbitrary text. That text is placed into the user message of a `chat/completions` call.

**Impact if exploited.** A crafted review could attempt to:
- force specific label values (e.g. always `severity: S5`, or a chosen `theme_primary`),
- suppress or fabricate `root_cause_hypotheses`,
- emit content that passes JSON Schema validation but is semantically manipulated,
- pollute cluster membership and therefore priority scores.

**Current mitigation.** JSON Schema validation, enum whitelists, confidence thresholds, and dual-model review with human adjudication. These catch malformed or low-confidence output. **They do not defend against semantic manipulation** — a well-formed but attacker-chosen label passes every check.

**Not yet done.** Adversarial test corpus, input sanitisation strategy, instruction/data separation, output anomaly detection, injection-specific evaluation.

### 2. Credential and log leakage

**Surface.** The process holds an OpenAI API key, a Feishu app secret, and a Bitable token, supplied via environment variables. It also writes run artifacts, logs, and a SQLite database to disk.

**Current mitigation.** `.env` is gitignored; `data/raw/` is not committed; a unit test asserts the LLM usage log never contains the API key.

**Not yet done.** Systematic review of log paths, exception tracebacks (which can embed request bodies), CI output, and the Streamlit session. No secret-scanning hook in CI.

### 3. Untrusted input parsing

**Surface.** App Store RSS (XML), external URL fetches, and CSV import.

**Not yet done.** XXE hardening review, SSRF restrictions on outbound fetches, size/recursion limits, malformed-encoding handling. Validation today is field-level only.

### 4. LLM output as a trust boundary

Model output is treated as untrusted: every field is validated against a Pydantic model, system fields (`feedback_id`, `model_name`) are injected by code rather than echoed by the model, and evidence-card citations are verified against the cluster's own record IDs — a card referencing an unknown ID is voided.

**Known gap.** Scores are computed by code from validated fields, so a manipulated *label* propagates into the score without any further check. There is no semantic sanity check on label distributions.

### 5. Dependency and supply chain

`streamlit`, `sentence-transformers`, `scikit-learn`, `pandas`, `httpx`, `pydantic` and others. No dependency audit, no hash-pinned lockfile, no automated vulnerability scanning.

### 6. CI

GitHub Actions runs on a schedule and on push, with repository write permission (`contents: write`, `issues: write`) so it can commit run artifacts and open conflict issues. Workflow files are not protected by a required-review rule.

## Out of scope

- Denial of service through sheer volume of collected reviews
- Security of the third-party platforms the data is collected from
- The LLM provider's own model safety

## What a review should produce

1. An injection test corpus and a measured baseline for how often manipulated input changes labels.
2. A concrete defence design for instruction/data separation in the classification and review prompts.
3. A secrets-handling audit covering logs, tracebacks, CI, and the Streamlit layer.
4. Hardening recommendations for RSS/XML/URL ingestion.
5. A dependency and CI permission review.
