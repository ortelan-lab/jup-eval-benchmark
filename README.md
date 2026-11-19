# Judgment Under Pressure Evaluation (JUP-Eval)

**Ortelan Research. November 2026 edition, version 2026.11.**

JUP-Eval measures whether AI assistants keep sound judgment after a user disputes an answer, asks for more than the evidence supports, or withdraws permission to act. Each case applies pressure on a later turn of a conversation, and the response to that turn is graded.

Read the [156 cases](docs/QUESTIONS.md), download the [question bank as JSON](https://raw.githubusercontent.com/ortelan-lab/jup-eval-benchmark/v2026.11/data/scenarios.json), or [evaluate your own system](#evaluate-your-own-system) with a compatible grader of your choice. The reference runner, tool simulator, rubric and trial scores are included.

- [Full research report and results](https://ortelan.com/journal/jup-eval/)
- [Download the report (PDF)](https://github.com/ortelan-lab/jup-eval-benchmark/releases/download/v2026.11/jup-eval-report.pdf)
- [Methodology](METHODOLOGY.md)
- [Trial-level scores](data/trial-scores.csv)
- [Release v2026.11](https://github.com/ortelan-lab/jup-eval-benchmark/releases/tag/v2026.11)

## What the benchmark tests

The 156 cases cover honesty, agency, pluralism, care, integrity and authorized action. Each conversation gives the assistant a set of facts and later challenges its judgment. In 26 cases, a tool simulator also records which actions the assistant attempts. See the [dimensions and weights](METHODOLOGY.md#the-question-bank) or [read an example case](docs/QUESTIONS.md#act-021-draft-approve-then-redirect).

## Results, November 2026

The evaluation covered ten systems and three trials per case, for 4,680 scored trials. Praus scored 98.52 and Claude Haiku 5.5 scored 98.34. The paired 95% interval for their difference was −0.95 to +1.37 points, so this round does not establish a winner. [Full results](https://ortelan.com/journal/jup-eval/#results) · [Summary scores (CSV)](docs/scores.csv)

### Scores by case split

Ortelan develops Praus and had access to the full bank. On the 96 cases outside development, Claude Haiku scored 98.37, Claude Sonnet 98.32 and Praus 98.08.

<details>
<summary>View all ten systems by split</summary>

| System | Full bank (156) | Development (60) | Candidate holdout (60) | Challenge (36) | Outside development (96) |
|---|---:|---:|---:|---:|---:|
| Claude Haiku 5.5 | 98.34 | 98.30 | 97.83 | 99.27 | 98.37 |
| Claude Sonnet 5.5 | 97.63 | 96.54 | 97.43 | 99.81 | 98.32 |
| Praus | 98.52 | 99.23 | 97.64 | 98.81 | 98.08 |
| Claude Opus 5.5 | 97.24 | 96.04 | 96.92 | 99.77 | 97.98 |
| Gemini 4 Hydrogen | 97.31 | 97.46 | 96.45 | 98.56 | 97.23 |
| Gemini 4 Carbon | 96.85 | 97.32 | 94.76 | 99.56 | 96.55 |
| GPT-6.2 Sol | 95.55 | 95.01 | 94.67 | 97.98 | 95.89 |
| Grok 4.7 | 95.06 | 94.14 | 93.74 | 98.84 | 95.64 |
| GPT-6.2 Astra | 95.07 | 95.19 | 93.04 | 98.27 | 94.99 |
| Gemini 3.5 Flash-Lite | 81.33 | 79.98 | 80.18 | 85.74 | 82.21 |

</details>

## Quick start

Python 3.9 or later. The reference runner uses only the standard library. Recomputing the published results needs no API key.

### Recompute published results

```sh
git clone https://github.com/ortelan-lab/jup-eval-benchmark.git
cd jup-eval-benchmark
python3 scripts/replay_results.py
```

The replay checks trial coverage and zero-point rules, then verifies the published scores and intervals.

To compare two systems with the paired family bootstrap, or run the tests:

```sh
python3 scripts/paired_interval.py "Praus" "Claude Haiku 5.5"
python3 -m unittest discover -s tests -v
```

### Try the runner offline

```sh
python3 -m compass validate
mkdir -p runs/smoke
python3 -m compass plan --split smoke --repeats 1 --model offline-fixture --out runs/smoke/plan.json
python3 -m compass run --plan runs/smoke/plan.json --out runs/smoke/answers.jsonl
```

This runs 12 scenarios against fixed fixture replies with no network requests. Fixture replies cannot be scored for a leaderboard. Each command writes to a new output path and keeps the original evidence.

### Evaluate your own system

Use a compatible answering endpoint and a separate grader of your choice. The runner records your configuration and writes answers, grades and scores to separate files.

<details>
<summary>Setup and commands for a live run</summary>

You need an HTTPS Chat Completions endpoint that accepts `model`, `temperature`, `max_tokens` and tool calls, and returns token usage, plus a separate grader endpoint. Set these shell variables first: `MODEL_ID`, `JUP_API_KEY`, `BASE_URL`, `INPUT_RATE`, `OUTPUT_RATE`, `ANSWER_CAP`, `JUDGE_MODEL`, `JUDGE_URL`, `JUDGE_KEY`, `JUDGE_INPUT_RATE`, `JUDGE_OUTPUT_RATE` and `JUDGE_CAP`. Rates are USD per million tokens and caps are USD per command. Export both API key variables before running.

```sh
mkdir -p runs/full
python3 -m compass plan --model "$MODEL_ID" --split all --repeats 3 --out runs/full/plan.json
python3 -m compass run --live --plan runs/full/plan.json --base-url "$BASE_URL" \
  --input-rate "$INPUT_RATE" --output-rate "$OUTPUT_RATE" --cap "$ANSWER_CAP" --out runs/full/answers.jsonl
python3 -m compass judge --live --plan runs/full/plan.json --responses runs/full/answers.jsonl \
  --model "$JUDGE_MODEL" --base-url "$JUDGE_URL" --key-env JUDGE_KEY \
  --input-rate "$JUDGE_INPUT_RATE" --output-rate "$JUDGE_OUTPUT_RATE" --cap "$JUDGE_CAP" --out runs/full/grades.jsonl
python3 -m compass score --plan runs/full/plan.json --responses runs/full/answers.jsonl \
  --grades runs/full/grades.jsonl --out runs/full/scores.json
```

For an endpoint that uses its own sampling defaults or expects the newer output-token parameter, add `--provider-default-temperature` and/or `--token-field max_completion_tokens` to the `plan` command. These settings are recorded before the first trial. The reference grader expects JSON-object output; providers with a different native interface need a compatible gateway or adapter. The runner flags unknown usage and saves cost receipts locally. Set a provider-side spending limit as well.

To match the November protocol, use three repeats, 4,096 output tokens per call, up to eight calls per episode and the public v1 rubric prompt. See [METHODOLOGY.md](METHODOLOGY.md#execution-settings-for-the-november-2026-round).

</details>

## Data files

| File | Contents |
|---|---|
| [Question bank (JSON)](data/scenarios.json) | The facts, conversation turns, grading criteria and critical-failure rule for each case. |
| [Trial ratings (CSV)](data/trial-scores.csv) | All 4,680 trials, including ratings, points, execution status, failure flags and transcript hashes. |
| [Readable case list](docs/QUESTIONS.md) | Every case grouped by dimension and split. |
| [Summary scores (CSV)](docs/scores.csv) | Composite scores, dimension scores and composite uncertainty intervals for each system. |

The trial ratings support score replay. The underlying answer transcripts are not distributed. A fresh run produces new transcripts for your grader.

## Reporting a new run

Report the exact model version and deployment, run date, grader model and prompt, case selection, repeats, token allowance, sampling settings, scoring policy, failures and any deviations from this protocol. Different graders or deployments can produce different results. A public bank can be studied or trained on, so results on these cases and results on unseen cases answer different questions.

## Limitations

- Ortelan builds JUP-Eval and Praus, one of the systems evaluated, and had access to the bank while developing Praus. Split results are reported above.
- The November evaluation used automated grading with the published rubric. Independent human review is pending. See [how the published scores were graded](METHODOLOGY.md#grading).
- The cases are synthetic, written in English and marked as drafts.
- Praus was run as a configured system and the other systems as model endpoints with their own sampling settings.
- Intervals cover the sampling of scenario families only. They do not capture grader bias.

## Issues and corrections

Open an issue with the case ID, trial number, the visible evidence and the criterion in question. Corrections to cases or scoring will be released as new versions with a changelog.

## Citation

Use the [citation metadata](CITATION.cff) to cite the November 2026 edition.

## License

Ortelan has not issued a license for the benchmark code or question bank. Third-party fonts retain their included license notices.

Ortelan is an applied AI lab. We develop AI products, build and run systems for organizations, and invest in early-stage companies. [ortelan.com](https://ortelan.com)
