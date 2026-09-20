# Architecture

BrandProbe follows the approach inspected in Vibe Sentinel and its development checkout: one Python package, typed boundary models, declarative TOML, async HTTP at the edge, SQLite evidence, and thin entry points. It does not depend on Vibe Sentinel or copy its implementation.

The user requested this alignment on 2026-09-19 so that both projects use familiar structure and conventions. It replaces the original TypeScript-backend proposal. The browser layer is static HTML/CSS/JavaScript served by FastAPI; it delegates all audit behavior to the same core as the CLI. React is unnecessary for the present single-screen workflow.

## Dependency direction

| Layer | Modules | Responsibility |
| --- | --- | --- |
| Foundation | exceptions | Safe domain errors |
| Vocabulary | schemas, config, db/connection | Pydantic contracts, TOML and environment readers, connection lifecycle |
| Mechanisms | templates, fixtures, llm, search, measure, db/store | Exact messages, synthetic transport, OpenRouter transport, mechanical counts, persistence |
| Subjects | planning, analyze, worker | Price/scope review and evidence-bound semantic scoring |
| Composition | engine, report | Acquisition orchestration and portable presentation |
| Entry | cli, __main__, web, __init__, db/__init__ | Process and HTTP adapters |

Lower layers do not import higher ones. An architecture test checks internal imports and cycles. Pydantic defines boundary data; configuration is TOML; credentials are environment-only and excluded from serialized plans. Runtime async work stays async; CLI opens the event loop once. SQLite connections use one context manager and WAL. Loguru handles server diagnostics without request bodies or credentials.

## Pipeline

TOML/UI configuration → reviewed plan and model prices → explicit approval → bounded async requests → raw observations → deterministic mentions → persisted audit → browser/HTML/JSON/CSV.

Direct recognition and unprompted discovery remain separate. Acquisition never receives the brand fact sheet or brand metadata. Model output is untrusted text. An optional separate judge classifies recognition and recommendation using a versioned rubric. Exact quotes must exist in the answer and labels must be applicable; invalid scoring remains unassessed. Mechanical mentions and semantic judgments have separate denominators. Neither proves factual accuracy.

## Budget and recovery

The planner estimates cost and reserves a conservative amount using UTF-8 bytes plus framing, the requested output ceiling, listed reasoning rates, request charges, and a buffer. This is not exact tokenization or a provider billing guarantee. Provider prompt/completion/request price ceilings prevent routing to a more expensive endpoint for those price components. Fallbacks and tools are disabled. Returned model/provider metadata is saved; provider selection is not pinned across calls.

Generation and optional scoring reservations must fit before approval. Each request reserves before dispatch; the reservation is never refunded within that run. Unknown cost or a receipt above the reservation stops new dispatches; already running requests can still finish and incur charges. No automatic paid retries: failures may have been billed. Reports sum known receipts and separately count unknown ones.

A filesystem lease (POSIX flock) serializes local workers. Each request is journaled before dispatch; receipts are persisted on completion. Cancellation classifies missing work, and startup or `brandprobe recover` marks abandoned running audits interrupted while holding the lease. Legacy entries without a journal remain uncertain. Never-dispatched generation work can be continued only through a fresh price preview and approval; in-flight/unknown requests are never retried. A unique database index allows one linked child run per parent, preventing duplicate continuations. Old evidence and costs stay in the parent. This is a local macOS/Linux worker, not a cross-host job queue.

Plans expire after 15 minutes and browser plans are one-use. This is a local tool bound to 127.0.0.1, with a per-process mutation token, no CORS, restricted Host headers, and escaped output. It is not a multi-user hosted service.

## Scoring validation findings

The first live pilot exposed two issues that fixtures could not establish: reasoning can exhaust the output limit without a visible answer, and a judge can conflate an absent recommendation with an absent brand. The transport now preserves token-limit receipts; rubric v2 makes recommendation not applicable for direct recognition questions. Scoring attempts are retained when rechecked, including their costs and unknown billing. Shipped configurations pace scoring requests three seconds apart; HTTP rate limits still stop the run rather than triggering unbounded retries.

The exploratory pilot used provider-default generation effort. The next-run preset explicitly uses low effort after that observation. These are different inference settings and must not be presented as identical experiments.

## Empty-output protection

A user-selected DeepSeek run exposed the original starter file's hidden 600-token ceiling. The interface now exposes the output limit and includes both it and reasoning effort in the cost preview. Shipped starter files use 4,096 output tokens and low reasoning; model support is validated before paid runs. Stored historical configurations retain their original limits.

An empty truncated answer blocks further dispatches to that model for the current audit, while other models can continue. Requests already in flight may still finish and incur cost. Running reports use provisional language; final missing-discovery and incomplete-audit warnings are deferred until the run ends.

## Comparisons, references, and search

Comparison metrics use exact target/competitor mentions and shared successful unprompted answers. Questions naming any compared brand (including aliases) are excluded from the comparison denominator. Recognition questions remain separate. No competitor recommendation judgment is implied by a mention.

Approved facts contain stable IDs, a statement, source URL, and review date. Only the separate evaluator sees them. Rubric v3 compares each reference with explicit claims in an answer; support/conflict requires exact answer and reference quotes, while omissions are not contradictions. Invalid checks invalidate that assessment and retain the raw receipt. This is a model-mediated reference comparison, not independently fetched evidence or exhaustive hallucination detection. Older assessments remain readable.

Brave uses its web-search API and is a separate evidence channel: query, locale, ordered results, timestamp and raw payload. Results never enter generation or scoring prompts. The owner confirms their subscription rate; previews include every search request in the same run budget, while reports label search costs as estimates and exclude them from known model billing. Requests are paced, and failures halt further dispatch without retries. Domain ranks use parsed hostname boundaries, not substring matches.

The browser loads the public model catalog when Live mode is selected. It displays loading, error/retry, and populated states instead of an empty multi-select; refresh preserves selected models and invalidates any existing approval preview.
