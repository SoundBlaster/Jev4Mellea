PYTHON ?= python3.13
VENV ?= .venv
PY := $(VENV)/bin/python
OLLAMA_MODEL ?=
EVAL_DATASET ?= examples/evaluation/museum_opening.jsonl
EVAL_PREDICTIONS ?=
EVAL_PROVIDER ?= typesafe
EVAL_MODEL ?=
EVAL_THRESHOLD ?= 0.10,0.90

.DEFAULT_GOAL := help
.PHONY: help install demo lint format-check typecheck quality test check test-integration ollama-test live-test live-check mellea-ollama evaluate live-evaluate diff-check committed-diff-check clean

help: ## Show the available development commands
	@printf '%s\n' \
	  'install          Create .venv and install the package, Mellea, and test dependencies' \
	  'demo             Run the offline demo (no keys, service, or model required)' \
	  'lint             Run Ruff lint checks, including a complexity limit' \
	  'format-check     Verify Python formatting with Ruff' \
	  'typecheck        Run strict Mypy checks on the distributable package' \
	  'quality          Run lint, formatting, and type checks' \
	  'test             Run pytest with a branch-coverage threshold (live calls skipped)' \
	  'check            Run quality checks, tests, coverage, and whitespace checks' \
	  'test-integration Run real Mellea Requirement contract tests with mocked Jev HTTP' \
	  'ollama-test      Run the local Ollama repair test; Jev HTTP is mocked' \
	  'live-test        Run explicitly enabled, potentially billable Jev smoke tests' \
	  'live-check       Run one potentially billable check from examples/live_check.py' \
	  'mellea-ollama    Run the Mellea + local Ollama example with live Jev checks' \
	  'evaluate         Score a saved prediction file offline (set EVAL_PREDICTIONS)' \
	  'live-evaluate    Explicitly run the labeled dataset through a model' \
	  'diff-check       Check staged and unstaged changes for whitespace errors' \
	  'committed-diff-check Check HEAD against its first parent for whitespace errors' \
	  'clean            Remove the virtualenv and generated Python/test build files'

install: $(VENV)/.installed ## Create the virtual environment and install dependencies

$(VENV)/.installed: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(PY) -m pip install --quiet -e '.[mellea,dev]'
	touch $@

demo: $(VENV)/.installed ## Run the offline demo
	$(PY) examples/offline_demo.py

lint: $(VENV)/.installed ## Run Ruff lint rules, including a cyclomatic complexity limit
	$(PY) -m ruff check --output-format=github .

format-check: $(VENV)/.installed ## Verify all Python files use Ruff formatting
	$(PY) -m ruff format --check .

typecheck: $(VENV)/.installed ## Run strict static type checks for the public package
	$(PY) -m mypy

quality: lint format-check typecheck ## Run the static quality gates

test: $(VENV)/.installed ## Run tests and enforce the configured branch-coverage threshold
	$(PY) -m pytest -q --cov=mellea_jev --cov-branch --cov-report=term-missing

check: quality test diff-check ## Run the same quality gate used by GitHub Actions

test-integration: $(VENV)/.installed ## Exercise the real Mellea Requirement.validate hook with Jev mocked
	$(PY) -m pytest -q tests/test_mellea_integration.py

ollama-test: $(VENV)/.installed ## Exercise real local generation; Jev HTTP is mocked and no API key is used
	@test -n '$(OLLAMA_MODEL)' || { echo 'Set OLLAMA_MODEL to a model already installed in Ollama.' >&2; exit 2; }
	RUN_LOCAL_OLLAMA=1 OLLAMA_MODEL='$(OLLAMA_MODEL)' $(PY) -m pytest -q tests/test_mellea_ollama.py

live-test: $(VENV)/.installed ## Send explicitly enabled requests to TypeSafe; this may incur charges
	@test -n "$${TYPESAFE_API_KEY:-}" || { echo 'Set TYPESAFE_API_KEY first.' >&2; exit 2; }
	RUN_LIVE_JEV=1 $(PY) -m pytest -q tests/test_live_jev.py

live-check: $(VENV)/.installed ## Run one live Jev check using the sample input; this may incur charges
	@test -n "$${TYPESAFE_API_KEY:-}" || { echo 'Set TYPESAFE_API_KEY first.' >&2; exit 2; }
	$(PY) examples/live_check.py

mellea-ollama: $(VENV)/.installed ## Run the Mellea + Ollama example; Jev requests may incur charges
	@test -n '$(OLLAMA_MODEL)' || { echo 'Set OLLAMA_MODEL to a model already installed in Ollama.' >&2; exit 2; }
	@test -n "$${TYPESAFE_API_KEY:-}" || { echo 'Set TYPESAFE_API_KEY first.' >&2; exit 2; }
	OLLAMA_MODEL='$(OLLAMA_MODEL)' $(PY) examples/mellea_ollama.py

evaluate: $(VENV)/.installed ## Compute metrics from saved predictions; performs no inference
	@test -n '$(EVAL_PREDICTIONS)' || { echo 'Set EVAL_PREDICTIONS to a saved prediction JSONL file.' >&2; exit 2; }
	$(PY) examples/evaluate.py '$(EVAL_DATASET)' --predictions '$(EVAL_PREDICTIONS)' --threshold '$(EVAL_THRESHOLD)'

live-evaluate: $(VENV)/.installed ## Explicitly evaluate labeled examples; may send text or download a local model
	$(PY) examples/evaluate.py '$(EVAL_DATASET)' --live --provider '$(EVAL_PROVIDER)' $(if $(EVAL_MODEL),--model '$(EVAL_MODEL)',) --threshold '$(EVAL_THRESHOLD)' $(if $(EVAL_PREDICTIONS),--save-predictions '$(EVAL_PREDICTIONS)',)

diff-check: ## Check staged and unstaged changes for whitespace errors
	git diff --check HEAD

committed-diff-check: ## Check the latest committed patch for whitespace errors
	git diff --check HEAD^1 HEAD

clean: ## Remove generated local files
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache .coverage build dist src/*.egg-info
	find src tests -type d -name __pycache__ -prune -exec rm -rf {} +
