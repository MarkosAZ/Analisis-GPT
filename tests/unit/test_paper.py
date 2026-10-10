from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from sports_analysis.domain.markets import (
    LineType,
    MarketKey,
    MarketLine,
    OutcomeProbability,
    OutcomeStructure,
    QuoteOutcome,
    QuoteSnapshot,
    proportional_de_vig,
)
from sports_analysis.domain.paper import (
    NoBetPolicy,
    NoBetReason,
    OddsSourceRule,
    PaperPolicy,
    PaperPolicyRegistry,
    PaperPrediction,
    PaperTrack,
    PredictionQuality,
    evaluate_no_bet,
    generate_paper_decision,
    load_no_bet_policy,
)

NOW = datetime(2026, 1, 2, 12, tzinfo=UTC)
START = NOW - timedelta(days=1)
QUALITY = PredictionQuality(Decimal(1), True, Decimal(0), Decimal(0), ())


def policy(track: PaperTrack = PaperTrack.ALL) -> PaperPolicy:
    return PaperPolicy(
        f"paper_{track.value.lower()}_v1",
        track,
        OddsSourceRule.FIXED_BOOKMAKER,
        "fixture_book",
        300,
        no_bet_policy() if track == PaperTrack.RECOMMENDED else None,
        START,
        START,
    )


def no_bet_policy() -> NoBetPolicy:
    # Explicit synthetic values test the mechanism, not a production strategy.
    return NoBetPolicy(
        "fixture_no_bet_v1",
        Decimal(1),
        Decimal("0.8"),
        Decimal("0.2"),
        Decimal("0.1"),
        60,
        START,
        START,
    )


def inputs() -> tuple[PaperPrediction, QuoteSnapshot]:
    key = MarketKey(
        uuid4(),
        "FOOTBALL_TOTAL_GOALS",
        MarketLine(LineType.HALF_LINE, Decimal("2.5")),
        OutcomeStructure.TWO_WAY,
        ("OVER", "UNDER"),
    )
    quote = QuoteSnapshot(
        uuid4(),
        key,
        "fixture_book",
        NOW,
        NOW,
        (QuoteOutcome("OVER", Decimal("1.6")), QuoteOutcome("UNDER", Decimal("2.4"))),
    )
    prediction = PaperPrediction(
        uuid4(),
        key,
        NOW,
        (OutcomeProbability("OVER", Decimal("0.55")), OutcomeProbability("UNDER", Decimal("0.45"))),
        True,
    )
    return prediction, quote


def test_paper_all_bets_max_positive_edge_for_exactly_one_unit() -> None:
    prediction, quote = inputs()
    result = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(quote),
        quotes=(quote,),
        policy=policy(),
        quality=QUALITY,
    )
    assert result.bet is not None
    assert result.bet.outcome_code == "UNDER"
    assert result.bet.edge_pp == pytest.approx(Decimal(5))
    assert result.bet.stake_units == 1
    assert result.bet.event_cycle_id == prediction.key.event_cycle_id
    assert result.bet.placed_at == prediction.decision_time


def test_draft_checked_in_configuration_is_not_a_live_strategy() -> None:
    draft = load_no_bet_policy(Path(__file__).parents[2] / "config/no_bet_policy_v1.json")
    assert draft.version == "no_bet_policy_v1"
    assert draft.min_edge_pp is None
    assert not draft.active_at(NOW)
    prediction, quote = inputs()
    result = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(quote),
        quotes=(quote,),
        policy=PaperPolicy("paper_all_v1", PaperTrack.ALL),
        quality=QUALITY,
    )
    assert result.reasons == (NoBetReason.POLICY_INACTIVE,)


def test_activation_requires_source_freshness_and_frozen_thresholds() -> None:
    with pytest.raises(ValueError, match="source and freshness"):
        PaperPolicy("paper_all_v1", PaperTrack.ALL, activated_at=START, valid_from=START)
    with pytest.raises(ValueError, match="thresholds"):
        NoBetPolicy("no_bet_policy_v1", activated_at=START, valid_from=START)
    with pytest.raises(ValueError, match="backdated"):
        replace(policy(), activated_at=NOW)


def test_policy_immutable_version_registry_and_prospective_windows() -> None:
    original = policy()
    with pytest.raises(FrozenInstanceError):
        original.version = "changed"
    registry = PaperPolicyRegistry()
    registry.register(original, registered_at=START)
    with pytest.raises(ValueError, match="cannot be replaced"):
        registry.register(replace(original, max_odds_age_seconds=900), registered_at=START)
    with pytest.raises(ValueError, match="retroactively"):
        PaperPolicyRegistry().register(original, registered_at=NOW)
    bounded = replace(original, valid_to=NOW)
    assert bounded.active_at(START)
    assert not bounded.active_at(START - timedelta(microseconds=1))
    assert not bounded.active_at(NOW)


def test_reusing_no_bet_version_cannot_change_thresholds() -> None:
    original = policy(PaperTrack.RECOMMENDED)
    registry = PaperPolicyRegistry()
    registry.register(original, registered_at=START)
    assert original.no_bet_policy is not None
    changed = replace(original.no_bet_policy, min_edge_pp=Decimal("0.01"))
    with pytest.raises(ValueError, match="NO BET version cannot be replaced"):
        registry.register(
            replace(original, version="paper_recommended_v2", no_bet_policy=changed),
            registered_at=START,
        )


