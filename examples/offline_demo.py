"""No network, no keys, no Mellea: synthetic Noul responses through real HTTPX."""
import json

import httpx

from mellea_jev import JevClient, JevVerifier


def main() -> None:
    values = iter([0.98, 0.02, 0.55])

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["questions"]["requirement"]["type"] == "noul"
        return httpx.Response(200, json={
            "model": "jev-OFFLINE-FIXTURE",
            "answers": {"requirement": {"type": "noul", "noul": next(values)}},
            "usage": {"input_tokens": 0, "output_tokens": 0},
        })

    print("OFFLINE DEMO: probabilities are synthetic fixtures, not model predictions.\n")
    with JevClient("offline-dummy", transport=httpx.MockTransport(handler)) as client:
        verifier = JevVerifier(
            client,
            "The museum opening time in the candidate matches the reference.",
            reference="The museum opens at 10:00 and closes at 18:00.",
            repair_hint="Use only the opening time supported by the reference.",
        )
        for text in ["It opens at 10:00.", "It opens at 08:00.", "It opens in the morning."]:
            verdict = verifier.evaluate(text)
            print(json.dumps(verdict.to_dict(), ensure_ascii=False, indent=2))
    print("\nIn Mellea: pass -> accept; fail -> repair; uncertain -> ReviewRequired.")


if __name__ == "__main__":
    main()
