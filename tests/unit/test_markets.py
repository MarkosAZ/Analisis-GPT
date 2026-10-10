from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import pytest

from sports_analysis.domain.markets import (
    LineCandidate,
    LineType,
    MarketBenchmark,
    MarketKey,
    MarketLine,
    OutcomeProbability,
    OutcomeStructure,
    QuoteOutcome,
    QuoteSnapshot,
    RejectionReason,
    compare_probabilities,
    line_selector_v1,
    proportional_de_vig,
)

NOW = datetime(2026, 1, 1, 12, tzinfo=UTC)
CYCLE = UUID(int=1)


def quote(line: MarketLine | None = None) -> QuoteSnapshot:
    line = line or MarketLine(LineType.HALF_LINE, Decimal("2.5"))
    key = MarketKey(
        CYCLE, "FOOTBALL_TOTAL_GOALS", line, OutcomeStructure.TWO_WAY, ("OVER", "UNDER")
    )
    return QuoteSnapshot(
        uuid4(),
        key,
        "fixture_book",
        NOW,
        NOW,
        (QuoteOutcome("OVER", Decimal("1.8")), QuoteOutcome("UNDER", Decimal("2.1"))),
    )


def test_two_way_proportional_de_vig_preserves_prices_and_overround() -> None:
    original = quote()
    benchmark = proportional_de_vig(original)
    assert benchmark.quote == original
    assert benchmark.method == "PROPORTIONAL_V1"
    assert (
        benchmark.overround_pp
        == (Decimal(1) / Decimal("1.8") + Decimal(1) / Decimal("2.1") - 1) * 100
    )
    assert abs(sum(item.probability for item in benchmark.probabilities) - 1) < Decimal("1e-24")
    assert benchmark.probabilities[0].probability == pytest.approx(
        Decimal("0.5384615384615384615384615385")
    )


def test_three_way_de_vig_uses_all_outcomes() -> None:
    key = MarketKey(
        CYCLE,
        "WINNER_3WAY",
        MarketLine(LineType.THREE_WAY),
        OutcomeStructure.THREE_WAY,
        ("HOME", "DRAW", "AWAY"),
    )
    original = QuoteSnapshot(
        uuid4(),
        key,
        "fixture_book",
        NOW,
        NOW,
        tuple(QuoteOutcome(code, Decimal(3)) for code in key.outcome_codes),
    )
    result = proportional_de_vig(original)
    assert abs(result.overround_pp) < Decimal("1e-24")
    assert all(
        abs(item.probability - Decimal(1) / 3) < Decimal("1e-24") for item in result.probabilities
    )


def test_direct_benchmark_cannot_fabricate_probabilities_prices_or_method() -> None:
    benchmark = proportional_de_vig(quote())
    with pytest.raises(ValueError, match="de-vig method"):
        replace(
            benchmark,
            probabilities=(
                OutcomeProbability("OVER", Decimal("0.1")),
                OutcomeProbability("UNDER", Decimal("0.9")),
            ),
        )
    with pytest.raises(ValueError, match="implied probabilities"):
        replace(
            benchmark, implied=(OutcomeProbability("OVER", Decimal("0.1")), benchmark.implied[1])
        )
    with pytest.raises(ValueError, match="overround"):
        replace(benchmark, overround_pp=Decimal(10))
    with pytest.raises(ValueError, match="every quote outcome"):
        replace(benchmark, implied=(benchmark.implied[0], benchmark.implied[0]))
    with pytest.raises(ValueError, match="every quote outcome"):
        replace(
            benchmark,
            probabilities=(
                OutcomeProbability("YES", Decimal("0.5")),
                OutcomeProbability("NO", Decimal("0.5")),
            ),
        )
    with pytest.raises(ValueError, match="unsupported"):
        replace(benchmark, method="invented")
    with pytest.raises(ValueError, match="settlement-aware"):
        MarketBenchmark(
            quote(MarketLine(LineType.INTEGER_PUSH, Decimal(3))),
            benchmark.implied,
            benchmark.probabilities,
            benchmark.overround_pp,
        )


def test_quote_and_market_copy_mutable_input_sequences() -> None:
    original = quote()
    outcomes = list(original.outcomes)
    codes = list(original.key.outcome_codes)
    key = replace(original.key, outcome_codes=codes)
    snapshot = replace(original, key=key, outcomes=outcomes)
    outcomes.clear()
    codes.clear()
    assert snapshot.outcomes == original.outcomes
    assert snapshot.key == original.key


@pytest.mark.parametrize(
    "outcomes",
    [
        (QuoteOutcome("OVER", Decimal(2)),),
        (QuoteOutcome("OVER", Decimal(2)), QuoteOutcome("OVER", Decimal(2))),
        (QuoteOutcome("OVER", Decimal(2)), QuoteOutcome("DRAW", Decimal(2))),
    ],
)
def test_reject_incomplete_duplicate_or_unexpected_outcomes(
    outcomes: tuple[QuoteOutcome, ...],
) -> None:
    with pytest.raises(ValueError, match="every market outcome"):
        replace(quote(), outcomes=outcomes)


@pytest.mark.parametrize("price", ["1", "0", "-2", "NaN", "Infinity"])
def test_reject_invalid_odds(price: str) -> None:
    with pytest.raises(ValueError):
        QuoteOutcome("OVER", Decimal(price))


