import os

import pytest


def pytest_addoption(parser):
    parser.addoption("--run-api", action="store_true", help="run api-marked tests (real spend)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-api") and os.environ.get("LRAE_CONFIRM_SPEND") == "1":
        config.option.markexpr = ""
        return
    skip = pytest.mark.skip(reason="api tests need --run-api and LRAE_CONFIRM_SPEND=1")
    for item in items:
        if "api" in item.keywords:
            item.add_marker(skip)
