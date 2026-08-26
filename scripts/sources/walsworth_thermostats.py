from __future__ import annotations

from .base import SourceResult, not_implemented_result


SOURCE_NAME = "Walsworth thermostats"


def fetch_monthly() -> SourceResult:
    return not_implemented_result(SOURCE_NAME)