@pytest.mark.parametrize(
    ("kind", "value", "eligible"),
    [
        (LineType.HALF_LINE, "8.5", True),
        (LineType.HALF_LINE, "-1.5", True),
        (LineType.INTEGER_PUSH, "8.0", False),
        (LineType.ASIAN_QUARTER, "8.25", False),
        (LineType.ASIAN_QUARTER, "-0.75", False),
    ],
)
def test_settlement_types_and_v1_eligibility(kind: LineType, value: str, eligible: bool) -> None:
    original = quote(MarketLine(kind, Decimal(value)))
    result = line_selector_v1(
        (LineCandidate(original, 0),), decision_time=NOW, max_age=timedelta(seconds=0)
    )
    assert (result.selected is not None) == eligible
    assert len(result.assessments) == 1
    if not eligible:
        assert result.assessments[0].reasons
        with pytest.raises(ValueError, match="settlement-aware"):
            proportional_de_vig(original)


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (LineType.HALF_LINE, "8"),
        (LineType.INTEGER_PUSH, "8.5"),
        (LineType.ASIAN_QUARTER, "8.1"),
        (LineType.MONEYLINE, "0"),
    ],
)
def test_line_type_cannot_mislabel_push_as_half_line(kind: LineType, value: str) -> None:
    with pytest.raises(ValueError):
        MarketLine(kind, Decimal(value))


def test_moneyline_is_eligible_without_numeric_line() -> None:
    original = quote(MarketLine(LineType.MONEYLINE))
    result = line_selector_v1(
        (LineCandidate(original, 0),), decision_time=NOW, max_age=timedelta(0)
    )
    assert result.selected == original


def test_selection_preserves_rejections_and_honors_explicit_rank() -> None:
    half = quote()
    push = quote(MarketLine(LineType.INTEGER_PUSH, Decimal(3)))
    later_preference = replace(half, quote_id=uuid4())
    future = replace(half, quote_id=uuid4(), available_at=NOW + timedelta(seconds=1))
    stale = replace(half, quote_id=uuid4(), captured_at=NOW - timedelta(minutes=10))
    candidates = tuple(
        LineCandidate(item, index)
        for index, item in enumerate((push, future, stale, half, later_preference))
    )
    result = line_selector_v1(candidates, decision_time=NOW, max_age=timedelta(minutes=5))
    assert result.selected == half
    assert len(result.assessments) == 5
    assert result.assessments[0].reasons == (RejectionReason.INTEGER_PUSH_UNSUPPORTED,)
    assert result.assessments[1].reasons == (RejectionReason.FUTURE_ODDS,)
    assert result.assessments[2].reasons == (RejectionReason.ODDS_STALE,)
    assert (
        line_selector_v1(
            tuple(reversed(candidates)), decision_time=NOW, max_age=timedelta(minutes=5)
        )
        == result
    )


def test_selector_rejects_mixing_cycles_and_naive_time() -> None:
    first = quote()
    other = replace(first, quote_id=uuid4(), key=replace(first.key, event_cycle_id=uuid4()))
    with pytest.raises(ValueError, match="same cycle"):
        line_selector_v1(
            (LineCandidate(first, 0), LineCandidate(other, 1)),
            decision_time=NOW,
            max_age=timedelta(0),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        line_selector_v1((), decision_time=NOW.replace(tzinfo=None), max_age=timedelta(0))


def test_favored_over_can_have_value_under_in_percentage_points() -> None:
    model = (
        OutcomeProbability("OVER", Decimal("0.578")),
        OutcomeProbability("UNDER", Decimal("0.422")),
    )
    market = (
        OutcomeProbability("OVER", Decimal("0.61")),
        OutcomeProbability("UNDER", Decimal("0.39")),
    )
    result = compare_probabilities(model, market)
    assert result.favored_outcome == "OVER"
    assert result.value_outcome == "UNDER"
    assert {item.outcome_code: item.edge_pp for item in result.outcomes} == {
        "OVER": Decimal("-3.2"),
        "UNDER": Decimal("3.2"),
    }


def test_no_positive_edge_and_deterministic_three_way_tie() -> None:
    balanced = tuple(OutcomeProbability(code, Decimal("0.5")) for code in ("OVER", "UNDER"))
    assert compare_probabilities(balanced, balanced).value_outcome is None
    model = tuple(
        OutcomeProbability(code, Decimal(value))
        for code, value in (("A", "0.4"), ("B", "0.4"), ("C", "0.2"))
    )
    market = tuple(
        OutcomeProbability(code, Decimal(value))
        for code, value in (("A", "0.3"), ("B", "0.3"), ("C", "0.4"))
    )
    assert compare_probabilities(model, market).value_outcome == "A"


def test_invalid_probability_mass_or_incomparable_outcomes_fail() -> None:
    valid = (
        OutcomeProbability("OVER", Decimal("0.5")),
        OutcomeProbability("UNDER", Decimal("0.5")),
    )
    with pytest.raises(ValueError, match="sum to one"):
        compare_probabilities((OutcomeProbability("OVER", Decimal("0.6")), valid[1]), valid)
    with pytest.raises(ValueError, match="identical outcomes"):
        compare_probabilities(
            valid,
            (OutcomeProbability("YES", Decimal("0.5")), OutcomeProbability("NO", Decimal("0.5"))),
        )
