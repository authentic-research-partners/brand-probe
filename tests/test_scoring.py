import asyncio
from decimal import Decimal

import httpx
import pytest

from brandprobe.analyze import validate_assessment
from brandprobe.llm import complete
from brandprobe.report import report_data
from brandprobe.schemas import (
    Assessment,
    Audit,
    AuditConfig,
    Brand,
    Evaluation,
    ModelPrice,
    Observation,
    Plan,
    Prompt,
)


def answer(text, kind="recognition"):
    return Observation(
        model="test",
        prompt=Prompt(
            id="q",
            kind=kind,
            text="What is the Society of Teen Scientists?"
            if kind == "recognition"
            else "Which programs offer physics research?",
        ),
        repetition=1,
        status="ok",
        text=text,
        mention="Society of Teen Scientists" in text,
    )


def test_explicit_ignorance_can_be_mentioned_but_not_recognized():
    quote = (
        "I don’t have reliable, specific information about Society of Teen Scientists."
    )
    o = answer(quote)
    v = Assessment(
        recognition="unrecognized",
        recommendation="not_applicable",
        recognition_quote=quote,
        recommendation_quote="",
        rationale="The answer explicitly disclaims knowledge.",
    )
    assert validate_assessment(v, o).recognition == "unrecognized"
    assert o.mention


def test_discouragement_is_not_a_recommendation():
    quote = "I would not recommend Society of Teen Scientists."
    v = Assessment(
        recognition="not_applicable",
        recommendation="discouraged",
        recognition_quote="",
        recommendation_quote=quote,
        rationale="Negative advice about the target.",
    )
    assert (
        validate_assessment(v, answer(quote, "discovery")).recommendation
        == "discouraged"
    )


def test_evidence_must_be_in_answer_not_question():
    o = answer("I cannot identify that organization.")
    v = Assessment(
        recognition="recognized",
        recommendation="neutral",
        recognition_quote="Society of Teen Scientists",
        recommendation_quote="Society of Teen Scientists",
        rationale="Wrong quote",
    )
    with pytest.raises(ValueError, match="not present"):
        validate_assessment(v, o)


def test_absence_cannot_overrule_exact_mention():
    o = answer("Society of Teen Scientists is mentioned here.", "discovery")
    v = Assessment(
        recognition="not_applicable",
        recommendation="absent",
        recognition_quote="",
        recommendation_quote="",
        rationale="Wrong absence",
    )
    with pytest.raises(ValueError, match="conflicts"):
        validate_assessment(v, o)


def test_truncation_preserves_receipt_even_when_answer_is_empty():
    async def run():
        transport = httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "model": "test",
                    "choices": [
                        {"message": {"content": ""}, "finish_reason": "length"}
                    ],
                    "usage": {
                        "cost": 0.012,
                        "completion_tokens": 600,
                        "prompt_tokens": 50,
                    },
                },
            )
        )
        async with httpx.AsyncClient(transport=transport) as client:
            return await complete(
                client,
                "test",
                ModelPrice(
                    id="test", name="Test", input_per_token=0, output_per_token=0
                ),
                [{"role": "user", "content": "test"}],
                600,
            )

    result = asyncio.run(run())
    assert result.status == "truncated"
    assert result.cost_usd == Decimal("0.012")
    assert result.output_tokens == 600
    assert result.raw


def test_unmeasured_and_unassessed_are_explicit_and_scoring_cost_is_included():
    o = answer("I do not know Society of Teen Scientists.")
    o.cost_usd = Decimal("0.01")
    o.evaluation = Evaluation(status="error", model="judge", cost_usd=Decimal("0.002"))
    config = AuditConfig(
        brand=Brand(
            name="Society of Teen Scientists",
            domain="teenscientists.org",
            audience="Teens",
        ),
        prompts=[
            o.prompt,
            Prompt(
                id="discovery",
                kind="discovery",
                text="Which physics programs are available for teens?",
            ),
        ],
    )
    audit = Audit(
        plan=Plan(
            mode="live",
            config=config,
            prices=[],
            requests=2,
            estimated_usd=0,
            reserved_usd=0,
            reservations={},
        ),
        status="partial",
        observations=[o],
    )
    data = report_data(audit)
    assert data["known_cost_usd"] == "0.012"
    assert data["semantic_summary"][0]["unassessed"] == 1
    assert data["semantic_summary"][0]["assessed"] == 0
    assert any("Discovery is unmeasured" in w for w in data["warnings"])


def test_previous_scoring_receipts_are_not_lost_on_review():
    o = answer("I do not know Society of Teen Scientists.")
    o.cost_usd = Decimal("0.01")
    o.evaluation = Evaluation(
        status="complete",
        cost_usd=Decimal("0.002"),
        previous_attempts=[
            {"status": "error", "cost_usd": "0.003"},
            {"status": "error", "cost_usd": None},
        ],
    )
    config = AuditConfig(
        brand=Brand(
            name="Society of Teen Scientists",
            domain="teenscientists.org",
            audience="Teens",
        ),
        prompts=[o.prompt],
    )
    audit = Audit(
        plan=Plan(
            mode="live",
            config=config,
            prices=[],
            requests=1,
            estimated_usd=0,
            reserved_usd=0,
            reservations={},
        ),
        observations=[o],
    )
    data = report_data(audit)
    assert data["known_cost_usd"] == "0.015"
    assert data["unknown_evaluation_costs"] == 1


def test_provider_defaults_can_not_silently_override_requested_effort():
    async def run():
        def handler(request):
            import json

            assert json.loads(request.content)["reasoning"] == {"effort": "low"}
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": "Answer"}, "finish_reason": "stop"}
                    ],
                    "usage": {"cost": 0},
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await complete(
                client,
                "test",
                ModelPrice(
                    id="test", name="Test", input_per_token=0, output_per_token=0
                ),
                [{"role": "user", "content": "test"}],
                2000,
                reasoning_effort="low",
            )

    assert asyncio.run(run()).status == "ok"


def test_running_report_does_not_present_missing_results_as_final():
    o = answer("", "discovery")
    o.status = "truncated"
    config = AuditConfig(
        brand=Brand(
            name="Society of Teen Scientists",
            domain="teenscientists.org",
            audience="Teens",
        ),
        prompts=[o.prompt],
    )
    audit = Audit(
        plan=Plan(
            mode="live",
            config=config,
            prices=[],
            requests=3,
            estimated_usd=0,
            reserved_usd=0,
            reservations={},
        ),
        observations=[o],
    )
    warnings = report_data(audit)["warnings"]
    assert any("Run in progress" in w for w in warnings)
    assert not any(
        "Incomplete audit" in w or "Discovery is unmeasured" in w for w in warnings
    )
    audit.status = "partial"
    assert any("Discovery is unmeasured" in w for w in report_data(audit)["warnings"])
