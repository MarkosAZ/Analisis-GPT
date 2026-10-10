"""Provider-independent quotes, proportional de-vig and v1 line eligibility.

Probabilities are fractions; edges and overround_pp are percentage points.
The proportional method divides each implied probability by their sum. It is
a transparent benchmark, not a claim to recover the true market probability.
Integer and Asian lines need settlement-aware probability models in v2.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

PROBABILITY_TOLERANCE = Decimal("1e-24")


class OutcomeStructure(StrEnum):
    TWO_WAY = "TWO_WAY"
    THREE_WAY = "THREE_WAY"


class LineType(StrEnum):
    HALF_LINE = "HALF_LINE"
    INTEGER_PUSH = "INTEGER_PUSH"
    ASIAN_QUARTER = "ASIAN_QUARTER"
    MONEYLINE = "MONEYLINE"
    THREE_WAY = "THREE_WAY"


def require_aware(value: datetime) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")


def require_decimal(value: Decimal) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("a finite Decimal is required")


@dataclass(frozen=True)
class MarketLine:
    kind: LineType
    value: Decimal | None = None

    def __post_init__(self) -> None:
        if self.kind in (LineType.MONEYLINE, LineType.THREE_WAY):
            if self.value is not None:
                raise ValueError("non-numeric markets must not carry a line")
            return
        if self.value is None:
            raise ValueError("numeric markets require a line")
        require_decimal(self.value)
        fraction = abs(self.value) % 1
        allowed = {
            LineType.HALF_LINE: (Decimal("0.5"),),
            LineType.INTEGER_PUSH: (Decimal(0),),
            LineType.ASIAN_QUARTER: (Decimal("0.25"), Decimal("0.75")),
        }
        if self.kind not in allowed or fraction not in allowed[self.kind]:
            raise ValueError("line value does not match its settlement type")

    @property
    def eligible_v1(self) -> bool:
        return self.kind in (LineType.HALF_LINE, LineType.MONEYLINE, LineType.THREE_WAY)


@dataclass(frozen=True)
class MarketKey:
    event_cycle_id: UUID
    market_code: str
    line: MarketLine
    structure: OutcomeStructure
    outcome_codes: tuple[str, ...]
    subject_id: UUID | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome_codes", tuple(self.outcome_codes))
        if not isinstance(self.structure, OutcomeStructure):
            raise ValueError("market structure must be TWO_WAY or THREE_WAY")
        expected_count = 2 if self.structure == OutcomeStructure.TWO_WAY else 3
        if not self.market_code or len(self.outcome_codes) != expected_count:
            raise ValueError("market structure requires a complete outcome definition")
        if len(set(self.outcome_codes)) != expected_count or not all(self.outcome_codes):
            raise ValueError("outcome codes must be distinct and nonempty")
        if self.line.kind == LineType.THREE_WAY and expected_count != 3:
            raise ValueError("THREE_WAY requires three outcomes")
        if self.line.kind == LineType.MONEYLINE and expected_count != 2:
            raise ValueError("MONEYLINE requires two outcomes; use THREE_WAY for draws")


@dataclass(frozen=True)
class QuoteOutcome:
    code: str
    decimal_odds: Decimal

    def __post_init__(self) -> None:
        require_decimal(self.decimal_odds)
        if not self.code or self.decimal_odds <= 1:
            raise ValueError("decimal odds must exceed one and identify an outcome")


@dataclass(frozen=True)
class QuoteSnapshot:
    quote_id: UUID
    key: MarketKey
    bookmaker: str
    captured_at: datetime
    available_at: datetime
    outcomes: tuple[QuoteOutcome, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcomes", tuple(self.outcomes))
        require_aware(self.captured_at)
        require_aware(self.available_at)
        if self.available_at < self.captured_at:
            raise ValueError("observed quote cannot be available before capture")
        if not self.bookmaker:
            raise ValueError("bookmaker is required")
        codes = tuple(outcome.code for outcome in self.outcomes)
        if len(set(codes)) != len(codes) or set(codes) != set(self.key.outcome_codes):
            raise ValueError("quote must contain every market outcome exactly once")

    def price(self, outcome_code: str) -> Decimal:
        return next(
            outcome.decimal_odds for outcome in self.outcomes if outcome.code == outcome_code
        )


@dataclass(frozen=True)
class OutcomeProbability:
    code: str
    probability: Decimal

    def __post_init__(self) -> None:
        require_decimal(self.probability)
        if not self.code or not 0 <= self.probability <= 1:
            raise ValueError("probabilities must be between zero and one")


def validate_probabilities(values: tuple[OutcomeProbability, ...]) -> None:
    if len(values) not in (2, 3) or len({value.code for value in values}) != len(values):
        raise ValueError("a complete two-way or three-way distribution is required")
    # Decimal division can round at its 28-digit precision; this is numeric
    # tolerance only, never an edge or NO BET policy threshold.
    if abs(sum((value.probability for value in values), Decimal(0)) - 1) > PROBABILITY_TOLERANCE:
        raise ValueError("outcome probabilities must sum to one")


@dataclass(frozen=True)
class MarketBenchmark:
    quote: QuoteSnapshot
    implied: tuple[OutcomeProbability, ...]
    probabilities: tuple[OutcomeProbability, ...]
    overround_pp: Decimal
    method: str = "PROPORTIONAL_V1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "implied", tuple(self.implied))
        object.__setattr__(self, "probabilities", tuple(self.probabilities))
        require_decimal(self.overround_pp)
        if not self.quote.key.line.eligible_v1:
            raise ValueError("push/Asian lines require settlement-aware probabilities")
        if self.method != "PROPORTIONAL_V1":
            raise ValueError("unsupported de-vig method")
        validate_probabilities(self.probabilities)
        codes = set(self.quote.key.outcome_codes)
        for values in (self.implied, self.probabilities):
            if len(values) != len(codes) or {item.code for item in values} != codes:
                raise ValueError("benchmark must contain every quote outcome exactly once")
        expected_implied = {
            item.code: Decimal(1) / item.decimal_odds for item in self.quote.outcomes
        }
        total = sum(expected_implied.values(), Decimal(0))
        if any(
            abs(item.probability - expected_implied[item.code]) > PROBABILITY_TOLERANCE
            for item in self.implied
        ):
            raise ValueError("implied probabilities must match original decimal odds")
        if abs(self.overround_pp - (total - 1) * 100) > PROBABILITY_TOLERANCE * 100:
            raise ValueError("overround must match original decimal odds")
        if any(
            abs(item.probability - expected_implied[item.code] / total) > PROBABILITY_TOLERANCE
            for item in self.probabilities
        ):
            raise ValueError("benchmark probabilities must match the declared de-vig method")


def proportional_de_vig(quote: QuoteSnapshot) -> MarketBenchmark:
    if not quote.key.line.eligible_v1:
        raise ValueError("push/Asian lines require settlement-aware probabilities")
    implied = tuple(
        OutcomeProbability(item.code, Decimal(1) / item.decimal_odds) for item in quote.outcomes
    )
    total = sum((item.probability for item in implied), Decimal(0))
    probabilities = tuple(
        OutcomeProbability(item.code, item.probability / total) for item in implied
    )
    validate_probabilities(probabilities)
    return MarketBenchmark(quote, implied, probabilities, (total - 1) * 100)


@dataclass(frozen=True)
class OutcomeEdge:
    outcome_code: str
    model_probability: Decimal
    market_probability: Decimal
    edge_pp: Decimal


@dataclass(frozen=True)
class EdgeComparison:
    outcomes: tuple[OutcomeEdge, ...]
    favored_outcome: str
    value_outcome: str | None


def compare_probabilities(
    model: tuple[OutcomeProbability, ...], market: tuple[OutcomeProbability, ...]
) -> EdgeComparison:
    validate_probabilities(model)
    validate_probabilities(market)
    if {item.code for item in model} != {item.code for item in market}:
        raise ValueError("model and benchmark must describe identical outcomes")
    market_values = {item.code: item.probability for item in market}
    edges = tuple(
        OutcomeEdge(
            item.code,
            item.probability,
            market_values[item.code],
            (item.probability - market_values[item.code]) * 100,
        )
        for item in sorted(model, key=lambda item: item.code)
    )
    favored = min(model, key=lambda item: (-item.probability, item.code)).code
    positive = [item for item in edges if item.edge_pp > 0]
    value = (
        min(positive, key=lambda item: (-item.edge_pp, item.outcome_code)).outcome_code
        if positive
        else None
    )
    return EdgeComparison(edges, favored, value)


class RejectionReason(StrEnum):
    INTEGER_PUSH_UNSUPPORTED = "INTEGER_PUSH_UNSUPPORTED"
    ASIAN_QUARTER_UNSUPPORTED = "ASIAN_QUARTER_UNSUPPORTED"
    FUTURE_ODDS = "FUTURE_ODDS"
    ODDS_STALE = "ODDS_STALE"


@dataclass(frozen=True)
class LineCandidate:
    quote: QuoteSnapshot
    preference_rank: int

    def __post_init__(self) -> None:
        if self.preference_rank < 0:
            raise ValueError("preference rank must be nonnegative")


@dataclass(frozen=True)
class CandidateAssessment:
    candidate: LineCandidate
    reasons: tuple[RejectionReason, ...]


@dataclass(frozen=True)
class LineSelection:
    selected: QuoteSnapshot | None
    assessments: tuple[CandidateAssessment, ...]
    selector_version: str = "line_selector_v1"


def quote_time_reasons(
    quote: QuoteSnapshot, decision_time: datetime, max_age: timedelta
) -> tuple[RejectionReason, ...]:
    require_aware(decision_time)
    if max_age < timedelta(0):
        raise ValueError("quote age limit must be nonnegative")
    if quote.available_at > decision_time or quote.captured_at > decision_time:
        return (RejectionReason.FUTURE_ODDS,)
    if decision_time - quote.captured_at > max_age:
        return (RejectionReason.ODDS_STALE,)
    return ()


def line_selector_v1(
    candidates: tuple[LineCandidate, ...], *, decision_time: datetime, max_age: timedelta
) -> LineSelection:
    """Eligibility only: supplied preference ranks define the explicit ordering.

    Foundation does not invent a main-line strategy. Equal ranks use UUID order
    solely for stable tie-breaking. All candidates and rejection reasons survive.
    """
    require_aware(decision_time)
    if max_age < timedelta(0):
        raise ValueError("quote age limit must be nonnegative")
    if len({item.quote.quote_id for item in candidates}) != len(candidates):
        raise ValueError("duplicate quote ids")
    groups = {
        (
            item.quote.key.event_cycle_id,
            item.quote.key.market_code,
            item.quote.key.subject_id,
            item.quote.key.structure,
            item.quote.key.outcome_codes,
        )
        for item in candidates
    }
    if len(groups) > 1:
        raise ValueError("line candidates must belong to the same cycle, market and subject")
    assessments = []
    for item in sorted(
        candidates, key=lambda item: (item.preference_rank, str(item.quote.quote_id))
    ):
        reasons = list(quote_time_reasons(item.quote, decision_time, max_age))
        if item.quote.key.line.kind == LineType.INTEGER_PUSH:
            reasons.append(RejectionReason.INTEGER_PUSH_UNSUPPORTED)
        if item.quote.key.line.kind == LineType.ASIAN_QUARTER:
            reasons.append(RejectionReason.ASIAN_QUARTER_UNSUPPORTED)
        assessments.append(CandidateAssessment(item, tuple(reasons)))
    selected = next((item.candidate.quote for item in assessments if not item.reasons), None)
    return LineSelection(selected, tuple(assessments))
