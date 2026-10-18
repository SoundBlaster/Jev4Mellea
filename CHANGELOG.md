# Changelog

## Unreleased

- Add provider-neutral categorical tasks/results and explicit native Choice
  projection, without invented probability/confidence fields.
- Add optional `ResponsesChoiceProvider` for one strict-schema generation
  request containing one or several Choice questions, explicit endpoints/model/
  reasoning/budget settings, safe evidence, and bounded response reading.
- Reject label-only providers before dispatch from existing probability-based
  Mellea helpers. Preserve native results and threshold semantics.
- Add an explicit one-call categorical example, offline transport checks, and
  documentation; live compatibility and downstream migration remain opt-in.

## 0.7.0 — 2026-10-15

- Add a bounded opt-in visual evaluation runner for the synthetic reference,
  using Jev/TypeSafe or Luna/OpenAI providers and explicit Proxy connections.
  Save complete or partial image captures without overwriting prior receipts;
  replay complete captures offline with shared FAR/FRR/uncertainty and latency
  reports. Validate all labels, pixels, and hashes before inference.

- Add a versioned synthetic visual reference: twelve crosswalk diagrams,
  balanced geometry-derived labels, paired cases, provenance, and image hashes.
- Add the offline `make visual-reference` integrity check and mutation tests;
  keep the visual format separate from the text evaluation runner.
- Record a bounded 24-call synthetic visual comparison of direct Jev 1.14 and
  Luna through CoreInfra Decisions, with raw receipts and offline quality/latency
  reports. This does not establish photographic accuracy or model superiority.

- Measure each successful evaluation call and persist `elapsed_ms` in version 2
  prediction snapshots. Report count, missing count, mean, median, population
  standard deviation, min/max, and p90/p95/p99 by provider and returned model.
  Offline replay preserves timing; version 1 snapshots remain readable with
  unavailable latency reported as null.

- Add an opt-in CoreInfra primitive matrix and record one successful bounded
  live check of Jev 1.14/Luna through both protocols plus Luna image Noul.
  Preserve partial receipts on errors; ordinary CI remains offline.

- Add explicit PNG/JPEG image inputs to OpenAI Decisions Noul, Choice, and
  Score, reusing `ImageInput` and `WithImages` for Mellea Requirements. Send
  named base64 image parts through the official SDK; preserve text payloads.

- Add `coreinfra_provider` as an explicit connection factory over the existing
  TypeSafe and OpenAI SDK providers. Select protocol and model independently,
  use the documented Hub operation URLs, and read only `COREINFRA_API_KEY`.

- Add experimental TypeSafe image attachments to Noul, Choice, Score, and mixed
  `system_one` requests. Keep typed results and existing Mellea contracts.
- Add `ImageInput` for local PNG/JPEG bytes and explicit Mellea `ImageBlock`
  conversion, plus `WithImages` for composing visual context with existing
  verifier, classifier, scorer, and Requirement policies.
- Require TypeSafe SDK 0.7.5 or newer below 0.8.0; use its multipart serializer
  and per-request image opt-in header. Explicitly disable request compression
  to preserve the existing text/gateway wire format.
- Add `make image-live-check IMAGE=...` for one opt-in, potentially billable
  mixed-primitive image request. Keep ordinary CI offline.

## 0.6.0 — 2026-10-14

- Add `SubQProvider` for SubQ Decisions Noul, Choice, and Score with strict
  response checks, configurable endpoints, and opt-in live evaluation support.

## 0.5.0 — 2026-10-14

- Add `ScaleDownProvider` for Noul, Choice, and Score decisions through the
  ScaleDown Decisions API, with response validation and usage metadata.
- Add ScaleDown to the labeled evaluation runner and record an opt-in live
  smoke run with reproducible predictions and threshold metrics. The four-case
  synthetic sample demonstrates the workflow and does not establish production
  quality.
- Add mutually exclusive `--endpoint-url` and `--base-url` options to the
  evaluation runner and single-request smoke CLI. Support TypeSafe and OpenAI
  smoke checks with explicit Proxy key selection and provider/model options.
- Add `EVAL_ENDPOINT_URL` and `PROXY_ENDPOINT_URL` Makefile configuration;
  preserve opt-in inference and offline scoring without saving URLs or keys.

## 0.4.0 — 2026-10-11

- Add optional `endpoint_url` to `OpenAIProvider` and `TypeSafeProvider`
  (`JevClient`) for gateways with custom operation paths. The full URL is used
  without appending `/decisions` or `/v1/systemone`; `base_url` retains its API-root
  behavior. Supplying both URL arguments raises `ValueError`.
- Share URL validation and exact-operation routing across the HTTP providers.
  Preserve SDK payloads, authentication, timeouts, metadata, and response
  validation; redirects, environment proxies, and automatic retries stay disabled.

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
