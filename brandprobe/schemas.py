"""Validated contracts shared by providers, persistence, CLI and web."""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Brand(Record):
    name: str = Field(min_length=2, max_length=150)
    domain: str = Field(min_length=3, max_length=250)
    aliases: list[str] = Field(default_factory=list)
    audience: str = Field(min_length=3, max_length=1000)
    market: str = Field(default="United States", max_length=200)
    language: str = Field(default="English", max_length=100)


class Competitor(Record):
    name: str = Field(min_length=2, max_length=150)
    domain: str = Field(min_length=3, max_length=250)
    aliases: list[str] = Field(default_factory=list, max_length=10)


class BrandFact(Record):
    id: str = Field(min_length=1, max_length=80)
    statement: str = Field(min_length=10, max_length=1500)
    source_url: str = Field(pattern=r"^https?://", max_length=2000)
    reviewed_at: str = Field(min_length=10, max_length=10)

    @field_validator("reviewed_at")
    @classmethod
    def review_date(cls, value: str) -> str:
        datetime.strptime(value, "%Y-%m-%d")
        return value


class SearchConfig(Record):
    queries: list[str] = Field(default_factory=list, max_length=20)
    country: str = Field(default="US", pattern=r"^[A-Z]{2,3}$")
    language: str = Field(default="en", pattern=r"^[a-z-]{2,10}$")
    count: int = Field(default=10, ge=1, le=20)
    # User's subscription rate, never represented as a provider billing receipt.
    price_per_request_usd: Decimal = Field(
        default=Decimal("0.005"), ge=0, le=1, allow_inf_nan=False
    )
    rate_confirmed: bool = False

    @field_validator("queries")
    @classmethod
    def valid_queries(cls, values: list[str]) -> list[str]:
        if any(not q.strip() or len(q) > 400 or len(q.split()) > 50 for q in values):
            raise ValueError(
                "Search queries must be nonempty and at most 400 characters / 50 words."
            )
        if len(set(values)) != len(values):
            raise ValueError("Search queries must be distinct.")
        return values


class WorkItem(Record):
    model: str
    prompt_id: str
    repetition: int


class Prompt(Record):
    id: str = Field(min_length=1, max_length=80)
    kind: Literal["recognition", "discovery", "alternatives"]
    text: str = Field(min_length=10, max_length=4000)


class AuditConfig(Record):
    brand: Brand
    competitors: list[Competitor] = Field(default_factory=list, max_length=10)
    facts: list[BrandFact] = Field(default_factory=list, max_length=10)
    facts_approved: bool = False
    search: SearchConfig = Field(default_factory=SearchConfig)
    prompts: list[Prompt] = Field(min_length=1, max_length=50)
    models: list[str] = Field(default_factory=list, max_length=6)
    repetitions: int = Field(default=3, ge=1, le=5)
    reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    evaluator_model: str | None = None
    evaluation_interval_seconds: float = Field(default=0, ge=0, le=60)
    evaluator_max_tokens: int = Field(default=1200, ge=256, le=2000)
    max_tokens: int = Field(default=600, ge=64, le=16384)
    concurrency: int = Field(default=3, ge=1, le=6)
    budget_usd: Decimal = Field(default=Decimal("5"), ge=0, le=50, allow_inf_nan=False)

    @field_validator("models")
    @classmethod
    def plain_models(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(":" in m or "@" in m for m in values):
            raise ValueError(
                "Use distinct plain model IDs, without online variants or presets."
            )
        return values

    @model_validator(mode="after")
    def clean_prompts(self) -> "AuditConfig":
        if len({p.id for p in self.prompts}) != len(self.prompts):
            raise ValueError("Prompt IDs must be unique.")
        identities = [
            self.brand.name.casefold(),
            *(c.name.casefold() for c in self.competitors),
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("Target and competitor names must be distinct.")
        if len({f.id for f in self.facts}) != len(self.facts):
            raise ValueError("Fact IDs must be unique.")
        if self.facts and (not self.facts_approved or not self.evaluator_model):
            raise ValueError(
                "Approve the reference facts and select a scoring model before fact checking."
            )
        names = [self.brand.name, self.brand.domain, *self.brand.aliases]
        for p in self.prompts:
            if p.kind != "recognition" and any(
                n.casefold() in p.text.casefold() for n in names if n
            ):
                raise ValueError(
                    f"Unbranded prompt {p.id} contains a target name or alias."
                )
        return self


class ModelPrice(Record):
    id: str
    name: str
    supported_efforts: list[str] | None = None
    input_per_token: Decimal = Field(ge=0, allow_inf_nan=False)
    output_per_token: Decimal = Field(ge=0, allow_inf_nan=False)
    reasoning_per_token: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)
    per_request: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)


