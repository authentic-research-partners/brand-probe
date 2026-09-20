# MVP checklist

## First working slice

- [x] Locate Git projects directory and create BrandProbe.
- [x] Inspect Vibe Sentinel and align the Python architecture.
- [x] Add a SoTS starter configuration based on its public homepage.
- [x] Detect the configured OpenRouter key without displaying it.
- [x] Build brand setup, an editable prompt screen, and a local browser adapter.
- [x] Implement labeled fixture mode and an OpenRouter transport.
- [x] Fetch current model prices and show a cost preview before approval.
- [x] Add bounded concurrency, conservative reservations, and SQLite evidence.
- [x] Separate recognition/discovery metrics; exclude unsuccessful responses.
- [x] Add raw evidence inspection and HTML/JSON/CSV exports.
- [x] Complete the 135-response synthetic audit.
- [x] Test budget stops, unknown costs, approval, errors, exports, and secret isolation.

## MVP completion

- [ ] Confirm target market, choose comparison brands, and review prompt coverage.
- [x] Add competitor-specific exact mentions with unbiased question denominators.
- [x] Add semantic recognition/recommendation labels with validated supporting quotes.
- [x] Add fact-sheet agreement/conflict checks with validated answer and reference quotes.
- [x] Add Brave Search as a separate, explicitly priced baseline (mocked API validation; live key/setup still required).
- [x] Add a local worker lock, dispatch journal, crash recovery, and newly approved continuation of never-dispatched model work.
- [x] Automatically load the model catalog in Live mode; show loading/error/retry states and preserve selection on refresh.
- [x] Run a five-question, three-model live pilot with an approved cost preview.
- [x] Manually inspect recognition answers and sample discovery answers; document exclusions and scoring limitations.

The pilot produced 40 usable answers and five truncated ones. All 40 usable answers were scored after a rubric correction and a paced recheck; one earlier scoring request has unknown billing. The owner reported adding $50 to the account; this is not treated as permission to consume the full balance. The proposed per-run budget remains $5, subject to explicit plan approval.

## Validation and remaining setup

The expanded suite has 43 offline tests, including crash/cancellation recovery, duplicate continuation prevention, cost preview, Brave transport/errors, fact evidence validation, competitor denominators, exports, and model-picker state transitions. Python lint/type checks and JavaScript syntax pass. The new Brave and fact-sheet workflows have not been tested with paid provider requests, and the UI changes have not been visually verified in a browser.

Before a real brand study, the owner still needs to confirm the audience/market, choose competitors, supply and approve sourced facts, and configure Brave credentials and subscription pricing if search is desired. Existing SoTS assumptions remain unchanged. Tests do not spend account credit.

Recovery is local, not a hosted job queue. Unknown/in-flight calls are retained without retries. A continuation is a linked new run with its own preview/budget, containing only never-dispatched generation work and scoring for those new answers; it does not retry old scoring or search. Legacy audits without a dispatch journal are conservatively classified as uncertain. Trend comparisons and automated external-source verification remain beyond this MVP.
