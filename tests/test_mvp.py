"""MVP evidence boundaries, dispatch recovery and separately budgeted search."""

import asyncio
from decimal import Decimal
from pathlib import Path
import csv
import io
import json
import subprocess

import httpx
import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from brandprobe.schemas import (
    Audit,
    AuditConfig,
    Assessment,
    Brand,
    BrandFact,
    Competitor,
    FactCheck,
    ModelPrice,
    Observation,
    Prompt,
    SearchConfig,
    SearchObservation,
    SearchHit,
    Completion,
)
from brandprobe.analyze import evaluate, validate_facts, conversation
from brandprobe.templates import messages
from brandprobe.planning import make_plan
from brandprobe.engine import execute
from brandprobe.search import search
from brandprobe.measure import competitor_summary, search_summary
from brandprobe.report import report_data, html_report, csv_report
from brandprobe.db import store
from brandprobe.worker import lease, recover, remaining
from brandprobe.web import create_app
from brandprobe.exceptions import BrandProbeError


@pytest.fixture
def cfg():
    return AuditConfig(
        brand=Brand(
            name="Teen Society", domain="teen.example", audience="Teen researchers"
        ),
        models=["test/model"],
        prompts=[
            Prompt(
                id="q1",
                kind="discovery",
                text="Which science clubs should teenagers join?",
            ),
            Prompt(
                id="q2",
                kind="recognition",
                text="What is Teen Society and who is it for?",
            ),
        ],
        repetitions=1,
        concurrency=1,
    )


def build(cfg, demo=True, **kwargs):
    async def run():
        async with httpx.AsyncClient() as client:
            return await make_plan(cfg, demo, client, **kwargs)

    return asyncio.run(run())


def fact():
    return BrandFact(
        id="f1",
        statement="Membership is free for teenagers.",
        source_url="https://teen.example/about",
        reviewed_at="2026-09-20",
    )


def assessment(checks):
    return Assessment(
        recognition="not_applicable",
        recommendation="absent",
        recognition_quote="",
        recommendation_quote="",
        rationale="No target mention",
        fact_checks=checks,
    )


def test_reference_requires_approval_and_evaluator_and_valid_dates(cfg):
    values = cfg.model_dump()
    values["facts"] = [fact().model_dump()]
    with pytest.raises(ValidationError):
        AuditConfig.model_validate(values)
    values.update(facts_approved=True, evaluator_model="test/model")
    validated = AuditConfig.model_validate(values)
    assert validated.facts[0].id == "f1"
    with pytest.raises(ValidationError):
        BrandFact(**{**fact().model_dump(), "reviewed_at": "yesterday!"})


def test_fact_quotes_and_omissions_cannot_be_fabricated(cfg):
    cfg.facts = [fact()]
    observation = Observation(
        model="m",
        prompt=cfg.prompts[0],
        repetition=1,
        status="ok",
        text="Membership costs $50.",
    )
    check = FactCheck(
        fact_id="f1",
        verdict="contradicted",
        answer_quote="Membership costs $50.",
        reference_quote="Membership is free",
        rationale="Conflicting cost",
    )
    validate_facts(assessment([check]), cfg, observation)
    for update in (
        {"answer_quote": "invented"},
        {"reference_quote": "invented"},
        {"answer_quote": ""},
        {"verdict": "not_addressed"},
    ):
        with pytest.raises(ValueError):
            validate_facts(
                assessment([check.model_copy(update=update)]), cfg, observation
            )
    with pytest.raises(ValueError):
        validate_facts(assessment([]), cfg, observation)
    with pytest.raises(ValueError):
        validate_facts(assessment([check, check]), cfg, observation)
    validate_facts(
        assessment(
            [
                check.model_copy(
                    update={
                        "verdict": "not_addressed",
                        "answer_quote": "",
                        "reference_quote": "",
                    }
                )
            ]
        ),
        cfg,
        observation,
    )


def test_reference_and_competitors_never_prime_acquisition(cfg):
    cfg.facts = [fact()]
    cfg.competitors = [Competitor(name="Other Club", domain="other.example")]
    cfg.facts_approved = True
    cfg.evaluator_model = "test/model"
    acquisition = json.dumps(messages(cfg, cfg.prompts[0]))
    assert (
        "Membership" not in acquisition
        and "Other Club" not in acquisition
        and cfg.brand.name not in acquisition
    )
    o = Observation(
        model="m", prompt=cfg.prompts[0], repetition=1, status="ok", text="An answer"
    )
    assert "Membership" in json.dumps(conversation(cfg, o))


