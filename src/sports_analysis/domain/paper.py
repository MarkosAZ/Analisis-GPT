"""Prospective paper decisions; no real-bet data or active strategy defaults.

Policy objects are immutable values. The in-memory registry rejects replacing
versions; production persistence must also enforce version immutability. Price
source, freshness limits and NO BET thresholds require explicit activation.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from uuid import UUID

from sports_analysis.domain.markets import (
    MarketBenchmark,
    MarketKey,
    OutcomeProbability,
    QuoteSnapshot,
    compare_probabilities,
    quote_time_reasons,
    require_aware,
    require_decimal,
    validate_probabilities,
)


class PaperTrack(StrEnum):
    ALL = "ALL"
    RECOMMENDED = "RECOMMENDED"


class OddsSourceRule(StrEnum):
    FIXED_BOOKMAKER = "FIXED_BOOKMAKER"
    BEST_AVAILABLE = "BEST_AVAILABLE"


class NoBetReason(StrEnum):
    POLICY_INACTIVE = "POLICY_INACTIVE"
    NOT_OFFICIAL = "NOT_OFFICIAL"
    NON_COMPARABLE = "NON_COMPARABLE"
    NO_POSITIVE_EDGE = "NO_POSITIVE_EDGE"
    PRICE_UNAVAILABLE = "PRICE_UNAVAILABLE"
    FUTURE_ODDS = "FUTURE_ODDS"
    EDGE_INSUFFICIENT = "EDGE_INSUFFICIENT"
    DATA_QUALITY_LOW = "DATA_QUALITY_LOW"
    MODEL_UNVALIDATED = "MODEL_UNVALIDATED"
    OOD_HIGH = "OOD_HIGH"
    ENSEMBLE_UNSTABLE = "ENSEMBLE_UNSTABLE"
    ODDS_STALE = "ODDS_STALE"
    CRITICAL_CONTEXT_MISSING = "CRITICAL_CONTEXT_MISSING"


def _validate_window(
    activated_at: datetime | None, valid_from: datetime | None, valid_to: datetime | None
) -> None:
    if (activated_at is None) != (valid_from is None):
        raise ValueError("activation and effective time must both be specified")
    if activated_at is None or valid_from is None:
        if valid_to is not None:
            raise ValueError("draft policies cannot have an effective end")
        return
    require_aware(activated_at)
    require_aware(valid_from)
    if valid_from < activated_at:
        raise ValueError("policy activation cannot be backdated")
    if valid_to is not None:
        require_aware(valid_to)
        if valid_to <= valid_from:
            raise ValueError("policy window must be nonempty")


@dataclass(frozen=True)
class NoBetPolicy:
    version: str
    min_edge_pp: Decimal | None = None
    min_data_quality: Decimal | None = None
    max_ood_score: Decimal | None = None
    max_ensemble_dispersion: Decimal | None = None
    max_odds_age_seconds: int | None = None
    activated_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("policy version is required")
        _validate_window(self.activated_at, self.valid_from, self.valid_to)
        thresholds = (
            self.min_edge_pp,
            self.min_data_quality,
            self.max_ood_score,
            self.max_ensemble_dispersion,
        )
        for value in thresholds:
            if value is not None:
                require_decimal(value)
                if value < 0:
                    raise ValueError("policy thresholds must be nonnegative")
        if self.min_data_quality is not None and self.min_data_quality > 1:
            raise ValueError("data quality is a fraction")
        if self.max_odds_age_seconds is not None and self.max_odds_age_seconds < 0:
            raise ValueError("odds age limit must be nonnegative")
        if self.valid_from is not None and (
            any(value is None for value in thresholds) or self.max_odds_age_seconds is None
        ):
            raise ValueError("all NO BET thresholds must be frozen before activation")

    def active_at(self, decision_time: datetime) -> bool:
        require_aware(decision_time)
        return (
            self.valid_from is not None
            and self.valid_from <= decision_time
            and (self.valid_to is None or decision_time < self.valid_to)
        )


def load_no_bet_policy(path: Path) -> NoBetPolicy:
    """Load the checked-in draft; activation is a separate prospective action."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document["state"] != "DRAFT":
        raise ValueError("this loader only accepts unactivated draft configuration")
    thresholds = document["thresholds"]

    def number(key: str) -> Decimal | None:
        value = thresholds[key]
        return None if value is None else Decimal(str(value))

    return NoBetPolicy(
        version=document["version"],
        min_edge_pp=number("min_edge_pp"),
        min_data_quality=number("min_data_quality"),
        max_ood_score=number("max_ood_score"),
        max_ensemble_dispersion=number("max_ensemble_dispersion"),
        max_odds_age_seconds=thresholds["max_odds_age_seconds"],
    )


