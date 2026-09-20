# Roadmap

This roadmap describes proposed development for the Jev adapter. Priorities may
change as the TypeSafe API and Mellea integration are exercised by real client
projects. A listed feature is not a release commitment.

## Provider portability

The goal is to let client projects select another evaluator without changing
their Mellea requirements or depending on a large plugin framework. Add each
stage in a separate pull request and keep `JevClient` as a supported backend.

1. Define small provider-neutral Noul, Choice, and Score contracts. Mellea
   helpers should depend on these contracts, and callers should be able to
   implement a single primitive without inheriting from package classes.
2. Isolate TypeSafe request/response serialization in a TypeSafe provider while
   retaining `JevClient` as the compatible public entry point.
3. Implement a second provider integration to exercise the contracts against a
   different API and record any unavoidable semantic differences.
4. Consider configuration-based selection or an entry-point plugin mechanism
   only after multiple maintained providers demonstrate the need.

Provider contracts are ready for broader use when a second provider can satisfy
them without importing TypeSafe wire models and existing Jev callers remain
compatible. Plugin discovery is deliberately deferred until provider count and
maintenance ownership justify it.

## In progress — Choice support (PR #3)

- Classify text into a configured set of Choice labels.
- Expose the selected label, confidence, probabilities, model, and request ID.
- Adapt classification to a Mellea `Requirement` with an expected label and an
  optional minimum-confidence policy.
- Exercise the real Mellea `Requirement.validate` contract with mocked Jev HTTP
  responses; keep live Jev checks opt-in.

## In progress — Score support

- Add Jev `Score` support for ordered scales, with response validation and a
  Mellea `Requirement` bridge for configurable inclusive score bounds.

## In progress — Batched questions

- Support multiple named Noul, Choice, and Score questions in one TypeSafe
  request; preserve typed per-question results and fail closed on mismatched IDs.

## Next — Broaden primitive criteria

- Accept the structured Choice criteria forms supported by the TypeSafe API.
- Allow callers to provide Noul criteria in addition to the current instruction.

## Then — Make behavior observable and measurable

- Expose available TypeSafe usage metadata, including token counts, without
  making it part of a validation decision.
- Add explicitly enabled live smoke checks for Noul and Choice, with clear
  billing and data-submission notices.
- Measure false-acceptance, false-rejection, and uncertain rates on labeled
  task-specific examples; document that thresholds remain caller policy.
- Publish a tested compatibility matrix for supported Python and Mellea
  versions.

## Before production use

- Decide whether an async client and a Mellea integration point that can await
  network I/O are needed for target deployments.
- Define bounded timeout, rate-limit, and retry behavior with request billing
  and idempotency in mind; never assume cancellation stops server-side work.
- Document deployment controls for sensitive text, logging, redaction, and
  operational telemetry.
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
