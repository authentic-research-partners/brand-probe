"""Orchestrate acquisition, mechanical measurement, and durable evidence."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import httpx
from brandprobe import fixtures, llm
from brandprobe.analyze import evaluate
from brandprobe.db import store
from brandprobe.exceptions import BrandProbeError
from brandprobe.measure import find_mentions
from brandprobe.schemas import Audit, Evaluation, Observation, Plan, now


async def execute(
    root: Path,
    plan: Plan,
    key: str = "",
    approved: bool = False,
    audit: Audit | None = None,
) -> Audit:
    if plan.mode == "live":
        if not approved or not key:
            raise BrandProbeError(
                "A live run needs explicit approval of its plan and a configured API key."
            )
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(plan.created_at)
        ).total_seconds()
        if age < 0 or age > 900:
            raise BrandProbeError(
                "This price preview expired. Create a new plan before approving."
            )
    audit = audit or Audit(plan=plan)
    store.save(root, audit)
    semaphore = asyncio.Semaphore(plan.config.concurrency)
    lock = asyncio.Lock()
    allocated = Decimal(0)
    halt = False
    blocked_models: set[str] = set()

    async with httpx.AsyncClient(timeout=90) as client:

        async def one(price, prompt, repetition):
            nonlocal allocated, halt
            async with semaphore:
                reserve = plan.reservations[f"{price.id}|{prompt.id}"]
                async with lock:
                    blocked = (
                        halt
                        or price.id in blocked_models
                        or allocated + reserve > plan.config.budget_usd
                    )
                    if not blocked:
                        allocated += reserve
                if blocked:
                    observation = Observation(
                        model=price.id,
                        prompt=prompt,
                        repetition=repetition,
                        status="skipped",
                        error=(
                            "Model stopped after an empty token-limited response. Lower reasoning effort or increase the output token limit in a new preview."
                            if price.id in blocked_models
                            else "Stopped before dispatch because the budget or billing certainty changed."
                        ),
                    )
                else:
                    observation = (
                        await fixtures.respond(
                            plan.config, price.id, prompt, repetition
                        )
                        if plan.mode == "demo"
                        else await llm.respond(
                            client, key, plan.config, price, prompt, repetition
                        )
                    )
                    # Keep the full reservation charged against this run even when actual usage is less.
                    # Unknown billing stops further dispatch; in-flight requests retain their reservation.
                    if plan.mode == "live" and (
                        observation.cost_usd is None or observation.cost_usd > reserve
                    ):
                        halt = True
                    if (
                        observation.status == "truncated"
                        and not observation.text.strip()
                    ):
                        blocked_models.add(price.id)
                    observation.evidence = find_mentions(
                        observation.text, plan.config.brand
                    )
                    observation.mention = bool(observation.evidence)
                audit.observations.append(observation)
                store.save(root, audit)

        try:
            await asyncio.gather(
                *(
                    one(price, p, repeat)
                    for price in plan.prices
                    for p in plan.config.prompts
                    for repeat in range(1, plan.config.repetitions + 1)
                )
            )
            # Acquisition completes first. Scoring never changes the observed answer or mention count.
            for observation in audit.observations:
                if plan.mode == "demo":
                    observation.evaluation = Evaluation(
                        status="demo",
                        error="Synthetic fixture; not eligible for semantic brand findings.",
                    )
                elif plan.evaluator_price and observation.status == "ok":
                    reserve = plan.evaluation_reservation
                    if halt or allocated + reserve > plan.config.budget_usd:
                        observation.evaluation = Evaluation(
                            status="skipped",
                            error="Scoring stopped because budget or billing is uncertain.",
                        )
                    else:
                        allocated += reserve
                        observation.evaluation = await evaluate(
                            client, key, plan.config, plan.evaluator_price, observation
                        )
                        receipt = observation.evaluation.cost_usd
                        if receipt is None or receipt > reserve:
                            halt = True
                    store.save(root, audit)
                    if not halt:
                        await asyncio.sleep(plan.config.evaluation_interval_seconds)
            audit.status = (
                "complete"
                if all(
                    o.status == "ok"
                    and (
                        not plan.evaluator_price
                        or (
                            o.evaluation is not None
                            and o.evaluation.status == "complete"
                        )
                    )
                    for o in audit.observations
                )
                else "partial"
            )
        except BaseException:
            audit.status = "interrupted"
            store.save(root, audit)
            raise
    audit.completed_at = now()
    store.save(root, audit)
    return audit
