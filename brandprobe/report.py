"""One report shape for the CLI, browser, and portable exports."""

import json
import csv
import io
from collections import Counter
from html import escape
from decimal import Decimal
from brandprobe.measure import (
    summarize,
    semantic_summary,
    competitor_summary,
    search_summary,
    find_mentions,
    comparable,
)
from brandprobe.schemas import Audit, Brand, Competitor


def report_data(audit: Audit) -> dict:
    generated = sum(
        (o.cost_usd for o in audit.observations if o.cost_usd is not None), Decimal(0)
    )
    judged = sum(
        (
            o.evaluation.cost_usd
            for o in audit.observations
            if o.evaluation and o.evaluation.cost_usd is not None
        ),
        Decimal(0),
    )
    previous = [
        prior
        for o in audit.observations
        if o.evaluation
        for prior in o.evaluation.previous_attempts
    ]
    judged += sum(
        (
            Decimal(str(e["cost_usd"]))
            for e in previous
            if e.get("cost_usd") is not None
        ),
        Decimal(0),
    )
    summary = semantic_summary(audit.observations)
    warnings = []
    if audit.plan.mode == "demo":
        warnings.append(
            "Synthetic demo: no real model was tested. These counts are not findings about this brand."
        )
    running = audit.status == "running"
    if running:
        warnings.append(
            "Run in progress. Counts are provisional until acquisition and scoring finish."
        )
    elif audit.status != "complete":
        warnings.append(
            "Incomplete audit: failed, skipped, or unassessed answers limit the conclusions."
        )
    if (
        not running
        and any(p.kind != "recognition" for p in audit.plan.config.prompts)
        and not any(
            o.status == "ok" and o.prompt.kind != "recognition"
            for o in audit.observations
        )
    ):
        warnings.append(
            "Discovery is unmeasured: no successful unprompted responses. Do not interpret this as 0% visibility."
        )
    if (
        not running
        and audit.plan.mode == "live"
        and any(r["unassessed"] for r in summary)
    ):
        warnings.append(
            "Some answers have no semantic assessment. A brand mention alone does not prove recognition or recommendation."
        )
    truncated = sum(o.status == "truncated" for o in audit.observations)
    if truncated:
        warnings.append(
            f"{truncated} answers reached the token limit. For a new run, lower reasoning effort or increase the output token limit and review the new cost preview."
        )
    if audit.search_observations:
        warnings.append(
            "Search is a separate Brave snapshot, not a measurement of consumer AI search. Search costs use your entered subscription rate, not billing receipts."
        )
    if audit.plan.config.facts:
        warnings.append(
            "Fact checks compare model answers with the owner-approved reference only; they are not independent or exhaustive verification."
        )
    if audit.recovery_note:
        warnings.append(audit.recovery_note)
    return {
        "audit": audit.model_dump(mode="json"),
        "summary": summarize(audit.observations),
        "competitor_summary": competitor_summary(audit),
        "search_summary": search_summary(audit),
        "search_estimated_cost_usd": str(
            sum(
                (
                    r.estimated_cost_usd
                    for r in audit.search_observations
                    if r.estimated_cost_usd is not None
                ),
                Decimal(0),
            )
        ),
        "unknown_search_costs": sum(
            r.status in ("error", "interrupted") for r in audit.search_observations
        ),
        "semantic_summary": summary,
        "warnings": warnings,
        "status_counts": dict(Counter(o.status for o in audit.observations)),
        "evaluation_attempts": sum(
            o.evaluation is not None and o.evaluation.status not in ("skipped", "demo")
            for o in audit.observations
        )
        + sum(e.get("status") not in ("skipped", "demo") for e in previous),
        "known_cost_usd": str(generated + judged),
        "generation_cost_usd": str(generated),
        "evaluation_cost_usd": str(judged),
        "unknown_cost_responses": sum(
            o.cost_usd is None and o.status != "skipped" for o in audit.observations
        ),
        "unknown_evaluation_costs": sum(
            o.evaluation is not None
            and o.evaluation.status not in ("skipped", "demo")
            and o.evaluation.cost_usd is None
            for o in audit.observations
        )
        + sum(
            e.get("cost_usd") is None and e.get("status") not in ("skipped", "demo")
            for e in previous
        ),
    }


