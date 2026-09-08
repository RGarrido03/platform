"""
Pytest custom markers for Huly integration
"""

import pytest


def huly(case_id: str = None, suite: str = None, priority: str = "medium", type: str = "functional"):
    """
    Decorator marker to bind tests to Huly Test Management.

    Usage:
        @pytest.mark.huly(case_id="673abc111111111111111111")
        def test_billing():
            ...

        @pytest.mark.huly(suite="Authentication", priority="high")
        def test_login():
            ...
    """
    return pytest.mark.huly(case_id=case_id, suite=suite, priority=priority, type=type)
