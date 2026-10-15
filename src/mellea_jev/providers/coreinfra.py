"""CoreInfra connection factory composed from the existing SDK providers."""

from __future__ import annotations

import os
from typing import Literal, overload

import httpx2

from .openai import OpenAIProvider
from .typesafe import TypeSafeProvider

CoreInfraProtocol = Literal["systemone", "decisions"]
SYSTEM_ONE_ENDPOINT = "https://hub.coreinfra.ai/typesafe/api/v1/systemone"
DECISIONS_ENDPOINT = "https://hub.coreinfra.ai/openai/api/v1/decisions"


@overload
def coreinfra_provider(
    *,
    api_key: str | None = None,
    model: str = "jev-latest",
    protocol: Literal["systemone"] = "systemone",
    timeout: float = 10.0,
    transport: httpx2.BaseTransport | None = None,
) -> TypeSafeProvider: ...


@overload
def coreinfra_provider(
    *,
    api_key: str | None = None,
    model: str = "jev-latest",
    protocol: Literal["decisions"],
    timeout: float = 10.0,
    transport: httpx2.BaseTransport | None = None,
) -> OpenAIProvider: ...


@overload
def coreinfra_provider(
    *,
    api_key: str | None = None,
    model: str = "jev-latest",
    protocol: CoreInfraProtocol,
    timeout: float = 10.0,
    transport: httpx2.BaseTransport | None = None,
) -> TypeSafeProvider | OpenAIProvider: ...


def coreinfra_provider(
    *,
    api_key: str | None = None,
    model: str = "jev-latest",
    protocol: CoreInfraProtocol = "systemone",
    timeout: float = 10.0,
    transport: httpx2.BaseTransport | None = None,
) -> TypeSafeProvider | OpenAIProvider:
    """Select a CoreInfra protocol independently of the requested model.

    Read only COREINFRA_API_KEY when no explicit key is supplied. Return an
    ordinary TypeSafeProvider or OpenAIProvider, with its existing lifecycle,
    primitive contracts, safe errors, and disabled retries/redirects. The
    Decisions route requires the optional ``openai`` extra. Model availability
    is owned by the Hub; no discovery request or protocol fallback is performed.
    """
    if protocol not in ("systemone", "decisions"):
        raise ValueError("CoreInfra protocol must be systemone or decisions.")
    key = os.environ.get("COREINFRA_API_KEY", "") if api_key is None else api_key
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Set COREINFRA_API_KEY or supply api_key.")
    if protocol == "systemone":
        return TypeSafeProvider(
            api_key=key,
            model=model,
            endpoint_url=SYSTEM_ONE_ENDPOINT,
            timeout=timeout,
            transport=transport,
        )
    return OpenAIProvider(
        api_key=key,
        model=model,
        endpoint_url=DECISIONS_ENDPOINT,
        timeout=timeout,
        transport=transport,
    )
