from examples.evaluate import LabeledDataset, LabeledExample, collect_predictions
from mellea_jev import NoulResult


class RecordingProvider:
    def __init__(self):
        self.states = []

    def noul(self, *, state, question, criteria=None):
        self.states.append(state.copy())
        return NoulResult(p_yes=0.75, model="recording-model")


def test_collect_predictions_passes_each_example_own_reference():
    dataset = LabeledDataset(
        name="reference-forwarding",
        version="1",
        requirement="The candidate matches the reference.",
        examples=(
            LabeledExample("first", "first candidate", "accept", "first reference"),
            LabeledExample("second", "second candidate", "reject", "second reference"),
            LabeledExample("no-reference", "third candidate", "accept"),
        ),
        content_sha256="fixture-hash",
    )
    provider = RecordingProvider()

    predictions = collect_predictions(dataset, provider, provider_name="fixture")

    assert provider.states == [
        {"candidate": "first candidate", "reference": "first reference"},
        {"candidate": "second candidate", "reference": "second reference"},
        {"candidate": "third candidate"},
    ]
    assert [prediction.example_id for prediction in predictions] == [
        "first",
        "second",
        "no-reference",
    ]
