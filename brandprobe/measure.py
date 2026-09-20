"""Mechanical mentions only: a mention is not a recommendation."""

import re
from brandprobe.schemas import Brand, Observation


def find_mentions(text: str, brand: Brand) -> list[str]:
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
