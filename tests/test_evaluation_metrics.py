import pytest

from examples.evaluate import (
    EvaluationFormatError,
    LabeledDataset,
    LabeledExample,
    Prediction,
    ThresholdPair,
    score_predictions,
)


def labeled_dataset():
    return LabeledDataset(
        name="metrics-fixture",
        version="1",
        requirement="The candidate meets the requirement.",
        examples=(
            LabeledExample("positive-clear", "candidate one", "accept"),
            LabeledExample("positive-rejected", "candidate two", "accept"),
            LabeledExample("negative-accepted", "candidate three", "reject"),
            LabeledExample("negative-middle", "candidate four", "reject"),
        ),
        content_sha256="fixture-hash",
    )


def labeled_predictions():
    return [
        Prediction("positive-clear", "typesafe", "jev-fixture", 0.95),
        Prediction("positive-rejected", "typesafe", "jev-fixture", 0.05),
        Prediction("negative-accepted", "typesafe", "jev-fixture", 0.95),
        Prediction("negative-middle", "typesafe", "jev-fixture", 0.30),
        Prediction("positive-clear", "laya", "laya-fixture", 0.90),
        Prediction("positive-rejected", "laya", "laya-fixture", 0.20),
        Prediction("negative-accepted", "laya", "laya-fixture", 0.10),
        Prediction("negative-middle", "laya", "laya-fixture", 0.50),
    ]


def test_score_predictions_counts_rates_and_groups_by_provider_model_and_threshold():
    first_threshold = ThresholdPair(reject_at=0.20, accept_at=0.80)
    second_threshold = ThresholdPair(reject_at=0.35, accept_at=0.65)

    rows = score_predictions(
        labeled_dataset(), labeled_predictions(), [first_threshold, second_threshold]
    )
    by_key = {(row.provider, row.model, row.threshold): row for row in rows}

    laya = by_key[("laya", "laya-fixture", first_threshold)]
    assert (laya.sample_count, laya.positive_count, laya.negative_count) == (4, 2, 2)
    assert (laya.false_acceptance_count, laya.false_acceptance_rate) == (0, 0.0)
    assert (laya.false_rejection_count, laya.false_rejection_rate) == (1, 0.5)
    assert (laya.uncertain_count, laya.uncertain_rate) == (1, 0.25)

    typesafe_wide = by_key[("typesafe", "jev-fixture", first_threshold)]
    assert (typesafe_wide.false_acceptance_count, typesafe_wide.false_acceptance_rate) == (1, 0.5)
    assert (typesafe_wide.false_rejection_count, typesafe_wide.false_rejection_rate) == (1, 0.5)
    assert (typesafe_wide.uncertain_count, typesafe_wide.uncertain_rate) == (1, 0.25)

    typesafe_narrow = by_key[("typesafe", "jev-fixture", second_threshold)]
    assert (typesafe_narrow.false_acceptance_count, typesafe_narrow.false_acceptance_rate) == (
        1,
        0.5,
    )
    assert (typesafe_narrow.false_rejection_count, typesafe_narrow.false_rejection_rate) == (1, 0.5)
    assert (typesafe_narrow.uncertain_count, typesafe_narrow.uncertain_rate) == (0, 0.0)


def test_score_predictions_requires_complete_unique_predictions_per_model():
    dataset = labeled_dataset()
    predictions = labeled_predictions()
    threshold = ThresholdPair(reject_at=0.20, accept_at=0.80)

    with pytest.raises(EvaluationFormatError, match="every dataset example exactly once"):
        score_predictions(dataset, predictions[:-1], [threshold])

    with pytest.raises(EvaluationFormatError, match="Duplicate prediction"):
        score_predictions(dataset, [*predictions, predictions[0]], [threshold])
