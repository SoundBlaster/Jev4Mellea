"""Shared URL validation and exact-operation routing for synchronous SDKs."""

from __future__ import annotations

import httpx2


class _DefaultBaseURL(str):
    """Keep a string default while distinguishing an explicitly supplied URL."""


def _validated_url(value: str, parameter: str) -> httpx2.URL:
    message = f"{parameter} must be an absolute HTTP(S) URL without credentials or query."
    if not isinstance(value, str) or any(ch.isspace() for ch in value):
        raise ValueError(message)
    try:
        url = httpx2.URL(value)
    except httpx2.InvalidURL:
        raise ValueError(message) from None
    if (
        not url.is_absolute_url
        or url.scheme not in ("http", "https")
        or url.userinfo
        or url.query
        or url.fragment
    ):
        raise ValueError(message)
    return url


class _EndpointTransport(httpx2.BaseTransport):
    """Route only the configured SDK operation to an exact destination URL."""

    def __init__(
        self,
        inner: httpx2.BaseTransport,
        source: httpx2.URL,
        destination: httpx2.URL,
    ) -> None:
        self._inner = inner
        self._source = source
        self._destination = destination

    def handle_request(self, request: httpx2.Request) -> httpx2.Response:
        if request.method != "POST" or request.url != self._source:
            raise httpx2.UnsupportedProtocol("Unexpected SDK operation; refusing to route.")
        headers = request.headers.copy()
        headers["Host"] = self._destination.netloc.decode("ascii")
        forwarded = httpx2.Request(
            request.method,
            self._destination,
            headers=headers,
            stream=request.stream,
            extensions=request.extensions,
        )
        return self._inner.handle_request(forwarded)

    def close(self) -> None:
        self._inner.close()


def _http_client(
    *,
    base_url: str,
    endpoint_url: str | None,
    operation_path: str,
    timeout: float,
    transport: httpx2.BaseTransport | None,
) -> tuple[str, httpx2.Client]:
    if endpoint_url is not None and not isinstance(base_url, _DefaultBaseURL):
        raise ValueError("Supply only one of base_url or endpoint_url.")
    _validated_url(base_url, "base_url")
    sdk_base_url = str(base_url)
    if endpoint_url is not None:
        destination = _validated_url(endpoint_url, "endpoint_url")
        # Keep the SDK on the configured origin; the transport supplies the exact path.
        sdk_base_url = str(destination.copy_with(path="/"))
        source = httpx2.URL(sdk_base_url.rstrip("/") + operation_path)
        inner = (
            transport if transport is not None else httpx2.HTTPTransport(retries=0, trust_env=False)
        )
        transport = _EndpointTransport(inner, source, destination)
    client = httpx2.Client(
        timeout=timeout,
        follow_redirects=False,
        trust_env=False,
        transport=transport,
    )
    return sdk_base_url, client
