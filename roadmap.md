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
4. **Deferred.** Keep provider construction explicit. Revisit configuration or
   entry-point discovery if client projects need dynamic provider selection and
   there is clear ownership for maintaining the integration.

The second provider now exercises the shared contracts without importing
TypeSafe wire models, while existing Jev callers keep `JevClient`. This meets
the current portability milestone; it does not by itself establish a need for
plugin discovery.

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

## Then — Publish a compatibility matrix

- The project declares Python 3.11+ and pins the Mellea integration to 0.7.0;
  CI currently exercises Python 3.11 and Mellea 0.7.0.
- Decide which additional Python and Mellea versions to support, test those
  combinations in CI, and document only combinations that pass.

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
