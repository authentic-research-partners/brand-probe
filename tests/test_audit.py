import asyncio
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from brandprobe.config import load_config
from brandprobe.db import store
from brandprobe.engine import execute
from brandprobe.exceptions import BrandProbeError
from brandprobe.llm import respond
from brandprobe.measure import find_mentions, summarize
from brandprobe.planning import make_plan
from brandprobe.report import csv_report, html_report
from brandprobe.schemas import (
    Audit,
    AuditConfig,
    Brand,
    ModelPrice,
    Observation,
    Prompt,
)
from brandprobe.web import create_app


@pytest.fixture
def config():
    return AuditConfig(
        brand=Brand(
            name="Society of Teen Scientists",
            domain="teenscientists.org",
            audience="Teen researchers",
        ),
        prompts=[
            Prompt(
                id="direct",
                kind="recognition",
                text="What is Society of Teen Scientists?",
            ),
            Prompt(
                id="discovery",
                kind="discovery",
                text="Which physics programs should a teenager consider?",
            ),
        ],
        repetitions=2,
    )


def plan_for(config):
    async def run():
        async with httpx.AsyncClient() as client:
            return await make_plan(config, True, client)

    return asyncio.run(run())


def test_unbranded_prompt_cannot_contain_target(config):
    data = config.model_dump()
    data["prompts"][1]["text"] = "Please recommend Society of Teen Scientists."
    with pytest.raises(ValidationError, match="contains a target"):
        AuditConfig.model_validate(data)


def test_fixture_audit_persists_and_denominators_stay_separate(config, tmp_path):
    plan = plan_for(config)
    audit = asyncio.run(execute(tmp_path, plan))
    assert audit.status == "complete"
    assert len(audit.observations) == 12
    assert store.get(tmp_path, audit.id) == audit
    assert all(r["successful"] == 2 for r in summarize(audit.observations))
    assert all(o.cost_usd == 0 for o in audit.observations)
    assert "Synthetic demo" in html_report(audit)


def test_failures_and_truncation_are_not_absence(config):
    observations = [
        Observation(
            model="one", prompt=config.prompts[1], repetition=i, status=s, mention=True
        )
        for i, s in enumerate(["ok", "error", "truncated", "skipped"], 1)
    ]
    assert summarize(observations) == [
        dict(
            model="one", kind="discovery", mentions=1, successful=1, excluded=3, rate=1
        )
    ]
    assert summarize(observations[1:])[0]["rate"] is None


def test_mentions_are_case_insensitive_and_have_boundaries(config):
    assert find_mentions("Visit TEENSCIENTISTS.ORG today", config.brand)
    assert not find_mentions("notteenscientists.org", config.brand)
    assert not find_mentions("Society of Teen ScientistsExtra", config.brand)


def test_live_requires_approval_before_any_dispatch(config, tmp_path):
    plan = plan_for(config).model_copy(update={"mode": "live"})
    with pytest.raises(BrandProbeError, match="explicit approval"):
        asyncio.run(execute(tmp_path, plan, key="test", approved=False))
    assert not (tmp_path / ".brandprobe").exists()


def test_expired_plan_cannot_execute(config, tmp_path):
    plan = plan_for(config).model_copy(
        update={"mode": "live", "created_at": "2020-01-01T00:00:00+00:00"}
    )
    with pytest.raises(BrandProbeError, match="expired"):
        asyncio.run(execute(tmp_path, plan, key="test", approved=True))