def test_invalid_fact_check_is_not_retained_as_valid_assessment(cfg, monkeypatch):
    cfg.facts = [fact()]
    bad = assessment(
        [
            FactCheck(
                fact_id="f1",
                verdict="supported",
                answer_quote="fake",
                reference_quote="Membership",
                rationale="bad",
            )
        ]
    )

    async def complete(*args, **kwargs):
        return Completion(
            status="ok",
            text=bad.model_dump_json(),
            cost_usd=Decimal(".001"),
            raw={"receipt": "saved"},
        )

    monkeypatch.setattr("brandprobe.analyze.complete", complete)

    async def run():
        async with httpx.AsyncClient() as client:
            return await evaluate(
                client,
                "key",
                cfg,
                ModelPrice(id="m", name="m", input_per_token=0, output_per_token=0),
                Observation(
                    model="m",
                    prompt=cfg.prompts[0],
                    repetition=1,
                    status="ok",
                    text="No useful answer",
                ),
            )

    result = asyncio.run(run())
    assert (
        result.status == "error"
        and result.assessment is None
        and result.cost_usd == Decimal(".001")
    )
    assert result.raw == {"receipt": "saved"}


def test_competitor_denominators_exclude_named_prompts_and_failures(cfg):
    cfg.competitors = [Competitor(name="Other Club", domain="other.example")]
    plan = build(cfg)
    a = Audit(
        plan=plan,
        observations=[
            Observation(
                model="m",
                prompt=cfg.prompts[0],
                repetition=1,
                status="ok",
                text="Try Other Club or Teen Society.",
            ),
            Observation(
                model="m",
                prompt=Prompt(
                    id="biased",
                    kind="alternatives",
                    text="What are alternatives to Other Club?",
                ),
                repetition=1,
                status="ok",
                text="Teen Society",
            ),
            Observation(
                model="m",
                prompt=cfg.prompts[0],
                repetition=2,
                status="truncated",
                text="Other Club",
            ),
        ],
    )
    rows = competitor_summary(a)
    assert [(r["mentions"], r["successful"], r["excluded"]) for r in rows] == [
        (1, 1, 2),
        (1, 1, 2),
    ]
    assert all(len(r["observation_ids"]) == 1 for r in rows)
    a.observations = a.observations[1:]
    assert all(r["successful"] == 0 for r in competitor_summary(a))


def test_brave_transport_and_domain_boundaries(cfg):
    def handler(request):
        assert request.headers["x-subscription-token"] == "secret"
        assert (
            request.url.params["q"] == "teen science"
            and request.url.params["country"] == "US"
        )
        return httpx.Response(
            200,
            json={
                "type": "search",
                "web": {
                    "results": [
                        {"title": "Spoof", "url": "https://teen.example.evil.org"},
                        {
                            "title": "Society",
                            "url": "https://www.teen.example/about",
                            "description": "A club",
                        },
                    ]
                },
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await search(client, "secret", SearchConfig(), "teen science")

    result = asyncio.run(run())
    assert result.status == "ok"
    assert "secret" not in result.model_dump_json()
    assert result.estimated_cost_usd == Decimal(".005")
    a = Audit(plan=build(cfg), search_observations=[result])
    assert search_summary(a)[0]["first_domain_rank"] == 2
    data = report_data(a)
    assert (
        data["known_cost_usd"] == "0" and data["search_estimated_cost_usd"] == "0.005"
    )


@pytest.mark.parametrize(
    "status,payload",
    [
        (429, {}),
        (200, {"error": "bad"}),
        (200, {"type": "search", "web": {"results": "bad"}}),
    ],
)
def test_search_errors_are_unknown_billing(status, payload):
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(status, json=payload)
            )
        ) as c:
            return await search(c, "key", SearchConfig(), "question")

    result = asyncio.run(run())
    assert result.status == "error" and result.estimated_cost_usd is None


def test_search_cost_in_preview_and_rate_confirmation(cfg, monkeypatch):
    async def catalog(client):
        return [
            ModelPrice(
                id="test/model", name="Test", input_per_token=0, output_per_token=0
            )
        ]

    monkeypatch.setattr("brandprobe.planning.catalog", catalog)
    cfg.search = SearchConfig(
        queries=["one query", "another query"], price_per_request_usd=".02"
    )
    with pytest.raises(BrandProbeError, match="Confirm"):
        build(cfg, False)
    cfg.search.rate_confirmed = True
    plan = build(cfg, False)
    assert plan.search_requests == 2 and plan.reserved_usd == Decimal(".04")
    cfg.budget_usd = Decimal(".03")
    with pytest.raises(BrandProbeError, match="exceeds"):
        build(cfg, False)
    assert build(cfg).search_requests == 0


def test_hard_crash_recovery_preserves_receipts_and_never_retries_unknown(
    cfg, tmp_path
):
    a = Audit(plan=build(cfg), dispatch_journal=True)
    a.observations = [
        Observation(
            model=a.plan.prices[0].id,
            prompt=cfg.prompts[0],
            repetition=1,
            status="ok",
            text="saved",
            cost_usd=Decimal(".01"),
        ),
        Observation(
            model=a.plan.prices[0].id,
            prompt=cfg.prompts[1],
            repetition=1,
            status="interrupted",
        ),
    ]
    store.save(tmp_path, a)
    with lease(tmp_path):
        assert recover(tmp_path) == 1
    saved = store.get(tmp_path, a.id)
    assert saved.status == "interrupted" and len(saved.observations) == 6
    assert len(remaining(saved)) == 4 and saved.observations[0].text == "saved"
    assert report_data(saved)["unknown_cost_responses"] == 1
    with lease(tmp_path):
        assert recover(tmp_path) == 0
    continuation = build(cfg, work_items=remaining(saved), parent_audit_id=a.id)
    assert continuation.requests == 4
    child = asyncio.run(execute(tmp_path, continuation))
    assert len(child.observations) == 4
    assert not {(o.model, o.prompt.id, o.repetition) for o in a.observations} & {
        (o.model, o.prompt.id, o.repetition) for o in child.observations
    }
    assert store.get(tmp_path, a.id) == saved


