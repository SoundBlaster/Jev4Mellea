"""Experimental ProxyAPI Decisions bridge; not OpenAI's native wire contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx2

from ..contracts import ChoiceCriteria, NoulCriteria
from ..results import ChoiceResult, NoulResult, ScoreResult
from .typesafe import JevProtocolError, SystemOneResult, TypeSafeProvider, TypeSafeQuestion

BASE_URL = "https://api.proxyapi.ru"
ENDPOINT = f"{BASE_URL}/v1/decisions"
DEFAULT_MODEL = "openai/gpt-6-luna-decisions"


class _DecisionsTransport(httpx2.BaseTransport):
    """Change only the TypeSafe route and normalize ProxyAPI's response ID."""

    def __init__(self, inner: httpx2.BaseTransport) -> None:
        self._inner = inner

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.method != "POST" or request.url != httpx2.URL(f"{BASE_URL}/v1/systemone"):
            raise httpx2.UnsupportedProtocol("Unexpected ProxyAPI bridge request.")
        forwarded = httpx2.Request(
            request.method,
            ENDPOINT,
            headers=request.headers,
            content=request.content,
            extensions=request.extensions,
        )
        response = self._inner.handle_request(forwarded)
        if response.status_code == 200:
            response.read()
            try:
                body = response.json()
            except ValueError:
                # The shared provider rejects malformed JSON without exposing it.
                return response
            request_id = body.get("id") if isinstance(body, dict) else None
            if (
                not isinstance(request_id, str)
                or not request_id
                or not request_id.isascii()
                or any(ch.isspace() or ord(ch) < 33 or ord(ch) == 127 for ch in request_id)
            ):
                response.close()
                raise JevProtocolError(
                    "Malformed ProxyAPI response ID; validation did not complete."
                )
            response.headers["x-typesafe-request-id"] = request_id
        return response

    def close(self) -> None:
        self._inner.close()


class ProxyAPIProvider:
    """Temporary provider composed from the shared TypeSafe implementation.

    ProxyAPI uses ``state``, named ``questions``, and ``noul``, unlike the native
    OpenAI Decisions API. The bridge reuses TypeSafe SDK serialization and the
    adapter's strict result validation. Import from this module explicitly;
    this experimental provider is not exported from the package root.

    Supply a ProxyAPI key explicitly. The destination is fixed to ProxyAPI;
    key and URL environment variables are not read. Environment proxies,
    redirects, and automatic retries remain disabled. Close with a context
    manager. The existing JevError classes report failures.
    """

    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        timeout: float = 10.0,
        transport: httpx2.BaseTransport | None = None,
    ) -> None:
        if not isinstance(api_key, str):
            raise ValueError("Supply a ProxyAPI api_key explicitly.")
        bridge = _DecisionsTransport(
            transport if transport is not None else httpx2.HTTPTransport(retries=0)
        )
        try:
            self._provider = TypeSafeProvider(
                api_key=api_key, model=model, timeout=timeout, base_url=BASE_URL, transport=bridge
            )
        except Exception:
            bridge.close()
            raise

    @property
    def model(self) -> str:
        return self._provider.model

    def system_one(
        self, *, state: dict[str, Any], questions: Mapping[str, TypeSafeQuestion]
    ) -> SystemOneResult:
        """Evaluate mixed named questions in one synchronous request."""
        return self._provider.system_one(state=state, questions=questions)

    def noul(
        self,
        *,
        state: dict[str, Any],
        question: str,
        criteria: NoulCriteria | None = None,
    ) -> NoulResult:
        return self._provider.noul(state=state, question=question, criteria=criteria)

    def choice(
        self, *, state: dict[str, Any], question: str, criteria: ChoiceCriteria
    ) -> ChoiceResult:
        return self._provider.choice(state=state, question=question, criteria=criteria)

    def score(
        self, *, state: dict[str, Any], question: str, criteria: Sequence[str]
    ) -> ScoreResult:
        return self._provider.score(state=state, question=question, criteria=criteria)

    def close(self) -> None:
        self._provider.close()

    def __enter__(self) -> ProxyAPIProvider:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