def test_live_wire_has_no_brand_metadata_and_search_is_disabled(config):
    def handler(request):
        import json

        payload = json.loads(request.content)
        assert config.brand.name not in str(payload)
        assert payload["tools"] == [] and payload["plugins"] == []
        assert payload["provider"]["allow_fallbacks"] is False
        assert payload["max_tokens"] == 600
        return httpx.Response(
            200,
            json={
                "model": "model/version",
                "provider": "test",
                "choices": [
                    {
                        "message": {"content": "An independent answer"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"cost": 0.001, "prompt_tokens": 30, "completion_tokens": 10},
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await respond(
                client,
                "secret-test",
                config,
                ModelPrice(
                    id="model",
                    name="Test",
                    input_per_token="0.000001",
                    output_per_token="0.000002",
                ),
                config.prompts[1],
                1,
            )

    result = asyncio.run(run())
    assert result.status == "ok" and result.returned_model == "model/version"
    assert "secret-test" not in result.model_dump_json()


def test_unknown_billing_stops_remaining_dispatch(config, tmp_path, monkeypatch):
    config.concurrency = 1
    plan = plan_for(config).model_copy(update={"mode": "live"})
    called = []

    async def failed(client, key, config, price, prompt, repetition):
        called.append(1)
        return Observation(
            model=price.id,
            prompt=prompt,
            repetition=repetition,
            status="error",
            error="timeout",
        )

    monkeypatch.setattr("brandprobe.engine.llm.respond", failed)
    audit = asyncio.run(execute(tmp_path, plan, key="test", approved=True))
    assert len(called) == 1
    assert audit.status == "partial"
    assert sum(o.status == "skipped" for o in audit.observations) == 11


def test_budget_prevents_dispatch(config, tmp_path, monkeypatch):
    plan = plan_for(config).model_copy(update={"mode": "live"})
    plan.config.budget_usd = Decimal("0.01")
    plan.reservations = {k: Decimal("1") for k in plan.reservations}

    async def forbidden(*args):
        pytest.fail("Over-budget request dispatched")

    monkeypatch.setattr("brandprobe.engine.llm.respond", forbidden)
    audit = asyncio.run(execute(tmp_path, plan, key="test", approved=True))
    assert all(o.status == "skipped" for o in audit.observations)


def test_exports_escape_model_content(config):
    audit = Audit(
        plan=plan_for(config),
        observations=[
            Observation(
                model="demo",
                prompt=config.prompts[0],
                repetition=1,
                status="ok",
                text='=HYPERLINK("evil") <script>alert(1)</script>',
            )
        ],
    )
    assert "<script>alert" not in html_report(audit)
    assert "&lt;script&gt;" in html_report(audit)
    assert "'=HYPERLINK" in csv_report(audit)


def test_web_requires_token_and_allows_fixture_run(config, tmp_path):
    (tmp_path / "examples").mkdir()
    (tmp_path / "examples/sots.toml").write_text(Path("examples/sots.toml").read_text())
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=never-render-this-key\n")
    with TestClient(create_app(tmp_path)) as client:
        setup = client.get("/api/setup")
        assert setup.json()["key_configured"]
        assert "never-render-this-key" not in setup.text
        assert (
            client.post(
                "/api/plans", json={"config": config.model_dump(mode="json")}
            ).status_code
            == 403
        )
        headers = {"x-brandprobe-token": setup.json()["token"]}
        preview = client.post(
            "/api/plans",
            headers=headers,
            json={"config": config.model_dump(mode="json"), "demo": True},
        )
        assert preview.status_code == 200
        run = client.post(
            "/api/runs", headers=headers, json={"plan_id": preview.json()["id"]}
        )
        assert run.status_code == 200
        audit_id = run.json()["id"]
        for _ in range(30):
            result = client.get(f"/api/runs/{audit_id}")
            if result.json()["audit"]["status"] != "running":
                break
        assert result.json()["audit"]["status"] == "complete"
        assert client.get(f"/api/runs/{audit_id}/export/csv").status_code == 200
        assert client.get("/", headers={"host": "evil.example"}).status_code == 400


def test_sots_configuration_does_not_prime_discovery():
    config = load_config(Path("examples/sots.toml"))
    assert len(config.prompts) == 15
    assert sum(p.kind == "recognition" for p in config.prompts) == 3


def test_catalog_keeps_optional_search_models_and_prices_reasoning():
    from brandprobe.llm import catalog

    def handler(request):
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "vendor/model",
                        "name": "Model",
                        "pricing": {
                            "prompt": "0.000001",
                            "completion": "0.000002",
                            "internal_reasoning": "0.000003",
                            "web_search": "0.01",
                        },
                        "architecture": {"output_modalities": ["text"]},
                    },
                    {
                        "id": "vendor/model:online",
                        "name": "Search model",
                        "pricing": {"prompt": "0", "completion": "0"},
                    },
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await catalog(client)

    models = asyncio.run(run())
    assert len(models) == 1
    assert models[0].reasoning_per_token == Decimal("0.000003")


def test_planner_refuses_unaffordable_live_run(config, monkeypatch):
    config.models = ["vendor/model"]
    config.budget_usd = Decimal("0.01")

    async def expensive_catalog(client):
        return [
            ModelPrice(
                id="vendor/model",
                name="Expensive model",
                input_per_token="0.01",
                output_per_token="0.01",
            )
        ]

    monkeypatch.setattr("brandprobe.planning.catalog", expensive_catalog)

    async def run():
        async with httpx.AsyncClient() as client:
            return await make_plan(config, False, client)

    with pytest.raises(BrandProbeError, match="exceeds budget"):
        asyncio.run(run())


def test_empty_truncation_stops_only_affected_model(config, tmp_path, monkeypatch):
    config.concurrency = 1
    plan = plan_for(config).model_copy(update={"mode": "live"})
    calls = []

    async def response(client, key, config, price, prompt, repetition):
        calls.append(price.id)
        empty = price.id == plan.prices[0].id
        return Observation(
            model=price.id,
            prompt=prompt,
            repetition=repetition,
            status="truncated" if empty else "ok",
            text="" if empty else "An answer",
            cost_usd=Decimal(0),
        )

    monkeypatch.setattr("brandprobe.engine.llm.respond", response)
    audit = asyncio.run(execute(tmp_path, plan, key="test", approved=True))
    assert calls.count(plan.prices[0].id) == 1
    assert calls.count(plan.prices[1].id) == 4
    assert sum(o.status == "skipped" for o in audit.observations) == 3
    assert all(
        "empty token-limited" in o.error
        for o in audit.observations
        if o.status == "skipped"
    )
