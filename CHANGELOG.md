# Changelog

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