def test_legacy_missing_requests_are_uncertain(cfg, tmp_path):
    a = Audit(plan=build(cfg))
    store.save(tmp_path, a)
    with lease(tmp_path):
        recover(tmp_path)
    saved = store.get(tmp_path, a.id)
    assert all(o.status == "interrupted" for o in saved.observations)
    with pytest.raises(BrandProbeError):
        remaining(saved)


def test_worker_lease_prevents_second_process_recovery(cfg, tmp_path):
    with lease(tmp_path):
        with pytest.raises(BrandProbeError, match="worker"):
            with lease(tmp_path):
                pass


def test_cancellation_records_dispatch_and_remaining(cfg, tmp_path, monkeypatch):
    cfg.concurrency = 1
    plan = build(cfg).model_copy(update={"mode": "live"})

    async def run():
        started = asyncio.Event()

        async def interrupted(*args):
            saved = store.history(tmp_path)[0]
            assert saved.observations[0].status == "interrupted"
            started.set()
            await asyncio.Event().wait()

        monkeypatch.setattr("brandprobe.engine.llm.respond", interrupted)
        task = asyncio.create_task(execute(tmp_path, plan, key="test", approved=True))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    saved = store.history(tmp_path)[0]
    assert saved.status == "interrupted" and len(saved.observations) == 6
    assert len(remaining(saved)) == 5


def test_search_failure_stops_further_queries(cfg, tmp_path, monkeypatch):
    plan = build(cfg).model_copy(update={"mode": "live", "search_requests": 2})
    plan.config.search = SearchConfig(queries=["first", "second"], rate_confirmed=True)

    async def answer(client, key, config, price, prompt, repetition):
        return Observation(
            model=price.id,
            prompt=prompt,
            repetition=repetition,
            status="ok",
            text="answer",
            cost_usd=0,
        )

    calls = []

    async def failure(client, key, config, query):
        calls.append(query)
        return SearchObservation(query=query, status="error", error="timeout")

    monkeypatch.setattr("brandprobe.engine.llm.respond", answer)
    monkeypatch.setattr("brandprobe.engine.search", failure)
    audit = asyncio.run(
        execute(tmp_path, plan, key="test", approved=True, search_key="test")
    )
    assert calls == ["first"] and [r.status for r in audit.search_observations] == [
        "error",
        "skipped",
    ]
    assert audit.status == "partial" and report_data(audit)["unknown_search_costs"] == 1


def test_exports_keep_search_and_facts_distinct(cfg):
    cfg.competitors = [Competitor(name="Other Club", domain="other.example")]
    a = Audit(
        plan=build(cfg),
        search_observations=[
            SearchObservation(
                query="=formula",
                status="ok",
                results=[
                    SearchHit(
                        rank=1, title="<script>alert(1)</script>", url="javascript:bad"
                    )
                ],
                estimated_cost_usd=".005",
            )
        ],
    )
    html = html_report(a)
    assert "<script>alert" not in html and "Brave Search baseline" in html
    rows = list(csv.reader(io.StringIO(csv_report(a))))
    assert len(rows[0]) == len(rows[1]) and rows[1][8] == "'=formula"
    assert rows[1][17] == "search" and rows[1][7] == ""


def test_web_startup_recovers_and_continuation_needs_fresh_approval(cfg, tmp_path):
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples/sots.toml").write_text(Path("examples/sots.toml").read_text())
    original = Audit(plan=build(cfg), dispatch_journal=True)
    store.save(tmp_path, original)
    with TestClient(create_app(tmp_path)) as client:
        setup = client.get("/api/setup").json()
        headers = {"x-brandprobe-token": setup["token"]}
        history = client.get("/api/runs").json()
        assert history[0]["can_continue"]
        path = f"/api/runs/{original.id}/continuation"
        assert client.post(path, json={}).status_code == 403
        preview = client.post(path, json={}, headers=headers)
        assert preview.status_code == 200
        assert preview.json()["parent_audit_id"] == original.id
        assert len(store.history(tmp_path)) == 1
        child = client.post(
            "/api/runs", json={"plan_id": preview.json()["id"]}, headers=headers
        )
        assert child.status_code == 200
        assert client.post(path, json={}, headers=headers).status_code == 400


def test_model_picker_loading_states():
    subprocess.run(
        ["node", "tests/model_picker.cjs"], check=True, capture_output=True, text=True
    )
