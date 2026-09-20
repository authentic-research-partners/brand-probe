"""Brave web search baseline, independent of model acquisition and scoring."""

import httpx
from brandprobe.schemas import SearchConfig, SearchHit, SearchObservation


async def search(
    client: httpx.AsyncClient, key: str, config: SearchConfig, query: str
) -> SearchObservation:
    result = SearchObservation(query=query, status="error")
    try:
        response = await client.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": key, "Accept": "application/json"},
            params={
                "q": query,
                "count": config.count,
                "country": config.country,
                "search_lang": config.language,
                "spellcheck": "false",
            },
        )
        response.raise_for_status()
        result.raw = response.json()
        if (
            not isinstance(result.raw, dict)
            or result.raw.get("type") != "search"
            or "error" in result.raw
        ):
            raise ValueError("Invalid search response")
        # Missing web results are legitimate (e.g. an empty search), but malformed results aren't.
        rows = result.raw.get("web", {}).get("results", [])
        if not isinstance(rows, list):
            raise ValueError("Invalid results")
        result.results = [
            SearchHit(
                rank=i,
                title=row["title"],
                url=row["url"],
                description=row.get("description", ""),
            )
            for i, row in enumerate(rows[: config.count], 1)
        ]
        result.status = "ok"
        result.estimated_cost_usd = config.price_per_request_usd
    except httpx.HTTPStatusError as exc:
        result.error = f"Brave HTTP {exc.response.status_code}. Billing unknown; no automatic retry."
    except (httpx.RequestError, ValueError, TypeError, KeyError):
        result.error = "Search failed or returned malformed evidence. Billing unknown; no automatic retry."
    return result
