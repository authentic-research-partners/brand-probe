"""Exclusive local worker lease and crash classification, with no paid retries."""

import fcntl
from contextlib import contextmanager
from pathlib import Path
from brandprobe.db import store
from brandprobe.exceptions import BrandProbeError
from brandprobe.schemas import Audit, Observation, SearchObservation, WorkItem, now


def work_items(audit: Audit) -> list[WorkItem]:
    return (
        audit.plan.work_items
        if audit.plan.work_items is not None
        else [
            WorkItem(model=m.id, prompt_id=p.id, repetition=r)
            for m in audit.plan.prices
            for p in audit.plan.config.prompts
            for r in range(1, audit.plan.config.repetitions + 1)
        ]
    )


@contextmanager
def lease(root: Path):
    folder = root / ".brandprobe"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "worker.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise BrandProbeError(
                "Another BrandProbe worker is active in this workspace."
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def recover(root: Path, exclude_id: str | None = None) -> int:
    """Caller holds lease. Missing legacy entries have unknown dispatch state."""
    count = 0
    for audit in store.running(root):
        if audit.id == exclude_id:
            continue
        mark_interrupted(audit)
        store.save(root, audit)
        count += 1
    return count


def mark_interrupted(audit: Audit) -> None:
    recorded = {(o.model, o.prompt.id, o.repetition) for o in audit.observations}
    prompts = {p.id: p for p in audit.plan.config.prompts}
    for item in work_items(audit):
        if (item.model, item.prompt_id, item.repetition) not in recorded:
            audit.observations.append(
                Observation(
                    model=item.model,
                    prompt=prompts[item.prompt_id],
                    repetition=item.repetition,
                    status="skipped" if audit.dispatch_journal else "interrupted",
                    error="Not dispatched before the worker stopped."
                    if audit.dispatch_journal
                    else "Legacy run has no dispatch journal; request and billing state unknown.",
                )
            )
    recorded_queries = {r.query for r in audit.search_observations}
    for query in audit.plan.config.search.queries:
        if query not in recorded_queries:
            audit.search_observations.append(
                SearchObservation(
                    query=query,
                    status="skipped" if audit.dispatch_journal else "interrupted",
                    error="No saved search receipt. Never-dispatched searches are not included in generation continuation.",
                )
            )
    audit.status = "interrupted"
    audit.completed_at = now()
    audit.recovery_note = "Recovered after worker exit. In-flight requests may have been billed. Only never-dispatched generation work is eligible for a fresh approved continuation; original evidence is preserved."


def remaining(audit: Audit) -> list[WorkItem]:
    if audit.status != "interrupted" or not audit.dispatch_journal:
        raise BrandProbeError(
            "Only interrupted runs with a dispatch journal can continue safely."
        )
    return [
        WorkItem(model=o.model, prompt_id=o.prompt.id, repetition=o.repetition)
        for o in audit.observations
        if o.status == "skipped"
    ]