def csv_report(audit: Audit) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "mode",
            "model",
            "prompt_id",
            "kind",
            "repetition",
            "status",
            "mention",
            "cost_usd",
            "prompt",
            "response",
            "error",
            "assessment_status",
            "recognition",
            "recommendation",
            "recognition_quote",
            "recommendation_quote",
            "evaluation_cost_usd",
            "channel",
            "competitor_mentions_json",
            "fact_checks_json",
            "search_results_json",
            "search_estimated_cost_usd",
        ]
    )
    compared_brands: list[Brand | Competitor] = [
        audit.plan.config.brand,
        *audit.plan.config.competitors,
    ]
    for o in audit.observations:
        values = [
            audit.plan.mode,
            o.model,
            o.prompt.id,
            o.prompt.kind,
            str(o.repetition),
            o.status,
            str(o.mention),
            str(o.cost_usd) if o.cost_usd is not None else "",
            o.prompt.text,
            o.text,
            o.error,
            o.evaluation.status if o.evaluation else "not_assessed",
            o.evaluation.assessment.recognition
            if o.evaluation and o.evaluation.assessment
            else "",
            o.evaluation.assessment.recommendation
            if o.evaluation and o.evaluation.assessment
            else "",
            o.evaluation.assessment.recognition_quote
            if o.evaluation and o.evaluation.assessment
            else "",
            o.evaluation.assessment.recommendation_quote
            if o.evaluation and o.evaluation.assessment
            else "",
            str(o.evaluation.cost_usd)
            if o.evaluation and o.evaluation.cost_usd is not None
            else "",
            "model",
            json.dumps(
                [
                    {
                        "brand": brand.name,
                        "eligible": comparable(o, compared_brands),
                        "evidence": find_mentions(o.text, brand)
                        if o.status == "ok"
                        else [],
                    }
                    for brand in audit.plan.config.competitors
                ]
            ),
            json.dumps([c.model_dump() for c in o.evaluation.assessment.fact_checks])
            if o.evaluation
            and o.evaluation.status == "complete"
            and o.evaluation.assessment
            else "[]",
            "",
            "",
        ]
        writer.writerow(
            [
                "'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v
                for v in values
            ]
        )
    for r in audit.search_observations:
        values = [
            audit.plan.mode,
            "Brave",
            "",
            "search",
            "",
            r.status,
            "",
            "",
            r.query,
            "",
            r.error,
            "",
            "",
            "",
            "",
            "",
            "",
            "search",
            "",
            "",
            json.dumps([h.model_dump() for h in r.results]),
            str(r.estimated_cost_usd) if r.estimated_cost_usd is not None else "",
        ]
        writer.writerow(
            [
                "'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v
                for v in values
            ]
        )
    return output.getvalue()


