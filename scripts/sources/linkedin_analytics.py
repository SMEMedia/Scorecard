from __future__ import annotations

from .base import SourceResult, not_implemented_result


SOURCE_NAME = "LinkedIn Analytics"


def fetch_monthly() -> SourceResult:
    return not_implemented_result(SOURCE_NAME)

