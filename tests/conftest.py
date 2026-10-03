import pytest

from ai_chat import AIEngine


@pytest.fixture
def engine():
    return AIEngine()