def test_prediction_probabilities_copy_mutable_input_sequence() -> None:
    original, _ = inputs()
    probabilities = list(original.probabilities)
    snapshot = replace(original, probabilities=probabilities)
    probabilities.clear()
    assert snapshot.probabilities == original.probabilities


def test_recommended_collects_all_versioned_no_bet_reasons() -> None:
    quality = PredictionQuality(None, False, None, None, ("LINEUP",))
    reasons = evaluate_no_bet(
        no_bet_policy(),
        decision_time=NOW,
        edge_pp=Decimal("0.5"),
        quality=quality,
        odds_age=timedelta(seconds=61),
    )
    assert set(reasons) == {
        NoBetReason.EDGE_INSUFFICIENT,
        NoBetReason.DATA_QUALITY_LOW,
        NoBetReason.MODEL_UNVALIDATED,
        NoBetReason.OOD_HIGH,
        NoBetReason.ENSEMBLE_UNSTABLE,
        NoBetReason.ODDS_STALE,
        NoBetReason.CRITICAL_CONTEXT_MISSING,
    }


def test_recommended_blocks_quality_failure_but_all_keeps_model_track() -> None:
    prediction, quote = inputs()
    quality = replace(QUALITY, model_validated=False)
    recommended = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(quote),
        quotes=(quote,),
        policy=policy(PaperTrack.RECOMMENDED),
        quality=quality,
    )
    all_decision = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(quote),
        quotes=(quote,),
        policy=policy(),
        quality=quality,
    )
    assert recommended.bet is None
    assert recommended.no_bet_policy_version == "fixture_no_bet_v1"
    assert recommended.reasons == (NoBetReason.MODEL_UNVALIDATED,)
    assert all_decision.bet is not None


@pytest.mark.parametrize("case", ["future", "stale", "other_cycle", "other_line", "unofficial"])
def test_paper_never_uses_future_stale_or_incomparable_quotes(case: str) -> None:
    prediction, quote = inputs()
    if case == "future":
        quote = replace(quote, available_at=NOW + timedelta(seconds=1))
    elif case == "stale":
        quote = replace(quote, captured_at=NOW - timedelta(minutes=6))
    elif case == "other_cycle":
        quote = replace(quote, key=replace(quote.key, event_cycle_id=uuid4()))
    elif case == "other_line":
        quote = replace(
            quote, key=replace(quote.key, line=MarketLine(LineType.HALF_LINE, Decimal("3.5")))
        )
    else:
        prediction = replace(prediction, official=False)
    result = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(quote),
        quotes=(quote,),
        policy=policy(),
        quality=QUALITY,
    )
    assert result.bet is None
    assert result.reasons


def test_no_implicit_bookmaker_fallback_and_best_available_is_explicit() -> None:
    prediction, benchmark_quote = inputs()
    other = replace(benchmark_quote, quote_id=uuid4(), bookmaker="another_book")
    blocked = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(benchmark_quote),
        quotes=(other,),
        policy=policy(),
        quality=QUALITY,
    )
    assert blocked.reasons == (NoBetReason.PRICE_UNAVAILABLE,)
    best = replace(policy(), odds_source_rule=OddsSourceRule.BEST_AVAILABLE, bookmaker=None)
    allowed = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(benchmark_quote),
        quotes=(other,),
        policy=best,
        quality=QUALITY,
    )
    assert allowed.bet is not None
    assert allowed.bet.bookmaker == "another_book"


def test_best_available_does_not_cherry_pick_superseded_old_price() -> None:
    prediction, quote = inputs()
    old = replace(
        quote,
        quote_id=uuid4(),
        captured_at=NOW - timedelta(seconds=20),
        outcomes=(QuoteOutcome("OVER", Decimal("1.6")), QuoteOutcome("UNDER", Decimal(5))),
    )
    decision = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(quote),
        quotes=(quote, old),
        policy=policy(),
        quality=QUALITY,
    )
    assert decision.bet is not None
    assert decision.bet.quote_id == quote.quote_id
    assert decision.bet.decimal_odds == Decimal("2.4")


def test_no_positive_edge_produces_no_bet() -> None:
    prediction, quote = inputs()
    benchmark = proportional_de_vig(quote)
    prediction = replace(prediction, probabilities=benchmark.probabilities)
    decision = generate_paper_decision(
        prediction, benchmark=benchmark, quotes=(quote,), policy=policy(), quality=QUALITY
    )
    assert decision.reasons == (NoBetReason.NO_POSITIVE_EDGE,)


def test_recommended_freshness_uses_benchmark_too() -> None:
    prediction, quote = inputs()
    old_benchmark = replace(quote, quote_id=uuid4(), captured_at=NOW - timedelta(seconds=61))
    decision = generate_paper_decision(
        prediction,
        benchmark=proportional_de_vig(old_benchmark),
        quotes=(quote,),
        policy=policy(PaperTrack.RECOMMENDED),
        quality=QUALITY,
    )
    assert decision.reasons == (NoBetReason.ODDS_STALE,)
