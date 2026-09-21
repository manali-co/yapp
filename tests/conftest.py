import os

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get("TYPESAFE_API_KEY"):
        return
    skip = pytest.mark.skip(reason="TYPESAFE_API_KEY not set")
    for item in items:
        if "jev" in item.keywords:
            item.add_marker(skip)
