# Roadmap

This roadmap describes proposed development for the Jev adapter. Priorities may
change as the TypeSafe API and Mellea integration are exercised by real client
projects. A listed feature is not a release commitment.

## Provider portability

The goal is to let client projects select another evaluator without changing
their Mellea requirements or depending on a large plugin framework. Add each
stage in a separate pull request and keep `JevClient` as a supported backend.

1. **Complete (PR #11).** Define small provider-neutral Noul, Choice, and Score
   contracts. Mellea helpers depend on these contracts, and callers can
   implement a single primitive without inheriting from package classes.
2. **Complete (PRs #12 and #14).** Isolate TypeSafe request/response handling
   behind the official Python SDK while retaining `JevClient` as the compatible
   public entry point.
3. **Complete (PR #13).** Implement a Laya-MLX provider using its local System One
   API, with the dependency and model loading kept optional. Exercise the
   contracts against this second API and document differences such as its
   entropy-based Choice confidence.
4. **Completed — OpenAI Noul, Choice, Score, and Noul evaluation runner.**
   **Evidence checked October 7, 2026.** Following the DevDay limited preview,
   OpenAI [announced public beta on October 6](https://community.openai.com/t/decisions-api-is-now-available-in-public-beta/1403877),
   available to all developers. The [Decisions guide](https://developers.openai.com/api/docs/guides/decisions)
   identifies `gpt-6-luna` as the only supported model, with general availability
   expected in the coming weeks. Public beta permits integration work; GA and
   a successful request from our account remain separate evidence.

   The technical contract is now published: `POST /v1/decisions`, shared text
   or image input, and `predicate`, `choice`, and `score` questions. The guide
   requires Python SDK 3.26.0 or later; the official
   [Python API reference](https://developers.openai.com/api/reference/python/resources/decisions/methods/create)
   documents `client.decisions.create(...)`. Decisions is an API capability
   backed by Luna. OpenAI now reports faster decisions than the Responses API;
   measure latency on our own workload before making package performance claims.
   Implement each stage in a separate pull request:
   - **Completed — Noul foundation.** Construct `OpenAIProvider` explicitly using the
     official Python SDK, with an optional `openai` dependency. Map a single
     predicate answer to `NoulResult`, retaining model, request ID, and usage.
     Keep SDK types out of Mellea contracts, retries explicitly disabled, and
     errors safe. Verify SDK-version compatibility, request mapping, refusal,
     and malformed or missing answers with mocks; add an opt-in live smoke test.
   - **Completed ([PR #36](https://github.com/SoundBlaster/Jev4Mellea/pull/36)) — Choice.** Adapt configured labels and criteria to fixed choices and
     return `ChoiceResult`. Validate selected labels, distributions, and
     confidence semantics against the documented contract. Preserve existing
     Mellea classifier and requirement interfaces through the Choice protocol.
   - **Completed ([PR #37](https://github.com/SoundBlaster/Jev4Mellea/pull/37)) — Score.** Adapt the configured scale and rubric to score levels and
     return `ScoreResult`. Establish how the vendor's score and confidence map
     to our scale; reject unsupported mappings explicitly.
   - **Completed ([PR #38](https://github.com/SoundBlaster/Jev4Mellea/pull/38)) — Noul evaluation runner.** Select OpenAI,
     TypeSafe, or Laya for the same versioned labeled dataset. Save source labels,
     returned models, and raw probabilities; report false-acceptance,
     false-rejection, and uncertain rates for offline threshold sweeps.
     Live runs remain opt-in, including explicit Proxy URL/key configuration.
   - **Completed ([PR #40](https://github.com/SoundBlaster/Jev4Mellea/pull/40)) — Opt-in primitive smoke tests.** Exercise Noul, Choice, and
     Score through the existing adapters, one request per primitive; stop on the
     first failure with `make openai-live-test`. Ordinary CI remains offline.
     A live pass requires an available key and is separate from adding the tests.
   - **Next — Live calibration and comparison.** Run OpenAI on representative
     labeled data, record latency and cost separately, and establish calibration
     before claiming comparable confidence or interchangeable thresholds.
5. **Deferred.** Keep provider construction explicit. Revisit configuration or
   entry-point discovery if client projects need dynamic provider selection and
   there is clear ownership for maintaining the integration.

The second provider now exercises the shared contracts without importing
TypeSafe wire models, while existing Jev callers keep `JevClient`. This meets
the current portability milestone; it does not by itself establish a need for
plugin discovery.

## CoreInfra Hub compatibility

- **Implemented; awaiting merge.** Compose existing TypeSafe/OpenAI providers
  through `coreinfra_provider`, with explicit model/protocol selection and Hub
  credentials. Use common PNG/JPEG image inputs for OpenAI Decisions and Mellea
  Requirements. Keep exact operation URLs and provider-specific SDK types internal.
- **Live smoke completed October 15, 2026.** Jev 1.14 (`jev-preview`) and Luna
  Noul/Choice/Score worked through both Hub protocols, plus one Luna Decisions
  image Noul. Record thirteen receipts and SDK/source provenance separately from
  quality benchmarks. No live claim is made for other image routes or batching.
- **Next — Per-route calibration.** Run a frozen labeled dataset with distinct
  provider/protocol labels before reusing thresholds or comparing confidence.
  Keep uploads opt-in and record actual returned model IDs.

## Deferred — Decision 3.0 on Apple Silicon

- **Start condition:** a maintained, ready-to-run distribution of
  [Decision 3.0 (D3)](https://huggingface.co/collections/vllm-sr/decision-30)
  documents working native Apple Silicon acceleration, for example through
  MLX, Core ML, Metal, Ollama, or LM Studio. Available weights, an experimental
  conversion, or an unverified MPS device setting alone do not meet this condition.
- Start with `d3-edge` (0.59B) on the user's MacBook Pro M4 Pro with 24 GB unified
  memory; compare `d3-lite` only after the smaller model passes the checks.
- Verify individual Noul, Choice, and Score calls through the existing
  provider contracts, including distributions, confidence semantics, model,
  request ID, usage when available, and safe handling of malformed responses.
  Prefer configuring an existing compatible provider over adding a new adapter.
- Check batched questions separately against the upstream D3 runtime, or through
  `JevClient.system_one` if the runtime exposes a compatible HTTP API. The
  provider-neutral protocols currently cover individual primitive calls only;
  batching is not a requirement of those contracts.
- Evaluate representative labeled examples with a distinct provider label.
  Record false-acceptance, false-rejection, and uncertain rates by model and
  threshold pair; measure cold startup, warm p50/p95 latency, and peak memory
  separately. Record the model revision, runtime version, and actual backend.
- Keep model downloads and local inference opt-in and outside ordinary CI.
  Completion requires a successful run on the target Mac and saved evaluation
  results, with any differences from the upstream model documented.

## Completed primitive capabilities

### Choice support (PR #3)

- Classify text into a configured set of Choice labels.
- Expose the selected label, confidence, probabilities, model, and request ID.
- Adapt classification to a Mellea `Requirement` with an expected label and an
  optional minimum-confidence policy.
- Exercise the real Mellea `Requirement.validate` contract with mocked Jev HTTP
  responses; keep live Jev checks opt-in.

### Score support (PR #4)

- Add Jev `Score` support for ordered scales, with response validation and a
  Mellea `Requirement` bridge for configurable inclusive score bounds.

### Batched questions (PR #6)

- Support multiple named Noul, Choice, and Score questions in one TypeSafe
  request; preserve typed per-question results and fail closed on mismatched IDs.

### Broaden primitive criteria (PRs #7 and #8)

- Accept the structured Choice criteria forms supported by the TypeSafe API.
- Allow callers to provide Noul criteria in addition to the current instruction.

## Experimental image input

- **Implemented; awaiting merge.** Add explicit `ImageInput` attachments to
  TypeSafe Noul, Choice, Score, and mixed batches through SDK 0.7.5 multipart.
  Preserve primitive results and compose existing Mellea helpers with
  `WithImages`; convert Mellea `ImageBlock` explicitly, without scanning history
  or fetching URLs. Keep live image uploads opt-in and ordinary CI offline.
- **Next — Visual evaluation reference.** Define non-sensitive labeled image
  examples and observable predicates before measuring semantic quality. Keep
  edited or generated image provenance with the reference; a successful smoke
  request is not an accuracy benchmark or a parking-law determination.
- **Deferred — Box.** Introduce a separate bounding-box result contract only
  for a concrete localization use case. Account for Jev 1.14 requirements and
  use a separate presence predicate when an object may be absent.

## Completed observability foundations

- **Usage metadata (PR #9):** expose available TypeSafe token counts without
  making them part of a validation decision.
- **Live smoke checks:** Noul and Choice checks require explicit opt-in and an
  API key; the README describes billing and data-submission implications.

## Completed — Measure quality on labeled examples

- Define versioned, task-specific, non-sensitive JSONL examples with explicit
  expected accept/reject outcomes; include a small museum-opening example as a
  format demonstration, not a quality benchmark.
- Add an evaluation runner that reports false-acceptance, false-rejection, and
  uncertain rates by provider, returned model, and threshold pair. Saved raw
  predictions allow offline threshold comparisons without another request.
- Require `--live` before provider inference. Publish quality claims only with
  the dataset version, sample counts, provider/model, thresholds, metric
  denominators, and limitations; thresholds remain caller policy.

## Completed — Compatibility matrix (PR #22)

- The project declares Python 3.11+ and supports Mellea `>=0.7.0,<0.9.0`.
- CI runs the quality and test suites on Python 3.11, 3.12, 3.13, and 3.14
  with Mellea 0.7.0 and 0.8.0 (expanded in PR #29). Other minor versions are
  not currently declared compatible.

## Visual evaluation

- **Implemented; awaiting merge — Synthetic reference.** Twelve procedural
  crosswalk diagrams with six expected accepts and six rejects, controlled
  pairs, geometry-derived labels, provenance, exact image hashes, and offline
  pixel/integrity checks. No model output is used as the scoring reference;
  these labels do not claim human adjudication or photographic accuracy.
- **Next — Visual runner and metrics.** Load only each example's candidate and
  named image bytes into the image-capable provider; verify every asset before
  inference. Keep labels and annotation evidence out of model context, bind
  saved predictions to the full reference digest, and reuse FAR/FRR/uncertainty
  definitions. Live requests remain explicit opt-in with a bounded call count.
- **Later — Photographic reference.** Collect representative, non-sensitive
  photographs with usage rights and human-reviewed observable predicates.
  Preserve editing provenance and distinguish spatial overlap from a legal
  parking determination. Measure that set separately from synthetic diagrams.

## Before production use

- Decide whether an async client and a Mellea integration point that can await
  network I/O are needed for target deployments.
- The TypeSafe provider already uses a configurable finite timeout and disables
  automatic retries. Define any provider-specific rate-limit or idempotency
  policy without assuming that cancellation stops server-side work.
- Document deployment responsibilities for sensitive text, retention,
  redaction, application logging, and operational telemetry. The README already
  explains that candidate text and references are sent to TypeSafe and that the
  adapter does not log request bodies or API keys.
- Validate latency, cost, and classification quality against each deployment's
  workload and acceptance policy.

## Out of scope until there is a concrete use case

- Streaming, signed receipts, automatic S2 or human-review routing, and a full
  orchestration layer. These can be composed by client applications today and
  should be added only when their contracts and ownership are clear.

## Completion criteria

A roadmap item is ready to ship when its public API and failure semantics are
documented, its response contract has automated coverage, and the relevant
Mellea integration has been checked against the supported version. Live quality
claims require labeled evaluation data; mocked tests alone do not establish
Jev's accuracy, production readiness, or service availability.
