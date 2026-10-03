"""Shared classification, draft answer, and related answer lookup."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from .classifier import Classifier
from .generator import AnswerGenerator


class AIEngine:
    """Combine the existing complaint rules behind a reusable interface."""

    def __init__(self, history: dict | None = None):
        self.classifier = Classifier(history=history)
        self.generator = AnswerGenerator()

    def analyze(self, item: dict) -> dict:
        """Classify an item and generate a draft answer when it has a known category."""
        classification = self.classifier.classify(item)
        if classification["category"] == "other":
            answer, confidence = "", 0.0
        else:
            answer, confidence = self.generator.generate(item, classification)

        return {
            "category": classification["category"],
            "route": classification["route"],
            "risk": classification["risk"],
            "vip": classification.get("vip", False),
            "abuse_score": classification.get("abuse_score", 0),
            "answer": answer,
            "confidence": confidence,
            "abuse_signals": classification.get("abuse_signals", []),
        }

    def suggest(self, question: str, items: list[dict], limit: int = 3) -> list[dict]:
        """Rank previously answered items by title and body similarity."""
        if limit <= 0:
            return []
        normalized_q = self._normalize_text(question)
        if not normalized_q:
            return []

        scored = []
        for item in items:
            if not item.get("answer"):
                continue
            normalized_title = self._normalize_text(item.get("title", ""))
            normalized_body = self._normalize_text((item.get("body") or "")[:200])
            title_sim = SequenceMatcher(None, normalized_q, normalized_title).ratio()
            body_sim = SequenceMatcher(None, normalized_q, normalized_body).ratio()
            score = title_sim * 0.7 + body_sim * 0.3
            if score > 0.3:
                scored.append({
                    "item_id": item.get("id"),
                    "title": item.get("title"),
                    "answer": item["answer"],
                    "confidence": item.get("confidence", 0),
                    "score": score,
                })
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Ignore case, whitespace and punctuation when matching text."""
        return re.sub(r"[^\w]", "", value.lower(), flags=re.UNICODE).replace("_", "")
