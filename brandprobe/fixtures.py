"""Synthetic responses for exercising the pipeline, never market evidence."""

import asyncio
from decimal import Decimal
from brandprobe.schemas import AuditConfig, ModelPrice, Observation, Prompt

DEMO_MODELS = [
    ModelPrice(
        id=f"demo/{name}", name=f"Demo {name}", input_per_token=0, output_per_token=0
    )
    for name in ("Cedar", "Birch", "Willow")
]


async def respond(
    config: AuditConfig, model: str, prompt: Prompt, repetition: int
) -> Observation:
    await asyncio.sleep(0)
    present = (
        prompt.kind == "recognition"
        or (sum(map(ord, model + prompt.id)) + repetition) % 3 == 0
    )
    text = (
        f"SYNTHETIC DEMO RESPONSE. {config.brand.name} is named here solely to demonstrate mention tracking. This is not a real model assessment."
        if present
        else "SYNTHETIC DEMO RESPONSE. Compare program depth, mentor access, and eligibility. No target brand is named in this fixture."
    )
    return Observation(
        model=model,
        returned_model=model,
        provider="local fixture",
        prompt=prompt,
        repetition=repetition,
        status="ok",
        text=text,
        cost_usd=Decimal(0),
        raw={"fixture": True},
    )
