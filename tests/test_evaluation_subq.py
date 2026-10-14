"""SubQ labeled evaluation through local transport; no paid calls."""

import json

import httpx2
from test_evaluation_proxy import dataset

import mellea_jev
from examples.evaluate import (
    ThresholdPair,
    _run_live,
    load_predictions,
    save_predictions,
    score_predictions,
)


def test_subq_live_evaluation_saves_and_scores_predictions(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBQ_API_KEY", "subq-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-key")
    states = []

    def handler(request):
        assert str(request.url) == "https://api.subq.ai/v1/systemone"
        assert request.headers["authorization"] == "Bearer subq-test-key"
        payload = json.loads(request.content)
        state = payload["state"]
        states.append(state)
        assert payload["model"] == "subq-snap-preview"
        assert payload["questions"]["decision"]["type"] == "noul"
        p_yes = 0.98 if state["candidate"] == "10:00" else 0.02
        return httpx2.Response(
            200,
            json={
                "model": "subq-snap-preview",
                "answers": {"decision": {"type": "noul", "noul": p_yes}},
                "usage": {"input_tokens": 28, "output_tokens": 0},
            },
        )

    provider_type = mellea_jev.SubQProvider
    monkeypatch.setattr(
        mellea_jev,
        "SubQProvider",
        lambda **kwargs: provider_type(**kwargs, transport=httpx2.MockTransport(handler)),
    )
    labeled = dataset()
    predictions = _run_live("subq", None, labeled)
    assert states == [
        {"candidate": example.candidate, "reference": example.reference}
        for example in labeled.examples
    ]
    assert {item.provider for item in predictions} == {"subq"}
    assert {item.model for item in predictions} == {"subq-snap-preview"}

    snapshot = tmp_path / "subq-predictions.jsonl"
    save_predictions(snapshot, labeled, predictions)
    assert load_predictions(snapshot, labeled) == predictions
    saved_text = snapshot.read_text()
    assert "subq-test-key" not in saved_text and "https://" not in saved_text

    rows = score_predictions(
        labeled, predictions, [ThresholdPair(0.1, 0.9), ThresholdPair(0.2, 0.8)]
    )
    assert len(rows) == 2
    assert all(
        row.provider == "subq"
        and row.false_acceptance_count == 0
        and row.false_rejection_count == 0
        and row.uncertain_count == 0
        for row in rows
    )
    assert len(states) == len(labeled.examples)
