PYTHON ?= python3.13
VENV ?= .venv
MELLEA_VERSION ?= 0.8.0
INSTALL_STAMP := $(VENV)/.installed-mellea-$(MELLEA_VERSION)
PY := $(VENV)/bin/python
OLLAMA_MODEL ?=
EVAL_DATASET ?= examples/evaluation/museum_opening.jsonl
EVAL_PREDICTIONS ?=
EVAL_PROVIDER ?= typesafe
EVAL_MODEL ?=
EVAL_BASE_URL ?=
EVAL_API_KEY_ENV ?=
EVAL_PROVIDER_LABEL ?=
export EVAL_BASE_URL EVAL_API_KEY_ENV EVAL_PROVIDER_LABEL
EVAL_THRESHOLD ?= 0.10,0.90

.DEFAULT_GOAL := help
.PHONY: help install demo lint format-check typecheck quality test check test-integration ollama-test live-test live-check proxy-live-check openai-live-test mellea-ollama evaluate live-evaluate diff-check committed-diff-check clean

help: ## Show the available development commands
	@printf '%s\n' \
	  'install          Install package, Mellea, and tests (MELLEA_VERSION defaults to 0.8.0)' \
	  'demo             Run the offline demo (no keys, service, or model required)' \
	  'lint             Run Ruff lint checks, including a complexity limit' \
	  'format-check     Verify Python formatting with Ruff' \
	  'typecheck        Run strict Mypy checks on the distributable package' \
	  'quality          Run lint, formatting, and type checks' \
	  'test             Run pytest with a branch-coverage threshold (live calls skipped)' \
	  'check            Run quality checks, tests, coverage, and whitespace checks' \
	  'test-integration Run real Mellea Requirement contract tests with mocked provider HTTP' \
	  'ollama-test      Run the local Ollama repair test; Jev HTTP is mocked' \
	  'live-test        Run explicitly enabled, potentially billable Jev smoke tests' \
	  'live-check       Run one potentially billable check from examples/live_check.py' \
	  'proxy-live-check Run one potentially billable Jev check through a Proxy' \
	  'openai-live-test Run three opt-in Decisions smoke tests (Noul, Choice, Score; billable)' \
	  'mellea-ollama    Run the Mellea + local Ollama example with live Jev checks' \
	  'evaluate         Score a saved prediction file offline (set EVAL_PREDICTIONS)' \
	  'live-evaluate    Explicitly run the labeled dataset through a model' \
	  'diff-check       Check staged and unstaged changes for whitespace errors' \
	  'committed-diff-check Check HEAD against its first parent for whitespace errors' \
	  'clean            Remove the virtualenv and generated Python/test build files'

install: $(INSTALL_STAMP) ## Install the requested Mellea version and development dependencies

$(INSTALL_STAMP): pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet -e '.[mellea,dev]' 'mellea==$(MELLEA_VERSION)'
	rm -f $(VENV)/.installed-mellea-*
	touch $@

demo: $(INSTALL_STAMP) ## Run the offline demo
	$(PY) examples/offline_demo.py

lint: $(INSTALL_STAMP) ## Run Ruff lint rules, including a cyclomatic complexity limit
	$(PY) -m ruff check --output-format=github .

format-check: $(INSTALL_STAMP) ## Verify all Python files use Ruff formatting
	$(PY) -m ruff format --check .

typecheck: $(INSTALL_STAMP) ## Run strict static type checks for the public package
	$(PY) -m mypy

quality: lint format-check typecheck ## Run the static quality gates

test: $(INSTALL_STAMP) ## Run tests and enforce the configured branch-coverage threshold
	$(PY) -m pytest -q --cov=mellea_jev --cov-branch --cov-report=term-missing

check: quality test diff-check ## Run the same quality gate used by GitHub Actions

test-integration: $(INSTALL_STAMP) ## Exercise real Mellea Requirement.validate with mocked providers
	$(PY) -m pytest -q tests/test_mellea_integration.py

