"""OpenRouter transport. Raw answers are evidence; no evaluator alters them."""

import httpx
from pydantic import ValidationError
from brandprobe.exceptions import BrandProbeError
from brandprobe.schemas import AuditConfig, Completion, ModelPrice, Observation, Prompt
from brandprobe.templates import messages

BASE = "https://openrouter.ai/api/v1"


async def catalog(client: httpx.AsyncClient) -> list[ModelPrice]:
    response = await client.get(f"{BASE}/models")
    response.raise_for_status()
    result = []
    for row in response.json()["data"]:
        if (
            row["id"].startswith("~")
            or "latest" in row["id"]
            or ":" in row["id"]
            or "@" in row["id"]
            or "search" in row["id"].lower()
            or "sonar" in row["id"].lower()
        ):
            continue
        if row.get("architecture", {}).get("output_modalities", ["text"]) != ["text"]:
            continue
        price = row.get("pricing", {})
        try:
            result.append(
                ModelPrice(
                    id=row["id"],
                    name=row["name"],
                    supported_efforts=row.get("reasoning", {}).get("supported_efforts"),
                    input_per_token=price["prompt"],
                    output_per_token=price["completion"],
                    per_request=price.get("request", "0"),
                    reasoning_per_token=price.get("internal_reasoning", "0"),
                )
            )
        except (KeyError, ValidationError):
            continue
    return result


async def complete(
    client: httpx.AsyncClient,
    key: str,
    price: ModelPrice,
    conversation: list[dict[str, str]],
    max_tokens: int,
    response_format: dict | None = None,
    reasoning_effort: str | None = None,
) -> Completion:
    if not key:
        raise BrandProbeError(
            "Add OPENROUTER_API_KEY to .env or .env.local before a live run."
        )
    payload = {
        "model": price.id,
        "messages": conversation,
        "max_tokens": max_tokens,
        "plugins": [],
        "tools": [],
        "stream": False,
        "provider": {
            "allow_fallbacks": False,
            "require_parameters": True,
            "max_price": {
                "prompt": float(price.input_per_token * 1000000),
                "completion": float(price.output_per_token * 1000000),
                "request": float(price.per_request),
            },
        },
    }
    if reasoning_effort is not None:
        payload["reasoning"] = {"effort": reasoning_effort}
    if response_format is not None:
        payload["response_format"] = response_format
    result = Completion(status="error")
    try:
        response = await client.post(
            f"{BASE}/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json=payload,
        )
        response.raise_for_status()
        raw = response.json()
        usage = raw.get("usage", {})
        # Preserve the receipt even when the content cannot be used.
        result = Completion(
            status="error",
            returned_model=raw.get("model", ""),
            provider=raw.get("provider", "unknown"),
            cost_usd=usage.get("cost"),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            raw=raw,
        )
        choice = raw["choices"][0]
        content = choice["message"].get("content")
        if choice.get("finish_reason") == "length":
            result.status = "truncated"
            result.text = content if isinstance(content, str) else ""
            result.error = "Token ceiling reached. Reasoning may have consumed the output budget; receipt preserved."
            return result
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Empty or non-text response")
        result.text = content
        if choice["message"].get("tool_calls"):
            raise ValueError("Unexpected tool call in no-search run")
        result.status = "ok" if choice.get("finish_reason") == "stop" else "truncated"
    except httpx.HTTPStatusError as exc:
        result.error = f"Provider HTTP {exc.response.status_code}; check model access and account balance. No automatic retry."
    except httpx.TimeoutException:
        result.error = "Provider request timed out; billing is unknown unless a receipt was returned. No automatic retry."
    except (
        httpx.RequestError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
        ValidationError,
    ) as exc:
        result.error = f"{type(exc).__name__}: request failed or response was invalid. No automatic retry; review the saved receipt if present."
    return result


async def respond(
    client: httpx.AsyncClient,
    key: str,
    config: AuditConfig,
    price: ModelPrice,
    prompt: Prompt,
    repetition: int,
) -> Observation:
    result = await complete(
        client,
        key,
        price,
        messages(config, prompt),
        config.max_tokens,
        reasoning_effort=config.reasoning_effort,
    )
    return Observation(
        model=price.id, prompt=prompt, repetition=repetition, **result.model_dump()
    )
