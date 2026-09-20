# MVP status

## Implemented

- [x] Editable brand context, questions, and independent repetitions.
- [x] Synthetic demo with no API calls or charges.
- [x] OpenRouter catalog, price preview, approval, bounded requests, and raw evidence.
- [x] Searchable model picker with explicit Add/Remove controls.
- [x] Separate recognition, discovery, and competitor mention measurements.
- [x] Optional semantic scoring with validated supporting quotes.
- [x] Agreement/conflict checks against approved reference facts.
- [x] Separate Brave Search baseline with subscription-rate estimates.
- [x] SQLite history and HTML/JSON/CSV exports.
- [x] Dispatch journaling, local worker lock, crash classification, and approved continuation of never-dispatched answers.

## Verification

The automated suite covers cost limits, credential isolation, provider failures, quote validation, competitor denominators, search transport, exports, recovery, and model-picker interactions. Python lint/type checks and JavaScript syntax are checked separately.

Live generation and semantic scoring have been exercised, including a completed five-question, three-model run with three repetitions: all 45 answers and 45 assessments completed. Earlier pilots exposed truncation, rate limits, and ambiguous judge labels; those observations informed the current exclusions and evidence validation.

Reference-fact checking and Brave Search have mocked tests but have not yet been validated through live provider calls. Interface behavior has automated state tests; browser visual verification remains outstanding.

## Before each real study

- [ ] Confirm the target audience, market, and relevance of the chosen questions.
- [ ] Choose comparison brands and review names and aliases.
- [ ] Supply and approve reference facts if using factual comparisons.
- [ ] Configure Brave credentials and confirm the subscription rate if using search.
- [ ] Review the exact scope and costs before approving paid requests.
- [ ] Inspect raw answers and judge evidence before sharing conclusions.

## Outside this MVP

Trend comparisons, automatic source collection, independent exhaustive fact verification, and distributed job scheduling. Continuation preserves original evidence and never automatically retries uncertain, scoring, or search requests. Legacy runs without a dispatch journal remain conservatively classified as uncertain.
