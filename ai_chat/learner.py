"""도배/봇 탐지 자동 학습기.

매시간 분석:
1. repeat_user로 표시된 민원 중 주인장이 승인한 비율 (정확도)
2. bot_attack으로 필터된 민원 중 오탐율
3. 유사도 threshold 정확도 조정

설정: repeat-config.json (threshold, 쿨다운, 히트 임계값 등)
"""
from __future__ import annotations

import json
import logging
import math
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


class AutoSendLearner:
    """Persist complaint-level delivery outcomes and learn the specified rules.

    Three consecutive failures or seven negative ratings in ten new outcomes
    lower the threshold by 0.1, to a floor of 0.5 (the requested policy).
    Consumed evidence is not reused; retries update one complaint's rating.
    A saved inbox answer counts as sent; no external transport is implied.
    """

    _lock = threading.RLock()

    def __init__(self, config_path: str | Path = "auto_send_config.json"):
        self.config_path = Path(config_path)
        self.rules = self._defaults()
        self.load()

    @staticmethod
    def _defaults():
        return {"min_confidence": 0.8, "requires_route_auto": True,
                "consecutive_threshold": 3, "history": [], "last_update": None}

    @staticmethod
    def validate_feedback(feedback):
        if not isinstance(feedback, dict):
            raise ValueError("feedback must be an object")
        if "useful" in feedback and type(feedback["useful"]) is not bool:
            raise ValueError("useful must be a boolean")
        if "satisfaction" in feedback:
            value = feedback["satisfaction"]
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not 0 <= value <= 1):
                raise ValueError("satisfaction must be a number from 0 to 1")

    @contextmanager
    def _exclusive(self):
        # The hub and EMS can write the same config from separate processes.
        with self._lock:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(str(self.config_path) + ".lock", "a+b") as lock:
                lock.seek(0, os.SEEK_END)
                if lock.tell() == 0:
                    lock.write(b"0")
                    lock.flush()
                lock.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    lock.seek(0)
                    if os.name == "nt":
                        msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(lock, fcntl.LOCK_UN)

    def should_send(self, complaint: dict) -> bool:
        self.load()
        if self.rules["requires_route_auto"] and complaint.get("route") != "auto":
            return False
        confidence = complaint.get("ai_confidence", 0)
        return (type(confidence) in (int, float) and math.isfinite(confidence)
                and self.rules["min_confidence"] <= confidence <= 1)

    def record(self, complaint_id: int, sent: bool, user_feedback: dict | None = None):
        if type(complaint_id) is not int or complaint_id <= 0 or type(sent) is not bool:
            raise ValueError("a positive complaint_id and boolean sent are required")
        feedback = {} if user_feedback is None else dict(user_feedback)
        self.validate_feedback(feedback)
        with self._exclusive():
            self.load()
            history = self.rules["history"]
            entry = next((r for r in history if r["complaint_id"] == complaint_id), None)
            if entry is None:
                entry = {"complaint_id": complaint_id, "sent": sent,
                         "timestamp": datetime.now(timezone.utc).isoformat(), "feedback": {}}
                history.append(entry)
            entry["sent"] = sent
            if feedback:
                entry["feedback"] = feedback
            self.rules["history"] = history[-1000:]
            self._check_and_update()
            self._save()

    def _check_and_update(self):
        # Unrated successful sends are not satisfaction evidence.
        recent = [r for r in self.rules["history"] if not r.get("learned")
                  and ((r["sent"] and r["feedback"]) or (not r["sent"] and not r["feedback"]))][-10:]
        failures = [not r["sent"] or r["feedback"].get("useful") is False
                    or r["feedback"].get("satisfaction", 1) < 0.5 for r in recent]
        count = self.rules["consecutive_threshold"]
        consecutive = len(failures) >= count and all(failures[-count:])
        if consecutive or (len(failures) == 10 and sum(failures) >= 7):
            self.rules["min_confidence"] = max(0.5, round(self.rules["min_confidence"] - 0.1, 10))
            self.rules["last_update"] = datetime.now(timezone.utc).isoformat()
            for entry in recent:
                entry["learned"] = True

    def save(self):
        with self._exclusive():
            self._save()

    def _save(self):
        fd, name = tempfile.mkstemp(dir=self.config_path.parent, prefix="auto-send-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(self.rules, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.config_path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def load(self):
        if not self.config_path.exists():
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            rules = {**self._defaults(), **data}
            value = rules["min_confidence"]
            if type(value) not in (int, float) or not 0.5 <= value <= 1:
                raise ValueError("invalid min_confidence")
            if type(rules["requires_route_auto"]) is not bool:
                raise ValueError("invalid requires_route_auto")
            if type(rules["consecutive_threshold"]) is not int or not 1 <= rules["consecutive_threshold"] <= 10:
                raise ValueError("invalid consecutive_threshold")
            if not isinstance(rules["history"], list):
                raise ValueError("invalid history")
            for entry in rules["history"]:
                if type(entry["complaint_id"]) is not int or type(entry["sent"]) is not bool:
                    raise ValueError("invalid history entry")
                self.validate_feedback(entry["feedback"])
            rules["history"] = rules["history"][-1000:]
            self.rules = rules
        except (ValueError, TypeError, KeyError):
            logging.getLogger(__name__).warning("Invalid auto-send config %s; using defaults", self.config_path)
            self.rules = self._defaults()


def load_config(config_path: str | Path) -> dict:
    """설정 파일 로드."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_config(config: dict, config_path: str | Path) -> None:
    """설정 파일 저장."""
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


class RepeatLearner:
    """도배/봇 탐지 자동 학습기."""

    def __init__(self, desk, config_path: str | Path):
        """
        Args:
            desk: ComplaintDesk 인스턴스
            config_path: repeat-config.json 경로
        """
        self.desk = desk
        self.config_path = config_path
        self.config = load_config(config_path)

    def analyze_and_adjust(self) -> dict:
        """repeat_user · bot_attack 정확도 분석 및 threshold 조정.

        Returns: {
            "repeat_user": {"accuracy": 0.92, "hits": 25, "false_positives": 2, ...},
            "bot_attack": {"accuracy": 0.98, "hits": 15, "false_positives": 0, ...},
            "adjustments": {"repeat_user_threshold": 0.88, "bot_attack_threshold": 0.90}
        }
        """
        result = {
            "repeat_user": {},
            "bot_attack": {},
            "adjustments": {},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # repeat_user 분석
        repeat_stats = self._analyze_repeat_user()
        result["repeat_user"] = repeat_stats

        # bot_attack 분석
        bot_stats = self._analyze_bot_attack()
        result["bot_attack"] = bot_stats

        # threshold 조정 (선택적)
        if self.config["learning"]["enabled"]:
            adjustments = self._adjust_thresholds(repeat_stats, bot_stats)
            result["adjustments"] = adjustments
            # 설정 저장
            self._apply_adjustments(adjustments)
            save_config(self.config, self.config_path)

        return result

    def _analyze_repeat_user(self) -> dict:
        """repeat_user 정확도 분석.

        - hits: repeat_user로 표시된 건수
        - false_positives: 주인장이 "정상"으로 판정한 건수
        - accuracy: (hits - false_positives) / hits
        """
        # DB에서 지난 7일간 spam_type='repeat_user'인 민원 조회
        recent_complaints = self.desk.list()  # 모든 민원 (실제로는 SQL 쿼리가 효율적)
        repeat_complaints = [
            c for c in recent_complaints
            if c.get("spam_type") == "repeat_user"
            and self._is_within_days(c.get("created_at"), 7)
        ]

        hits = len(repeat_complaints)
        if hits == 0:
            return {
                "accuracy": 0.0,
                "hits": 0,
                "false_positives": 0,
                "status": "no_data"
            }

        # false_positives: resolution에 "[반복 민원 판정: 정상]"이 있는 건
        false_positives = sum(
            1 for c in repeat_complaints
            if "[반복 민원 판정: 정상]" in (c.get("resolution") or "")
        )

        accuracy = (hits - false_positives) / hits if hits > 0 else 0.0

        return {
            "accuracy": accuracy,
            "hits": hits,
            "false_positives": false_positives,
            "threshold": self.config["repeat_user"]["similarity_threshold"],
            "adjusted_threshold": self.config["repeat_user"].get("adjusted_threshold"),
        }

    def _analyze_bot_attack(self) -> dict:
        """bot_attack 정확도 분석.

        - hits: bot_attack으로 필터된 건수
        - false_positives: 부정적 피드백 (나중 조회 시 정상 판정됨)
        - accuracy: (hits - false_positives) / hits
        """
        recent_complaints = self.desk.list()
        bot_complaints = [
            c for c in recent_complaints
            if c.get("spam_type") == "bot_attack"
            and self._is_within_days(c.get("created_at"), 7)
        ]

        hits = len(bot_complaints)
        if hits == 0:
            return {
                "accuracy": 0.0,
                "hits": 0,
                "false_positives": 0,
                "status": "no_data"
            }

        # false_positives: 향후 수동 검증 필드 (현재 미구현)
        false_positives = 0

        accuracy = (hits - false_positives) / hits if hits > 0 else 0.0

        return {
            "accuracy": accuracy,
            "hits": hits,
            "false_positives": false_positives,
            "threshold": self.config["bot_attack"]["similarity_threshold"],
            "adjusted_threshold": self.config["bot_attack"].get("adjusted_threshold"),
        }

    def _adjust_thresholds(self, repeat_stats: dict, bot_stats: dict) -> dict:
        """정확도 기반 threshold 점진적 조정.

        정확도 < 70% → threshold 낮춤 (오탐 줄이기)
        정확도 > 90% → threshold 올림 (탈락 줄이기)
        """
        adjustments = {}
        learning_config = self.config["learning"]

        # repeat_user 조정
        if repeat_stats.get("hits", 0) >= self.config["repeat_user"]["min_hits_for_update"]:
            repeat_accuracy = repeat_stats.get("accuracy", 0.0)
            repeat_threshold = self.config["repeat_user"]["similarity_threshold"]

            if repeat_accuracy < learning_config["min_accuracy"]:
                # 오탐이 많으니 threshold 낮춤 (유사도 기준을 높임)
                new_threshold = min(
                    repeat_threshold + learning_config["threshold_adjustment_step"],
                    learning_config["max_threshold"]
                )
                adjustments["repeat_user_threshold"] = new_threshold
            elif repeat_accuracy > 0.9:
                # 정확도 높으니 threshold 올림 (유사도 기준을 낮춤)
                new_threshold = max(
                    repeat_threshold - learning_config["threshold_adjustment_step"],
                    learning_config["min_threshold"]
                )
                adjustments["repeat_user_threshold"] = new_threshold

        # bot_attack 조정 (비슷한 로직)
        if bot_stats.get("hits", 0) >= self.config["bot_attack"]["min_hits_for_update"]:
            bot_accuracy = bot_stats.get("accuracy", 0.0)
            bot_threshold = self.config["bot_attack"]["similarity_threshold"]

            if bot_accuracy < learning_config["min_accuracy"]:
                new_threshold = min(
                    bot_threshold + learning_config["threshold_adjustment_step"],
                    learning_config["max_threshold"]
                )
                adjustments["bot_attack_threshold"] = new_threshold
            elif bot_accuracy > 0.9:
                new_threshold = max(
                    bot_threshold - learning_config["threshold_adjustment_step"],
                    learning_config["min_threshold"]
                )
                adjustments["bot_attack_threshold"] = new_threshold

        return adjustments

    def _apply_adjustments(self, adjustments: dict) -> None:
        """설정에 조정 사항 적용."""
        for key, value in adjustments.items():
            if key == "repeat_user_threshold":
                self.config["repeat_user"]["adjusted_threshold"] = value
            elif key == "bot_attack_threshold":
                self.config["bot_attack"]["adjusted_threshold"] = value

    def _is_within_days(self, timestamp_str: str | None, days: int) -> bool:
        """timestamp가 최근 N일 이내인지 확인."""
        if not timestamp_str:
            return False
        try:
            ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            cutoff = datetime.now(timezone.utc) - timedelta(days=days)
            return ts >= cutoff
        except (ValueError, TypeError):
            return False