class Plan(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    created_at: str = Field(default_factory=now)
    mode: Literal["demo", "live"]
    config: AuditConfig
    prices: list[ModelPrice]
    requests: int
    estimated_usd: Decimal
    reserved_usd: Decimal
    # Price caps enforced in the provider payload; this is still not a billing guarantee.
    reservations: dict[str, Decimal]
    evaluator_price: ModelPrice | None = None
    evaluation_requests: int = 0
    evaluation_reservation: Decimal = Decimal(0)
    search_requests: int = 0
    search_reserved_usd: Decimal = Decimal(0)
    work_items: list[WorkItem] | None = None
    parent_audit_id: str | None = None


class FactCheck(Record):
    fact_id: str
    verdict: Literal["supported", "contradicted", "not_addressed", "uncertain"]
    answer_quote: str
    reference_quote: str
    rationale: str = Field(max_length=800)


class Assessment(Record):
    fact_checks: list[FactCheck] = Field(default_factory=list, max_length=10)
    recognition: Literal["recognized", "unrecognized", "uncertain", "not_applicable"]
    recommendation: Literal[
        "recommended", "discouraged", "neutral", "uncertain", "absent", "not_applicable"
    ]
    recognition_quote: str
    recommendation_quote: str
    rationale: str = Field(max_length=1500)


class Evaluation(Record):
    status: Literal["complete", "error", "skipped", "demo"]
    model: str = ""
    returned_model: str = ""
    provider: str = ""
    timestamp: str = Field(default_factory=now)
    reasoning_effort: str | None = None
    rubric_version: str = "brand-context-v2"
    previous_attempts: list[dict] = Field(default_factory=list)
    assessment: Assessment | None = None
    error: str = ""
    cost_usd: Decimal | None = None
    raw: dict = Field(default_factory=dict)


class Completion(Record):
    status: Literal["ok", "error", "truncated"]
    returned_model: str = ""
    provider: str = ""
    text: str = ""
    error: str = ""
    cost_usd: Decimal | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw: dict = Field(default_factory=dict)


class Observation(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    model: str
    returned_model: str = ""
    provider: str = ""
    prompt: Prompt
    repetition: int
    timestamp: str = Field(default_factory=now)
    status: Literal["ok", "error", "truncated", "skipped", "interrupted"]
    text: str = ""
    error: str = ""
    evaluation: Evaluation | None = None
    mention: bool = False
    evidence: list[str] = Field(default_factory=list)
    cost_usd: Decimal | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw: dict = Field(default_factory=dict)


class SearchHit(Record):
    rank: int
    title: str
    url: str
    description: str = ""


class SearchObservation(Record):
    query: str
    timestamp: str = Field(default_factory=now)
    status: Literal["ok", "error", "interrupted", "skipped", "demo"]
    results: list[SearchHit] = Field(default_factory=list)
    estimated_cost_usd: Decimal | None = None
    error: str = ""
    raw: dict = Field(default_factory=dict)


class Audit(Record):
    id: str = Field(default_factory=lambda: uuid4().hex)
    plan: Plan
    started_at: str = Field(default_factory=now)
    completed_at: str | None = None
    status: Literal["running", "complete", "partial", "interrupted"] = "running"
    observations: list[Observation] = Field(default_factory=list)
    search_observations: list[SearchObservation] = Field(default_factory=list)
    dispatch_journal: bool = False
    recovery_note: str = ""
