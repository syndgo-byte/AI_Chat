"""Common classification, answer generation, and recommendations."""

from pathlib import Path

__version__ = "0.3.0"
ROOT = Path(__file__).resolve().parent.parent


def manifest() -> dict:
    return {
        "id": "ai_chat",
        "kind": "module",
        "version": __version__,
        "description": "고객 챗봇 · 민원 답변 · 공지 작성",
        "provides": ["ai.chat"],
        "requires": [],
        "tools": [
            {"name":"ai_chat.compose","description":"민원 답변·공지 초안 생성","auth_required":"user","billing_model":"free"},
            {"name":"ai_chat.support_policy","description":"Manage service-scoped automatic answer policy","auth_required":"user","billing_model":"free"},
            {"name":"ai_chat.review_knowledge","description":"Approve learned answers with audit history","auth_required":"user","billing_model":"free"},
            {"name": "ai_chat.message", "description": "Chat with Google AI and draft complaint facts", "auth_required": "user", "billing_model": "free"},
            {"name": "ai_chat.complaint_draft", "description": "Review or edit a complaint draft", "auth_required": "user", "billing_model": "free"},
            {"name": "ai_chat.submit_complaint", "description": "Submit a confirmed complaint through the complaint module", "auth_required": "user", "billing_model": "free"},
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


__all__ = ["AIEngine", "Classifier", "AnswerGenerator", "AutoSendLearner", "Chatbot", "GeminiProvider", "ChatError", "SupportStore", "ServiceChatClient", "manifest"]


def __getattr__(name: str):
    # The Hub loads this file as a standalone manifest module, so package
    # imports must wait until a consumer requests the public classes.
    if name == "SupportStore":
        from .support import SupportStore
        return SupportStore
    if name == "ServiceChatClient":
        from .client import ServiceChatClient
        return ServiceChatClient
    if name in {"Chatbot", "GeminiProvider", "ChatError"}:
        from . import chatbot
        return getattr(chatbot, name)
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