def html_report(audit: Audit) -> str:
    data = report_data(audit)
    label = (
        "Synthetic demo — not brand research"
        if audit.plan.mode == "demo"
        else "Live API audit — search disabled"
    )
    warnings = "".join(f"<p class='warning'>{escape(w)}</p>" for w in data["warnings"])
    rows = ""
    for r in data["semantic_summary"]:
        mention = (
            f"{r['mentions']} / {r['successful']}" if r["successful"] else "Unmeasured"
        )
        recognition = (
            f"{r['recognized']} / {r['assessed']}"
            if r["assessed"] and r["kind"] == "recognition"
            else "Not assessed"
            if r["kind"] == "recognition"
            else "Not applicable"
        )
        recommendation = (
            "Not applicable"
            if r["kind"] == "recognition"
            else (
                f"{r['recommended']} / {r['assessed']}"
                if r["assessed"]
                else "Not assessed"
            )
        )
        rows += f"<tr><td>{escape(r['model'])}</td><td>{r['kind']}</td><td>{mention}</td><td>{recognition}</td><td>{recommendation}</td><td>{r['excluded']}</td></tr>"
    evidence = ""
    for o in audit.observations:
        assessment = ""
        if (
            o.evaluation
            and o.evaluation.status == "complete"
            and o.evaluation.assessment
        ):
            v = o.evaluation.assessment
            assessment = f"<p><b>Recognition:</b> {v.recognition}; <b>recommendation:</b> {v.recommendation}</p><p>{escape(v.rationale)}</p><blockquote>{escape(v.recognition_quote or v.recommendation_quote)}</blockquote>"
        elif o.evaluation:
            assessment = f"<p>Assessment: {o.evaluation.status}. {escape(o.evaluation.error)}</p>"
        if (
            o.evaluation
            and o.evaluation.status == "complete"
            and o.evaluation.assessment
        ):
            for check in o.evaluation.assessment.fact_checks:
                assessment += f"<p>Fact {escape(check.fact_id)}: {check.verdict}. {escape(check.rationale)}</p><blockquote>Answer: {escape(check.answer_quote)}<br>Reference: {escape(check.reference_quote)}</blockquote>"
        evidence += f"<details><summary>{escape(o.model)} · {escape(o.prompt.id)} · repetition {o.repetition} · {o.status}</summary><h3>{escape(o.prompt.text)}</h3>{assessment}<pre>{escape(o.text or o.error)}</pre></details>"
    extra = ""
    if audit.plan.config.competitors:
        extra += "<h2>Comparison brands</h2><p>Exact mentions on successful questions naming none of the compared brands. Not recommendations.</p><table><tr><th>Model</th><th>Brand</th><th>Mentions / eligible</th><th>Excluded</th></tr>"
        for r in data["competitor_summary"]:
            count = (
                f"{r['mentions']} / {r['successful']}"
                if r["successful"]
                else "Unmeasured"
            )
            extra += f"<tr><td>{escape(r['model'])}</td><td>{escape(r['brand'])}</td><td>{count}</td><td>{r['excluded']}</td></tr>"
        extra += "</table>"
    if audit.plan.config.facts:
        extra += "<h2>Approved reference facts</h2>"
        for fact in audit.plan.config.facts:
            extra += f"<p>{escape(fact.id)}: {escape(fact.statement)}<br>Source: {escape(fact.source_url)} · reviewed {escape(fact.reviewed_at)}</p>"
    if audit.search_observations:
        extra += f"<h2>Brave Search baseline</h2><p>Estimated cost: ${data['search_estimated_cost_usd']}. Requests with uncertain billing: {data['unknown_search_costs']}.</p>"
        for r in data["search_summary"]:
            rank = (
                str(r["first_domain_rank"])
                if r["first_domain_rank"]
                else (
                    f"Not in {r['returned_results']} returned results"
                    if r["status"] == "ok"
                    else r["status"]
                )
            )
            extra += f"<p>{escape(r['query'])} · {escape(r['brand'])} · domain rank: {escape(rank)}</p>"
        for result in audit.search_observations:
            extra += f"<details><summary>{escape(result.query)} · {result.status}</summary><p>{escape(result.error)}</p>"
            for hit in result.results:
                extra += f"<p>{hit.rank}. {escape(hit.title)}<br>{escape(hit.url)}<br>{escape(hit.description)}</p>"
            extra += "</details>"
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BrandProbe audit</title><style>body{{font:16px/1.6 system-ui;max-width:1200px;margin:40px auto;padding:0 24px;color:#23384d}}h1{{font:40px Georgia}}.label{{background:#edf3fa;padding:12px}}.warning{{background:#fff4d9;padding:12px}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;border-bottom:1px solid #ccd7e5;padding:12px}}details{{border-bottom:1px solid #ccd7e5;padding:16px 0}}summary{{cursor:pointer}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}blockquote{{border-left:3px solid #225fc7;padding-left:16px}}</style><p>BrandProbe / audit evidence</p><h1>{escape(audit.plan.config.brand.name)}</h1><p class="label">{label}</p>{warnings}<p>{escape(audit.started_at)} · Status: {audit.status}</p><p>Known generation cost: ${data["generation_cost_usd"]}; scoring: ${data["evaluation_cost_usd"]}. Unknown costs: {data["unknown_cost_responses"]} generation, {data["unknown_evaluation_costs"]} scoring requests.</p><p>Recognition means the answer describes the brand; it does not verify that description. Semantic scores are model judgments with quoted evidence. Errors, truncations, and unassessed answers are not negative findings. These API samples do not reproduce consumer chat applications.</p><div class="table"><table><thead><tr><th>Model</th><th>Question type</th><th>Mentions / successful</th><th>Recognition / assessed</th><th>Recommendations / assessed</th><th>Excluded</th></tr></thead><tbody>{rows}</tbody></table></div>{extra}<h2>Inspect the evidence</h2>{evidence}</html>"""
