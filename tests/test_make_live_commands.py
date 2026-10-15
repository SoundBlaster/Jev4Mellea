"""Exercise Make recipes with an argument recorder, never provider inference."""

import json
import os
import subprocess
import sys

import pytest


@pytest.fixture
def make_command(tmp_path):
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    python = venv / "bin" / "python"
    python.write_text(f"#!{sys.executable}\nimport json, sys\nprint(json.dumps(sys.argv[1:]))\n")
    python.chmod(0o755)
    stamp = venv / ".installed-mellea-0.8.0"
    stamp.touch()
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("PROXY_", "EVAL_"))
        and key not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES")
    }
    environment["PROXY_API_KEY"] = "mock-secret-key"

    def run(target, **options):
        return subprocess.run(
            [
                "make",
                "--silent",
                target,
                f"VENV={venv}",
                "MELLEA_VERSION=0.8.0",
                *[f"{key}={value}" for key, value in options.items()],
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
        )

    return run


@pytest.mark.parametrize("provider", ["typesafe", "openai"])
@pytest.mark.parametrize(
    "variable,flag", [("PROXY_BASE_URL", "--base-url"), ("PROXY_ENDPOINT_URL", "--endpoint-url")]
)
def test_proxy_smoke_forwards_configuration(make_command, provider, variable, flag):
    url = "https://proxy.example/tenant/a%2Fb/decide/"
    result = make_command(
        "proxy-live-check", PROXY_PROVIDER=provider, PROXY_MODEL="custom-model", **{variable: url}
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "examples/live_check.py",
        "--provider",
        provider,
        "--api-key-env",
        "PROXY_API_KEY",
        flag,
        url,
        "--model",
        "custom-model",
    ]
    assert "mock-secret-key" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "options",
    [
        {},
        {
            "PROXY_BASE_URL": "https://proxy.example",
            "PROXY_ENDPOINT_URL": "https://proxy.example/decide",
        },
    ],
)
def test_proxy_smoke_rejects_missing_or_conflicting_urls(make_command, options):
    result = make_command("proxy-live-check", **options)
    assert result.returncode != 0 and not result.stdout
    assert "PROXY_BASE_URL" in result.stderr and "PROXY_ENDPOINT_URL" in result.stderr


def test_live_evaluation_forwards_exact_url(make_command):
    url = "https://proxy.example/tenant/a%2Fb/decide/"
    result = make_command(
        "live-evaluate",
        EVAL_PROVIDER="openai",
        EVAL_ENDPOINT_URL=url,
        EVAL_API_KEY_ENV="PROXY_API_KEY",
        EVAL_PROVIDER_LABEL="proxy-a",
    )
    assert result.returncode == 0, result.stderr
    argv = json.loads(result.stdout)
    assert argv[argv.index("--endpoint-url") + 1] == url
    assert argv[argv.index("--api-key-env") + 1] == "PROXY_API_KEY"
    assert argv[argv.index("--provider-label") + 1] == "proxy-a"
    assert "--base-url" not in argv and "--live" in argv
    assert "mock-secret-key" not in result.stdout + result.stderr


def test_subq_smoke_requires_key_and_runs_one_provider_check(make_command):
    result = make_command("subq-live-check")
    assert result.returncode != 0 and "SUBQ_API_KEY" in result.stderr
    result = make_command("subq-live-check", SUBQ_API_KEY="mock-subq-key")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == ["examples/live_check.py", "--provider", "subq"]
    assert "mock-subq-key" not in result.stdout + result.stderr


def test_image_smoke_requires_explicit_file_and_passes_quoted_path(make_command):
    result = make_command("image-live-check", TYPESAFE_API_KEY="mock-image-key", IMAGE="")
    assert result.returncode != 0 and "Set IMAGE" in result.stderr
    path = "/tmp/photo with 'quotes' and spaces.png"
    result = make_command(
        "image-live-check", TYPESAFE_API_KEY="mock-image-key", IMAGE=path, IMAGE_MODEL="jev-1.14.0"
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == [
        "examples/live_image_check.py",
        path,
        "--model",
        "jev-1.14.0",
    ]
    assert "mock-image-key" not in result.stdout + result.stderr
