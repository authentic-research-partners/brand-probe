# BrandProbe

Explore how AI models recognize and mention a brand, with the exact answers behind every count.

Built with the same architectural approach as Vibe Sentinel: Python 3.13, Pydantic, TOML, async HTTP, SQLite history, and a thin CLI. A local FastAPI browser interface uses the same core. See [architecture](docs/ARCHITECTURE.md).

## Run locally

```sh
uv sync --extra dev
source .venv/bin/activate
brandprobe demo
brandprobe serve
```

Open http://127.0.0.1:8765 after starting the server. `demo` generates 135 clearly labeled synthetic responses for Society of Teen Scientists without network requests. The browser starts in demo mode.

The supplied [SoTS configuration](examples/sots.toml) has 15 editable questions: three direct recognition questions and twelve unprompted questions about physics study and young-scientist communities. The initial audience and geography are assumptions from the public homepage, not validated customer research. No competitors have been selected yet.

## Live audit

Put `OPENROUTER_API_KEY` in `.env` or `.env.local`; both are gitignored. A process environment variable takes precedence. Never put secrets in TOML, screenshots, or reports. The existing configuration proposes a $5 per-run budget; account credit is not a spending instruction.

In the browser: select Live mode (the catalog loads automatically), select models, edit questions, preview costs, then approve the exact run. The catalog request does not incur model inference charges. Model prices are refreshed for the preview.

CLI equivalent:

```sh
brandprobe models
brandprobe plan --model PROVIDER/MODEL_ID
brandprobe run --model PROVIDER/MODEL_ID
```

Repeat `--model` for additional models. `run` prints the estimate and conservative reservation, then requires typing `RUN`. No paid requests are made by setup or tests. The live pipeline has been exercised with paid requests; reports preserve incomplete/truncated responses and do not claim full coverage when requests fail.

## Current functionality

- Editable brand context and questions, 1–5 independent repetitions.
- Model catalog, cost preview, run approval, bounded async requests.
- Separate prompted recognition and unprompted discovery counts.
- Optional semantic scoring: recognized/unrecognized/uncertain and recommended/discouraged/neutral/absent, with exact supporting quotes and separately tracked costs.
- Five-question SoTS pilot preset; explicit reasoning effort validated against model capabilities.
- Raw responses, timestamps, model/provider metadata, usage, and errors in `.brandprobe/history.db`.
- Competitor exact-mention comparisons with shared, unprompted denominators.
- Optional approved fact-sheet checks with quoted agreement/conflict evidence.
- Separately priced Brave Search results and domain ranks, kept out of model prompts.
- Local dispatch journaling, crash recovery and approved continuation of never-dispatched answers.
- Evidence inspection and HTML/JSON/CSV exports; CLI reports in `.brandprobe/reports/`.
- Unknown billing stops further dispatch. Errors/truncations are excluded from mention denominators.

A mention is not an endorsement. An absence does not establish that a brand is absent from training data. API measurements do not reproduce consumer chat applications. Demo data is synthetic, never a brand finding. Short ambiguous aliases are excluded from automatic matching.

## Not implemented yet

Trend comparisons, automated source collection, exhaustive fact verification, and hosted/distributed job scheduling. Reference checks compare supplied facts; they do not establish independent ground truth.

## Development

```sh
pytest -q
ruff format --check .
ruff check .
mypy brandprobe
```

Tests use fixtures and mocked HTTP; no keys or paid requests are needed. `uv.lock` records dependency resolution. Run only one local instance per workspace. Do not expose this prototype directly to the internet.

BrandProbe is a working name; trademark and domain availability have not been checked.

## Scoring and the pilot

Use **Load the 5-question SoTS pilot** in the browser. It selects three models, three repetitions, a scoring model, and low reasoning effort, subject to current catalog availability. Review all choices and the combined price preview before approving. CLI: `brandprobe run --config examples/sots-pilot.toml`.

Semantic scoring is a model judgment, not ground truth. It never alters original responses. Unsupported quotes and inconsistent labels are rejected as unassessed. A substantive description can count as recognized even if its claims are wrong; approved reference checks are separate and cover only supplied facts. Directly naming a brand is never counted as spontaneous discovery.

`reasoning_effort` is persisted with the run. Provider defaults are retained when it is unset; the same token cap can yield different amounts of visible text across models. Empty `finish_reason: length` responses are truncated, retain receipts, and are excluded from visibility metrics.

## Competitors and reference checks

Open **Comparison brands and reference facts** in setup. Add competitors by name/domain and optional aliases. Reports compare exact mentions only on successful questions naming none of the compared brands; prompted alternatives are excluded from that comparison. A mention is not a recommendation.

For reference checks, add short statements, source URLs and review dates, tick the approval checkbox, and select a scoring model. The judge compares each fact with the answer and quotes both sources for agreement/conflict. Omitted facts are marked not addressed. References never prime model acquisition. These are reference-bound model judgments, not exhaustive verification of every claim. Large fact sheets can exhaust the scoring token limit; start with a few concise facts and inspect exclusions.

## Brave Search baseline

Add `BRAVE_SEARCH_API_KEY` to `.env.local`, enter explicit search queries under Live settings, and verify the subscription rate before previewing. The editable starting rate is not a promise about your account price. The preview includes the search portion; reports show it as estimated cost, separately from model billing receipts. Demo mode sends no search requests.

The [Brave web-search API](https://api-dashboard.search.brave.com/api-reference/web/search/post) supplies an independent search snapshot. We record only the requested first page (up to 20 results) and exact domain positions. No returned result is injected into model answers. Absence from this page is not absence from the index, and Brave rank does not establish visibility in ChatGPT or Claude.

## Interrupted runs

On the next server startup, abandoned runs are classified under an exclusive local worker lock. You can also run `brandprobe recover` without making API calls. In history, **Preview remaining work** creates a linked continuation for never-dispatched generation requests. Review its fresh prices and approve it separately; completed or uncertain calls are not repeated, and the original report is preserved. Search and old scoring requests are not retried by continuation. Legacy runs without a dispatch journal cannot safely continue automatically.

Keep one local instance per workspace. Restart the server after backend updates; refresh the browser for static UI updates. The worker lock uses POSIX file locking (macOS/Linux).