@dataclass(frozen=True)
class PaperPolicy:
    version: str
    track: PaperTrack
    odds_source_rule: OddsSourceRule | None = None
    bookmaker: str | None = None
    max_odds_age_seconds: int | None = None
    no_bet_policy: NoBetPolicy | None = None
    activated_at: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("policy version is required")
        if not isinstance(self.track, PaperTrack):
            raise ValueError("paper track must be ALL or RECOMMENDED")
        if self.odds_source_rule is not None and not isinstance(
            self.odds_source_rule, OddsSourceRule
        ):
            raise ValueError("unsupported odds source rule")
        _validate_window(self.activated_at, self.valid_from, self.valid_to)
        if self.max_odds_age_seconds is not None and self.max_odds_age_seconds < 0:
            raise ValueError("odds age limit must be nonnegative")
        if self.odds_source_rule == OddsSourceRule.FIXED_BOOKMAKER and not self.bookmaker:
            raise ValueError("fixed bookmaker policy requires an explicit bookmaker")
        if self.odds_source_rule != OddsSourceRule.FIXED_BOOKMAKER and self.bookmaker is not None:
            raise ValueError("bookmaker is only valid for FIXED_BOOKMAKER")
        if self.valid_from is not None:
            if self.odds_source_rule is None or self.max_odds_age_seconds is None:
                raise ValueError("source and freshness must be frozen before activation")
            if self.track == PaperTrack.RECOMMENDED and (
                self.no_bet_policy is None or not self.no_bet_policy.active_at(self.valid_from)
            ):
                raise ValueError("recommended policy requires an activated NO BET policy")

    def active_at(self, decision_time: datetime) -> bool:
        require_aware(decision_time)
        return (
            self.valid_from is not None
            and self.valid_from <= decision_time
            and (self.valid_to is None or decision_time < self.valid_to)
        )


class PaperPolicyRegistry:
    """Append-only process-local registry, used by Foundation tests/development."""

    def __init__(self) -> None:
        self._versions: dict[str, PaperPolicy] = {}
        self._no_bet_versions: dict[str, NoBetPolicy] = {}

    def register(self, policy: PaperPolicy, *, registered_at: datetime) -> None:
        require_aware(registered_at)
        if policy.version in self._versions:
            raise ValueError("a policy version cannot be replaced; create a new version")
        if policy.valid_from is not None and policy.valid_from < registered_at:
            raise ValueError("new policy versions cannot be registered retroactively")
        if policy.no_bet_policy is not None:
            no_bet = policy.no_bet_policy
            registered = self._no_bet_versions.get(no_bet.version)
            if registered is not None and registered != no_bet:
                raise ValueError("a NO BET version cannot be replaced; create a new version")
            if (
                registered is None
                and no_bet.valid_from is not None
                and no_bet.valid_from < registered_at
            ):
                raise ValueError("new NO BET versions cannot be registered retroactively")
            self._no_bet_versions[no_bet.version] = no_bet
        self._versions[policy.version] = policy


@dataclass(frozen=True)
class PaperPrediction:
    prediction_id: UUID
    key: MarketKey
    decision_time: datetime
    probabilities: tuple[OutcomeProbability, ...]
    official: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "probabilities", tuple(self.probabilities))
        require_aware(self.decision_time)
        validate_probabilities(self.probabilities)
        if {item.code for item in self.probabilities} != set(self.key.outcome_codes):
            raise ValueError("prediction must cover exactly the market outcomes")


@dataclass(frozen=True)
class PredictionQuality:
    data_quality: Decimal | None
    model_validated: bool
    ood_score: Decimal | None
    ensemble_dispersion: Decimal | None
    critical_context_missing: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "critical_context_missing", tuple(self.critical_context_missing))
        for value in (self.data_quality, self.ood_score, self.ensemble_dispersion):
            if value is not None:
                require_decimal(value)
                if value < 0:
                    raise ValueError("quality values must be nonnegative")
        if self.data_quality is not None and self.data_quality > 1:
            raise ValueError("data quality is a fraction")


@dataclass(frozen=True)
class PaperBet:
    prediction_id: UUID
    event_cycle_id: UUID
    policy_version: str
    no_bet_policy_version: str | None
    outcome_code: str
    quote_id: UUID
    bookmaker: str
    decimal_odds: Decimal
    edge_pp: Decimal
    placed_at: datetime
    stake_units: Decimal = Decimal(1)

    def __post_init__(self) -> None:
        if self.stake_units != 1:
            raise ValueError("Foundation paper policies use exactly one unit")


@dataclass(frozen=True)
class PaperDecision:
    policy_version: str
    no_bet_policy_version: str | None
    bet: PaperBet | None
    reasons: tuple[NoBetReason, ...]