ollama-test: $(INSTALL_STAMP) ## Exercise real local generation; Jev HTTP is mocked and no API key is used
	@test -n '$(OLLAMA_MODEL)' || { echo 'Set OLLAMA_MODEL to a model already installed in Ollama.' >&2; exit 2; }
	RUN_LOCAL_OLLAMA=1 OLLAMA_MODEL='$(OLLAMA_MODEL)' $(PY) -m pytest -q tests/test_mellea_ollama.py

live-test: $(INSTALL_STAMP) ## Send explicitly enabled requests to TypeSafe; this may incur charges
	@test -n "$${TYPESAFE_API_KEY:-}" || { echo 'Set TYPESAFE_API_KEY first.' >&2; exit 2; }
	RUN_LIVE_JEV=1 $(PY) -m pytest -q tests/test_live_jev.py

proxy-live-check: $(INSTALL_STAMP) ## Run one potentially billable Jev check through a configured Proxy
	@test -n "$${PROXY_API_KEY:-}" || { echo 'Set PROXY_API_KEY first.' >&2; exit 2; }
	@test -n "$${PROXY_BASE_URL:-}" || { echo 'Set PROXY_BASE_URL to the TypeSafe-compatible API root first.' >&2; exit 2; }
	$(PY) examples/live_check.py --base-url "$${PROXY_BASE_URL}" --api-key-env PROXY_API_KEY

live-check: $(INSTALL_STAMP) ## Run one live Jev check using the sample input; this may incur charges
	@test -n "$${TYPESAFE_API_KEY:-}" || { echo 'Set TYPESAFE_API_KEY first.' >&2; exit 2; }
	$(PY) examples/live_check.py

openai-live-test: $(INSTALL_STAMP) ## Send up to three opt-in OpenAI requests (one per primitive); may incur charges
	@test -n "$${OPENAI_API_KEY:-}" || { echo 'Set OPENAI_API_KEY first.' >&2; exit 2; }
	RUN_LIVE_OPENAI=1 $(PY) -m pytest -q -x --tb=short tests/test_live_openai.py

mellea-ollama: $(INSTALL_STAMP) ## Run the Mellea + Ollama example; Jev requests may incur charges
	@test -n '$(OLLAMA_MODEL)' || { echo 'Set OLLAMA_MODEL to a model already installed in Ollama.' >&2; exit 2; }
	@test -n "$${TYPESAFE_API_KEY:-}" || { echo 'Set TYPESAFE_API_KEY first.' >&2; exit 2; }
	OLLAMA_MODEL='$(OLLAMA_MODEL)' $(PY) examples/mellea_ollama.py

evaluate: $(INSTALL_STAMP) ## Compute metrics from saved predictions; performs no inference
	@test -n '$(EVAL_PREDICTIONS)' || { echo 'Set EVAL_PREDICTIONS to a saved prediction JSONL file.' >&2; exit 2; }
	$(PY) examples/evaluate.py '$(EVAL_DATASET)' --predictions '$(EVAL_PREDICTIONS)' --threshold '$(EVAL_THRESHOLD)'

live-evaluate: $(INSTALL_STAMP) ## Explicitly evaluate labeled examples; may send text or download a local model
	@set --; \
	if [ -n "$${EVAL_BASE_URL:-}" ]; then set -- "$$@" --base-url "$$EVAL_BASE_URL"; fi; \
	if [ -n "$${EVAL_API_KEY_ENV:-}" ]; then set -- "$$@" --api-key-env "$$EVAL_API_KEY_ENV"; fi; \
	if [ -n "$${EVAL_PROVIDER_LABEL:-}" ]; then set -- "$$@" --provider-label "$$EVAL_PROVIDER_LABEL"; fi; \
	$(PY) examples/evaluate.py '$(EVAL_DATASET)' --live --provider '$(EVAL_PROVIDER)' $(if $(EVAL_MODEL),--model '$(EVAL_MODEL)',) --threshold '$(EVAL_THRESHOLD)' $(if $(EVAL_PREDICTIONS),--save-predictions '$(EVAL_PREDICTIONS)',) "$$@"

diff-check: ## Check staged and unstaged changes for whitespace errors
	git diff --check HEAD

committed-diff-check: ## Check the latest committed patch for whitespace errors
	git diff --check HEAD^1 HEAD

clean: ## Remove generated local files
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .coverage build dist src/*.egg-info
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
