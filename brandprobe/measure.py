"""Mechanical mentions only: a mention is not a recommendation."""

import re
from brandprobe.schemas import Brand, Competitor, Observation, Audit


def find_mentions(text: str, brand: Brand | Competitor) -> list[str]:
    # Short ambiguous aliases are deliberately excluded from automatic matching.
    names = [brand.name, brand.domain, *(a for a in brand.aliases if len(a) >= 5)]
    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(n) for n in names if n) + r")(?!\w)", re.I
    )
    return list(
        dict.fromkeys(
            text[max(0, m.start() - 70) : min(len(text), m.end() + 110)]
            for m in pattern.finditer(text)
        )
    )


def summarize(observations: list[Observation]) -> list[dict]:
    rows = []
    for model in dict.fromkeys(o.model for o in observations):
        for kind in ("recognition", "discovery", "alternatives"):
            group = [
                o for o in observations if o.model == model and o.prompt.kind == kind
            ]
            if not group:
                continue
            valid = [o for o in group if o.status == "ok"]
            mentions = sum(o.mention for o in valid)
            rows.append(
                dict(
                    model=model,
                    kind=kind,
                    mentions=mentions,
                    successful=len(valid),
                    excluded=len(group) - len(valid),
                    rate=mentions / len(valid) if valid else None,
                )
            )
    return rows


def semantic_summary(observations: list[Observation]) -> list[dict]:
    rows = []
    for row in summarize(observations):
        group = [
            o
            for o in observations
            if o.model == row["model"]
            and o.prompt.kind == row["kind"]
            and o.status == "ok"
        ]
        assessments = [
            o.evaluation.assessment
            for o in group
            if o.evaluation
            and o.evaluation.status == "complete"
            and o.evaluation.assessment
        ]
        rows.append(
            {
                **row,
                "assessed": len(assessments),
                "unassessed": len(group) - len(assessments),
                "recognized": sum(a.recognition == "recognized" for a in assessments),
                "unrecognized": sum(
                    a.recognition == "unrecognized" for a in assessments
                ),
                "uncertain_recognition": sum(
                    a.recognition == "uncertain" for a in assessments
                ),
                "recommended": sum(
                    a.recommendation == "recommended" for a in assessments
                ),
                "discouraged": sum(
                    a.recommendation == "discouraged" for a in assessments
                ),
                "uncertain_recommendation": sum(
                    a.recommendation == "uncertain" for a in assessments
                ),
            }
        )
    return rows


def comparable(observation: Observation, brands: list[Brand | Competitor]) -> bool:
    return (
        observation.status == "ok"
        and observation.prompt.kind != "recognition"
        and not any(
            name.casefold() in observation.prompt.text.casefold()
            for brand in brands
            for name in [brand.name, brand.domain, *brand.aliases]
            if name
        )
    )


def competitor_summary(audit: Audit) -> list[dict]:
    """Compare exact mentions only on questions that name none of the compared brands."""
    brands: list[Brand | Competitor] = [
        audit.plan.config.brand,
        *audit.plan.config.competitors,
    ]
    rows = []
    for model in dict.fromkeys(o.model for o in audit.observations):
        group = [
            o
            for o in audit.observations
            if o.model == model and o.prompt.kind != "recognition"
        ]
        eligible = [o for o in group if comparable(o, brands)]
        for brand in brands:
            matched = [o for o in eligible if find_mentions(o.text, brand)]
            rows.append(
                dict(
                    model=model,
                    brand=brand.name,
                    mentions=len(matched),
                    successful=len(eligible),
                    excluded=len(group) - len(eligible),
                    observation_ids=[o.id for o in matched],
                )
            )
    return rows


def search_summary(audit: Audit) -> list[dict]:
    from urllib.parse import urlsplit

    def host(value):
        return (
            (urlsplit(value if "://" in value else "https://" + value).hostname or "")
            .lower()
            .removeprefix("www.")
        )

    rows = []
    brands: list[Brand | Competitor] = [
        audit.plan.config.brand,
        *audit.plan.config.competitors,
    ]
    for result in audit.search_observations:
        for brand in brands:
            domain = host(brand.domain)
            hits = [
                r.rank
                for r in result.results
                if domain
                and (host(r.url) == domain or host(r.url).endswith("." + domain))
            ]
            rows.append(
                dict(
                    query=result.query,
                    brand=brand.name,
                    status=result.status,
                    first_domain_rank=min(hits) if hits else None,
                    returned_results=len(result.results),
                )
            )
    return rows