def evaluate_no_bet(
    policy: NoBetPolicy,
    *,
    decision_time: datetime,
    edge_pp: Decimal,
    quality: PredictionQuality,
    odds_age: timedelta,
) -> tuple[NoBetReason, ...]:
    require_decimal(edge_pp)
    if odds_age < timedelta(0):
        return (NoBetReason.FUTURE_ODDS,)
    if not policy.active_at(decision_time):
        return (NoBetReason.POLICY_INACTIVE,)
    reasons = []
    if policy.min_edge_pp is None or edge_pp < policy.min_edge_pp:
        reasons.append(NoBetReason.EDGE_INSUFFICIENT)
    if (
        quality.data_quality is None
        or policy.min_data_quality is None
        or quality.data_quality < policy.min_data_quality
    ):
        reasons.append(NoBetReason.DATA_QUALITY_LOW)
    if not quality.model_validated:
        reasons.append(NoBetReason.MODEL_UNVALIDATED)
    if (
        quality.ood_score is None
        or policy.max_ood_score is None
        or quality.ood_score > policy.max_ood_score
    ):
        reasons.append(NoBetReason.OOD_HIGH)
    if (
        quality.ensemble_dispersion is None
        or policy.max_ensemble_dispersion is None
        or quality.ensemble_dispersion > policy.max_ensemble_dispersion
    ):
        reasons.append(NoBetReason.ENSEMBLE_UNSTABLE)
    if policy.max_odds_age_seconds is None or odds_age > timedelta(
        seconds=policy.max_odds_age_seconds
    ):
        reasons.append(NoBetReason.ODDS_STALE)
    if quality.critical_context_missing:
        reasons.append(NoBetReason.CRITICAL_CONTEXT_MISSING)
    return tuple(reasons)


def generate_paper_decision(
    prediction: PaperPrediction,
    *,
    benchmark: MarketBenchmark,
    quotes: tuple[QuoteSnapshot, ...],
    policy: PaperPolicy,
    quality: PredictionQuality,
) -> PaperDecision:
    """Select MAX_POSITIVE_EDGE, then obtain its explicitly configured price.

    Every offered quote and the benchmark must match the same cycle, market,
    subject, line and outcome set. Source rules never fall back implicitly.
    """
    no_bet_version = policy.no_bet_policy.version if policy.no_bet_policy else None

    def rejected(*reasons: NoBetReason) -> PaperDecision:
        return PaperDecision(policy.version, no_bet_version, None, tuple(dict.fromkeys(reasons)))

    if not policy.active_at(prediction.decision_time) or policy.max_odds_age_seconds is None:
        return rejected(NoBetReason.POLICY_INACTIVE)
    if not prediction.official:
        return rejected(NoBetReason.NOT_OFFICIAL)
    if not prediction.key.line.eligible_v1 or prediction.key != benchmark.quote.key:
        return rejected(NoBetReason.NON_COMPARABLE)
    max_age = timedelta(seconds=policy.max_odds_age_seconds)
    time_errors = quote_time_reasons(benchmark.quote, prediction.decision_time, max_age)
    if time_errors:
        return rejected(*(NoBetReason(reason.value) for reason in time_errors))
    comparison = compare_probabilities(prediction.probabilities, benchmark.probabilities)
    if comparison.value_outcome is None:
        return rejected(NoBetReason.NO_POSITIVE_EDGE)
    outcome = comparison.value_outcome
    available = [
        quote
        for quote in quotes
        if quote.key == prediction.key
        and not quote_time_reasons(quote, prediction.decision_time, max_age)
    ]
    if policy.odds_source_rule == OddsSourceRule.FIXED_BOOKMAKER:
        available = [quote for quote in available if quote.bookmaker == policy.bookmaker]
    elif policy.odds_source_rule != OddsSourceRule.BEST_AVAILABLE:
        return rejected(NoBetReason.POLICY_INACTIVE)
    if not available:
        return rejected(NoBetReason.PRICE_UNAVAILABLE)
    # Retain the latest available capture for each bookmaker. An old, superior
    # price is not an executable offer once a newer capture supersedes it.
    latest: dict[str, QuoteSnapshot] = {}
    for quote in sorted(
        available, key=lambda item: (item.captured_at, item.available_at, str(item.quote_id))
    ):
        latest[quote.bookmaker] = quote
    chosen = min(
        latest.values(), key=lambda item: (-item.price(outcome), item.bookmaker, str(item.quote_id))
    )
    edge = next(item.edge_pp for item in comparison.outcomes if item.outcome_code == outcome)
    if policy.track == PaperTrack.RECOMMENDED:
        if policy.no_bet_policy is None:
            return rejected(NoBetReason.POLICY_INACTIVE)
        reasons = evaluate_no_bet(
            policy.no_bet_policy,
            decision_time=prediction.decision_time,
            edge_pp=edge,
            quality=quality,
            odds_age=max(
                prediction.decision_time - chosen.captured_at,
                prediction.decision_time - benchmark.quote.captured_at,
            ),
        )
        if reasons:
            return rejected(*reasons)
    bet = PaperBet(
        prediction.prediction_id,
        prediction.key.event_cycle_id,
        policy.version,
        no_bet_version,
        outcome,
        chosen.quote_id,
        chosen.bookmaker,
        chosen.price(outcome),
        edge,
        prediction.decision_time,
    )
    return PaperDecision(policy.version, no_bet_version, bet, ())
