# Changelog

## 0.3.0 — 2026-10-09

- Extend the optional OpenAI Decisions provider with Choice and Score using
  the official Python SDK. Preserve the existing `JevClassifier`, `JevScorer`,
  and Mellea Requirement interfaces; keep SDK types internal.
- Validate complete Choice distributions and ordered Score legends, bounds,
  and probability-weighted values. Retain model, request ID, and token usage.
- Add OpenAI to the Noul evaluation runner. Compare TypeSafe, OpenAI, and Laya
  on the same versioned labeled dataset; save raw predictions and report false
  acceptance, false rejection, and uncertainty by source, model, and thresholds.
- Support explicit TypeSafe/OpenAI Proxy URL and key-variable selection in
  live evaluation. Distinguish gateway source labels even when model names match.
- Add opt-in OpenAI Noul, Choice, and Score smoke tests, exercised with mocked
  SDK transport in CI. `make openai-live-test` sends at most three requests and
  stops at the first failure. Redirects and automatic retries remain disabled.
- Record a small live TypeSafe-compatible Proxy evaluation with reproducible
  offline metrics; four synthetic examples do not establish production quality.

Python 3.11–3.14 and Mellea 0.7.0/0.8.0 remain the CI-tested combinations.
Native OpenAI live compatibility has not yet been verified with an official
OpenAI key. The experimental ProxyAPI provider is parked on `proxyapi-adapter`
and is not included in this release; its live checks use a different wire contract.

## 0.2.1 — 2026-10-08

- Replace vendor-specific gateway examples with an abstract Proxy in the
  README, API notes, and mock fixtures.
- Replace `make coreinfra-live-check` with `make proxy-live-check`. Set
  `PROXY_BASE_URL` and `PROXY_API_KEY` explicitly; the helper uses a neutral
  greeting example and does not hardcode a vendor URL.
- Preserve the provider APIs and the historical 0.2.0 live-check results.

## 0.2.0 — 2026-10-08

- Add an optional OpenAI Decisions provider for Noul verification through the
  official Python SDK. Install with `pip install 'mellea-jev-adapter[openai]'`.
- Support explicit gateway URLs in both OpenAIProvider and TypeSafeProvider
  (JevClient). Defaults remain the official endpoints; environment URL
  overrides are ignored. Redirects and automatic retries remain disabled.
- Verify CoreInfra Jev Noul, Choice, Score, and mixed-question batches with
  real API requests. Add `make coreinfra-live-check` for opt-in verification.
- Support Mellea 0.7.0 and 0.8.0, with CI covering both versions on Python
  3.11–3.14. SDK response types remain internal to providers.

CoreInfra live checks validate compatibility on selected inputs, not general
model accuracy. The adapter retains its dictionary `state` contract.
