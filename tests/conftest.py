import os

import pytest

pytest_plugins = ["tests.scorer_support"]  # scorer venv fixtures (scorer_py, ...)


def pytest_addoption(parser):
    parser.addoption("--run-api", action="store_true", help="run api-marked tests (real spend)")


def pytest_configure(config):
    """With ``-n``, keep each test file on one worker unless ``--dist`` is given. Module fixtures
    (the scripted pilot pipeline) are then built once, not once per worker that runs one of its
    tests, which used to multiply the load (and the scorer timings) several times over."""
    args = config.invocation_params.args
    explicit = any(a == "-d" or a == "--dist" or a.startswith("--dist=") for a in args)
    if getattr(config.option, "numprocesses", None) and config.option.dist == "load" and not explicit:
        config.option.dist = "loadfile"


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-api") and os.environ.get("LRAE_CONFIRM_SPEND") == "1":
        config.option.markexpr = ""
        return
    skip = pytest.mark.skip(reason="api tests need --run-api and LRAE_CONFIRM_SPEND=1")
    for item in items:
        if "api" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_spend_outside_api_tests(request, monkeypatch):
    """Only `api` tests may see LRAE_CONFIRM_SPEND; everything else must never reach the real CLI."""
    if "api" not in request.keywords:
        monkeypatch.delenv("LRAE_CONFIRM_SPEND", raising=False)
