"""Make the exact paid work reviewable before dispatch."""

from decimal import Decimal
import httpx
from brandprobe.analyze import RUBRIC, FACT_RUBRIC
from brandprobe.exceptions import BrandProbeError
from brandprobe.fixtures import DEMO_MODELS
from brandprobe.llm import catalog
from brandprobe.schemas import AuditConfig, Plan, WorkItem
from brandprobe.templates import messages


async def make_plan(
    config: AuditConfig,
    demo: bool,
    client: httpx.AsyncClient,
    work_items: list[WorkItem] | None = None,
    parent_audit_id: str | None = None,
) -> Plan:
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
    allowed = {
        (p.id, q.id, r)
        for p in selected
        for q in config.prompts
        for r in range(1, config.repetitions + 1)
    }
    if work_items is not None:
        requested = {(w.model, w.prompt_id, w.repetition) for w in work_items}
        if (
            not requested
            or not requested <= allowed
            or len(requested) != len(work_items)
        ):
            raise BrandProbeError(
                "Recovery work no longer matches available models and questions."
            )
    else:
        requested = allowed
    reservations = {}
    estimate = Decimal(0)
    for price in selected:
        for p in config.prompts:
            repeats = sum(
                (price.id, p.id, r) in requested
                for r in range(1, config.repetitions + 1)
            )
            if not repeats:
                continue
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
            ) * repeats
    requests = len(requested)
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
            + len(FACT_RUBRIC.encode())
            + sum(len(f.model_dump_json().encode()) for f in config.facts)
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
    search_requests = len(config.search.queries) if not demo else 0
    if search_requests and not config.search.rate_confirmed:
        raise BrandProbeError(
            "Confirm your Brave subscription price before previewing search requests."
        )
    search_reserved = config.search.price_per_request_usd * search_requests
    total = (
        sum(
            (reservations[f"{model}|{prompt}"] for model, prompt, _ in requested),
            Decimal(0),
        )
        + evaluation_reservation * requests
        + search_reserved
    )
    if not demo and (config.budget_usd <= 0 or total > config.budget_usd):
        raise BrandProbeError(
            f"Conservative reservation ${total:.4f} exceeds budget ${config.budget_usd}. Reduce the run or raise its budget."
        )
    return Plan(
        mode="demo" if demo else "live",
        config=config,
        prices=selected,
        requests=requests,
        search_requests=search_requests,
        search_reserved_usd=search_reserved,
        work_items=work_items,
        parent_audit_id=parent_audit_id,
        estimated_usd=estimate + search_reserved,
        reserved_usd=total,
        reservations=reservations,
        evaluator_price=evaluator,
        evaluation_requests=requests if evaluator else 0,
        evaluation_reservation=evaluation_reservation,
    )
