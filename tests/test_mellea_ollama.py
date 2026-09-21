"""Opt-in local Mellea -> Ollama repair flow with Jev HTTP mocked.

Requires .[mellea,dev], a running Ollama server, and OLLAMA_MODEL.
Never sends requests to TypeSafe and does not need TYPESAFE_API_KEY.
"""

import json
import os

import httpx2
import pytest

pytest.importorskip("mellea", reason="Install .[mellea,dev] for the local integration test.")
from mellea import MelleaSession
from mellea.backends.ollama import OllamaModelBackend
from mellea.stdlib.sampling import RepairTemplateStrategy

from mellea_jev import JevClient, JevVerifier, accepted_text

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_LOCAL_OLLAMA") != "1",
        reason="Set RUN_LOCAL_OLLAMA=1 to run the local generation integration test.",
    ),
]


def test_real_mellea_ollama_repair_with_mock_jev():
    model = os.environ.get("OLLAMA_MODEL")
    if not model:
        pytest.fail("Set OLLAMA_MODEL to an installed Ollama model tag.")

    source = "The museum opens at 10:00 and closes at 18:00."
    requests = []
    decisions = []

    def mock_jev(request: httpx2.Request) -> httpx2.Response:
        requests.append(json.loads(request.content))
        p_yes = 0.02 if len(requests) == 1 else 0.98
        decisions.append(p_yes)
        return httpx2.Response(
            200,
            json={
                "model": "jev-local-fixture",
                "answers": {"requirement": {"type": "noul", "noul": p_yes}},
            },
            headers={"x-typesafe-request-id": f"fixture-{len(requests)}"},
        )

    session = MelleaSession(backend=OllamaModelBackend(model_id=model))
    with JevClient("local-test-key", transport=httpx2.MockTransport(mock_jev)) as client:
        verifier = JevVerifier(
            client,
            "The candidate states the museum opening time supported by the reference.",
            reference=source,
            repair_hint="State only the opening time supported by the source.",
        )
        sampled = session.instruct(
            "Answer in one short sentence using this source: {{source}}",
            user_variables={"source": source},
            requirements=[verifier.as_requirement()],
            strategy=RepairTemplateStrategy(loop_budget=2, concurrency_budget=1),
            return_sampling_results=True,
        )

    answer = accepted_text(sampled)
    assert decisions == [0.02, 0.98]  # Reject once, then accept the repair attempt.
    assert requests[0]["state"]["reference"] == source
    assert requests[0]["state"]["candidate"].strip()
    normalized_answer = answer.lower().replace("ten", "10")
    assert "10" in normalized_answer
