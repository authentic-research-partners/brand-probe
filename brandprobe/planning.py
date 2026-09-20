"""Make the exact paid work reviewable before dispatch."""

from decimal import Decimal
import httpx
from brandprobe.analyze import RUBRIC
from brandprobe.exceptions import BrandProbeError
from brandprobe.fixtures import DEMO_MODELS
from brandprobe.llm import catalog
from brandprobe.schemas import AuditConfig, Plan
from brandprobe.templates import messages


async def make_plan(config: AuditConfig, demo: bool, client: httpx.AsyncClient) -> Plan:
    prices = DEMO_MODELS if demo else await catalog(client)
    if not demo and not config.models:
        raise BrandProbeError(
            "Select at least one model from the catalog before creating a live plan."
        )
    selected = prices if demo else [p for p in prices if p.id in config.models]
    if not demo and len(selected) != len(config.models):
        raise BrandProbeError(
            "A selected model is unavailable or unsuitable for no-search tests. Refresh the model catalog."
        )
    reservations = {}
    estimate = Decimal(0)
    for price in selected:
        for p in config.prompts:
            # UTF-8 bytes plus generous chat framing, not a tokenizer claim.
            size = (
                sum(len(m["content"].encode("utf-8")) for m in messages(config, p))
                + 512
            )
            reserve = (
                size * price.input_per_token
                + config.max_tokens
                * (price.output_per_token + price.reasoning_per_token)
                + price.per_request
            ) * Decimal("1.25")
            reservations[f"{price.id}|{p.id}"] = reserve
            estimate += (
                Decimal(size) / 3 * price.input_per_token
                + Decimal(config.max_tokens)
                / 2
                * (price.output_per_token + price.reasoning_per_token)
                + price.per_request
            ) * config.repetitions
    requests = len(selected) * len(config.prompts) * config.repetitions
    evaluator = None
    evaluation_reservation = Decimal(0)
    if not demo and config.evaluator_model:
        evaluator = next((p for p in prices if p.id == config.evaluator_model), None)
        if evaluator is None:
            raise BrandProbeError(
                "Evaluator model is unavailable. Choose a model from the catalog."
            )
        # Conservative upper bound including JSON schema, escaped response, question and brand context.
        # At most 8 serialized bytes per generated token, plus explicit framing.
        size = (
            len(RUBRIC.encode())
            + len(config.brand.model_dump_json().encode())
            + max(len(p.text.encode()) for p in config.prompts)
            + config.max_tokens * 8
            + 6000
        )
        evaluation_reservation = (
            size * evaluator.input_per_token
            + config.evaluator_max_tokens
            * (evaluator.output_per_token + evaluator.reasoning_per_token)
            + evaluator.per_request
        ) * Decimal("1.25")
        estimate += evaluation_reservation * requests / 2
    if not demo and config.reasoning_effort:
        for model in [*selected, *([evaluator] if evaluator else [])]:
            if (
                model.supported_efforts is None
                or config.reasoning_effort not in model.supported_efforts
            ):
                raise BrandProbeError(
                    f"{model.id} does not advertise {config.reasoning_effort} reasoning. Choose provider defaults or another effort."
                )
    total = (
        sum(reservations.values(), Decimal(0)) * config.repetitions
        + evaluation_reservation * requests
    )
    if not demo and (config.budget_usd <= 0 or total > config.budget_usd):
        raise BrandProbeError(
            f"Conservative reservation ${total:.4f} exceeds budget ${config.budget_usd}. Reduce the run or raise its budget."
        )
    return Plan(
        mode="demo" if demo else "live",
        config=config,
        prices=selected,
        requests=len(selected) * len(config.prompts) * config.repetitions,
        estimated_usd=estimate,
        reserved_usd=total,
        reservations=reservations,
        evaluator_price=evaluator,
        evaluation_requests=requests if evaluator else 0,
        evaluation_reservation=evaluation_reservation,
    )
