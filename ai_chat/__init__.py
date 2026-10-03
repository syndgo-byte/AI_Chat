"""Common classification, answer generation, and recommendations."""

from pathlib import Path

__version__ = "0.1.0"
ROOT = Path(__file__).resolve().parent.parent


def manifest() -> dict:
    return {
        "id": "ai_chat",
        "kind": "module",
        "version": __version__,
        "description": "AI classification, answer generation, and recommendation engine",
        "provides": [],
        "requires": [],
        "tools": [
            {
                "name": "ai_chat.analyze",
                "description": "Classify an item and generate a draft answer",
                "auth_required": "user",
                "billing_model": "free",
            },
            {
                "name": "ai_chat.suggest",
                "description": "Recommend similar answered items",
                "auth_required": "user",
                "billing_model": "free",
            },
        ],
        "license": {
            "service_id": "ai_chat",
            "environment": "dev",
            "status": "active",
            "issued_at": "2026-10-03T00:00:00+00:00",
            "issued_by": "mcp_hub",
        },
        "source": {"root": str(ROOT), "entry": "ai_chat/__init__.py"},
    }


__all__ = ["AIEngine", "Classifier", "AnswerGenerator", "AutoSendLearner", "manifest"]


def __getattr__(name: str):
    # The Hub loads this file as a standalone manifest module, so package
    # imports must wait until a consumer requests the public classes.
    if name == "AutoSendLearner":
        from .learner import AutoSendLearner

        return AutoSendLearner
    if name == "AIEngine":
        from .engine import AIEngine

        return AIEngine
    if name == "Classifier":
        from .classifier import Classifier

        return Classifier
    if name == "AnswerGenerator":
        from .generator import AnswerGenerator

        return AnswerGenerator
    raise AttributeError(name)
