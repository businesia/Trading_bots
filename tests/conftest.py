"""
tests/conftest.py
=================
Общие фикстуры pytest для всего проекта.
"""

import pytest


def pytest_configure(config):
    """Настройка pytest."""
    config.addinivalue_line(
        "markers", "slow: медленные тесты (интеграционные, с реальным API)"
    )


# asyncio mode — автоматически для всех async тестов
pytest_plugins = ["pytest_asyncio"]
