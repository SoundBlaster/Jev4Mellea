# Roadmap

This roadmap describes proposed development for the Jev adapter. Priorities may
change as the TypeSafe API and Mellea integration are exercised by real client
projects. A listed feature is not a release commitment.

## In progress — Choice support (PR #3)

- Classify text into a configured set of Choice labels.
- Expose the selected label, confidence, probabilities, model, and request ID.
- Adapt classification to a Mellea `Requirement` with an expected label and an
  optional minimum-confidence policy.
- Exercise the real Mellea `Requirement.validate` contract with mocked Jev HTTP
  responses; keep live Jev checks opt-in.

## Next — Complete the primitive and request model

- Add Jev `Score` support for ordered scales, with response validation and a
  Mellea requirement bridge where the primitive semantics support it.
- Support multiple named questions in one TypeSafe request, including mixed
  Noul and Choice questions; preserve per-question results and errors.
- Accept the structured Choice criteria forms supported by the TypeSafe API.
- Allow callers to provide Noul criteria in addition to the current instruction.
- Add contract tests for malformed, partial, and unexpected multi-question
  responses before relying on these capabilities in client code.

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
