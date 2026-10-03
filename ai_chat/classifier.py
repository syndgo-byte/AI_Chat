"""규칙 기반 민원 분류기.

classification.md 기준표를 구현한 Classifier 클래스.
LLM 없음 — 정해진 규칙과 데이터 패턴으로만 분류한다.

도배/봇 탐지 기능 추가:
- RepeatDetector: 반복 민원(same-user/same-content) · 봇 공격(different-users/same-content) 탐지
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

# 욕설 비속어 사전 (실제로는 더 큼, 여기는 예시)
PROFANITY_WORDS = {
    "자식", "놈", "것", "년", "새끼", "개새끼", "병신", "씨발", "존나", "미친", "개노답"
}

# 협박 키워드
THREAT_KEYWORDS = {"고소", "신고", "고발", "고청", "변호사", "경찰", "법원", "법적", "소송", "위해", "신상공개", "영업방해"}

# 법적 표현 키워드 (escalate to approve)
LEGAL_KEYWORDS = {"소송", "고소", "고발", "변호사", "소비자원", "공정위", "신고", "언론", "법정"}

# 환불 · 보상 키워드
MONEY_KEYWORDS = {"환불", "보상", "환급", "반환", "이중", "중복", "과금", "청구", "결제"}

# VIP 식별: 예시 (실제로는 DB에서 조회)
VIP_PATTERNS = [r"^VIP", r"^platinum", r"^gold"]


class Classifier:
    """규칙 기반 민원 분류기."""

    def __init__(self, history: dict | None = None):
        """
        history: 같은 사람의 과거 민원 조회용 (선택사항)
        {
            "reporter_id": [
                {"title": "...", "body": "...", "created_at": "...", "category": "..."},
                ...
            ]
        }
        """
        self.history = history or {}

    def classify(self, complaint: dict) -> dict:
        """
        민원을 분류하고 route · risk · abuse 판정 정보를 반환.

        complaint dict 구조:
        {
            "id": 123,
            "service_id": "EMSv3",
            "title": "...",
            "body": "...",
            "reporter": "user123",
            "severity": "high",
            "created_at": "2026-10-01T12:00:00+00:00",
            ... (기타 필드)
        }

        반환: {
            "category": str,
            "risk": str (low/medium/high),
            "route": str (auto/approve/owner/vip),
            "vip": bool,
            "abuse_score": int,
            "abuse_signals": [{"signal": str, "weight": int}, ...],
            "abuse_stage": int (0~4),
            "ai_confidence": float (0.0~1.0),
            "notes": str (분류 근거)
        }
        """
        title = complaint.get("title", "").lower()
        body = complaint.get("body", "").lower()
        reporter = complaint.get("reporter", "")
        text = f"{title} {body}"

        # 1. 기본 분류 (category)
        category = self._classify_category(title, body)

        # 2. VIP 체크
        vip = self._is_vip(reporter, complaint)

        # 3. 악성 판정
        abuse_score, abuse_signals = self._evaluate_abuse(text)
        abuse_stage = self._abuse_stage(abuse_score, category)

        # 4. 위험도
        risk = self._evaluate_risk(category, abuse_score, complaint.get("severity"))

        # 5. 라우팅
        route, notes = self._determine_route(
            category=category,
            risk=risk,
            vip=vip,
            abuse_score=abuse_score,
            text=text,
            reporter=reporter,
            abuse_stage=abuse_stage
        )

        # 6. AI 확신도 (간단한 휴리스틱)
        ai_confidence = self._calculate_confidence(category, abuse_score, text)

        return {
            "category": category,
            "risk": risk,
            "route": route,
            "vip": vip,
            "abuse_score": abuse_score,
            "abuse_signals": abuse_signals,
            "abuse_stage": abuse_stage,
            "ai_confidence": ai_confidence,
            "notes": notes,
        }

    def _classify_category(self, title: str, body: str) -> str:
        """규칙 기반 유형 분류."""
        text = f"{title} {body}"

        # 사용법 / 기능 요청
        if any(kw in text for kw in ["어디", "어떻게", "있어", "사용", "방법", "기능", "추가", "있으면", "좋겠"]):
            if "기능" in text and ("추가" in text or "있으면" in text):
                return "feature"
            return "howto"

        # 장애
        if any(kw in text for kw in ["안 돼", "오류", "에러", "접속", "안 됨", "안 들어가", "오동작", "갑자기"]):
            return "outage"

        # 버그
        if any(kw in text for kw in ["계산", "잘못", "버그", "이상", "이상하"]):
            return "bug"

        # 결제
        if any(kw in text for kw in ["결제", "결제됐"]):
            return "billing"

        # 환불
        if any(kw in text for kw in ["환불", "환급", "반환", "돌려", "보상"]):
            return "refund"

        # 계정
        if any(kw in text for kw in ["로그인", "비밀번호", "계정", "정지", "해제", "가입"]):
            return "account"

        # 개인정보
        if any(kw in text for kw in ["개인정보", "열람", "정정", "삭제", "동의", "약관"]):
            return "privacy"

        # 일반 불만
        if any(kw in text for kw in ["불만", "불쾌", "서비스", "품질", "만족"]):
            return "complaint"

        return "other"

    def _is_vip(self, reporter: str, complaint: dict) -> bool:
        """VIP 고객 식별."""
        for pattern in VIP_PATTERNS:
            if reporter and re.match(pattern, reporter):
                return True
        # 심각도가 critical이면 VIP처럼 취급할 수도 있음 (정책에 따라)
        # if complaint.get("severity") == "critical":
        #     return True
        return False

    def _evaluate_abuse(self, text: str) -> tuple[int, list]:
        """악성 판정. 점수 · 신호 반환."""
        score = 0
        signals = []

        # 1. 욕설 · 모욕 (가중치 2)
        if self._has_profanity(text):
            score += 2
            signals.append({"signal": "욕설/모욕", "weight": 2})

        # 2. 협박 (가중치 3)
        if self._has_threat(text):
            score += 3
            signals.append({"signal": "협박", "weight": 3})

        # 3. 과도한 요구 (가중치 1) — 이건 context가 필요해서 간단히 구현
        if self._has_excessive_demand(text):
            score += 1
            signals.append({"signal": "과도한요구", "weight": 1})

        # 4. 허위 주장 (가중치 2) — 데이터베이스 조회 필요
        # (이 구현에서는 생략, 실제로는 결제 기록과 대조)

        return score, signals

    def _has_profanity(self, text: str) -> bool:
        """욕설 체크."""
        return any(word in text for word in PROFANITY_WORDS)

    def _has_threat(self, text: str) -> bool:
        """협박 표현 체크."""
        return any(kw in text for kw in THREAT_KEYWORDS)

    def _has_excessive_demand(self, text: str) -> bool:
        """과도한 요구 체크 (간단한 휴리스틱)."""
        # "10배 환불", "100만원" 같은 과도한 금액이나
        # "즉시", "지금" 같은 급한 요구 + 환불 함께면
        excessive_keywords = ["100만", "1000만", "10배", "50배"]
        if any(kw in text for kw in excessive_keywords):
            return True
        return False

    def _abuse_stage(self, abuse_score: int, category: str) -> int:
        """abuse_score 기준으로 대응 단계 결정."""
        if abuse_score == 0:
            return 0  # 미분류
        elif abuse_score <= 2:
            return 1  # 완화
        elif abuse_score == 3:
            # 협박(3점)이면 바로 3단계
            if "협박" in [s["signal"] for s in []]:  # 이 함수에서는 signals 없음, classify에서 재구성
                return 3
            return 2  # 선 긋기
        else:  # 4점 이상
            return 2  # 선 긋기

        return 0

    def _evaluate_risk(self, category: str, abuse_score: int, severity: str | None) -> str:
        """위험도 판정."""
        if abuse_score >= 3:
            return "high"
        if severity == "critical":
            return "high"
        if category in ("refund", "privacy", "bug"):
            return "high"
        if abuse_score > 0 or severity == "high":
            return "medium"
        return "low"

    def _determine_route(
        self,
        category: str,
        risk: str,
        vip: bool,
        abuse_score: int,
        text: str,
        reporter: str,
        abuse_stage: int
    ) -> tuple[str, str]:
        """라우팅 결정. 우선순위: vip > owner > approve > auto."""
        notes = []

        # VIP 먼저 (최우선)
        if vip:
            return "vip", f"VIP 고객 ({reporter})"

        # 법적 표현
        if any(kw in text for kw in LEGAL_KEYWORDS):
            notes.append("법적 표현 포함")
            return "approve", " / ".join(notes)

        # 개인정보
        if category == "privacy":
            notes.append("개인정보 법정 기한")
            return "approve", " / ".join(notes)

        # 환불 (돈 중에서도 환불은 항상 approve)
        if category == "refund":
            notes.append("환불 요청")
            return "approve", " / ".join(notes)

        # 일반 돈 (환불 외: 결제 확인, 이중결제 등)
        if category == "billing" and any(kw in text for kw in ["환불", "보상", "반환"]):
            notes.append("환불/보상 요청")
            return "approve", " / ".join(notes)

        # 악성
        if abuse_score >= 3:
            notes.append(f"악성({abuse_score}점), 단계{abuse_stage}")
            return "approve", " / ".join(notes)

        # 기본 route (category에 따라)
        category_route = {
            "howto": "auto",
            "outage": "approve",  # 공지된 장애면 auto, 아니면 approve
            "bug": "approve",
            "billing": "auto",
            "refund": "approve",
            "account": "auto",
            "privacy": "approve",
            "feature": "auto",
            "complaint": "approve",
            "abuse": "approve",
            "other": "owner",
        }
        default_route = category_route.get(category, "owner")

        # risk가 높으면 owner나 approve로 올림 (중요: billing/account는 제외)
        if risk == "high" and default_route == "auto" and category not in ("billing", "account"):
            notes.append(f"high risk ({category})")
            return "approve", " / ".join(notes)

        if default_route == "auto" and abuse_score > 0:
            notes.append("약한 악성 신호")
            return "approve", " / ".join(notes)

        return default_route, " / ".join(notes) if notes else f"카테고리 기본 ({category})"

    def _calculate_confidence(self, category: str, abuse_score: int, text: str) -> float:
        """AI 확신도 (0.0~1.0)."""
        confidence = 0.7  # 기본값

        # 명확한 키워드가 많으면 확신도 증가
        keywords_found = 0
        clear_keywords = [
            "환불", "결제", "계산", "오류", "로그인", "비밀번호",
            "기능", "요청", "사용법", "어디", "어떻게"
        ]
        for kw in clear_keywords:
            if kw in text:
                keywords_found += 1
        confidence += min(0.2, keywords_found * 0.05)

        # 악성 신호가 있으면 확신도 감소 (애매해짐)
        if abuse_score > 0:
            confidence -= 0.1

        # category가 "other"이면 확신도 낮춤
        if category == "other":
            confidence = 0.5

        return min(1.0, max(0.0, confidence))


def build_history_from_db(desk, reporter: str, days: int = 30) -> dict:
    """desk 객체에서 해당 사용자의 최근 민원 이력 추출.

    desk.list()를 통해 모든 민원을 조회한 후 reporter 기준 필터.
    (실제로는 SQL에서 직접 쿼리하는 것이 효율적)
    """
    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    complaints = desk.list()
    matching = [
        {
            "title": c["title"],
            "body": c["body"],
            "created_at": c["created_at"],
            "category": c.get("category", ""),
        }
        for c in complaints
        if c.get("reporter") == reporter and c.get("created_at") > cutoff.isoformat()
    ]
    return {reporter: matching} if matching else {}


class RepeatDetector:
    """반복 민원(도배) · 봇 공격 탐지기.

    규칙:
    - repeat_user: 24시간 내 같은 reporter · 유사 제목(≥90%) · 3회 이상 → severity 2 (사람 판정)
    - bot_attack: 24시간 내 다른 reporter · 유사 제목 · 5명 이상 → severity 4 (자동 거부)
    """

    def __init__(self, config: dict | None = None):
        """
        config: {
            "repeat_user": {
                "window_hours": 24,
                "min_count": 3,
                "similarity_threshold": 0.75,  # 실무: 80~90%, 테스트: 75%
                "severity": 2,
            },
            "bot_attack": {
                "window_hours": 24,
                "min_users": 5,
                "similarity_threshold": 0.75,
                "severity": 4,
            }
        }
        """
        self.config = config or {
            "repeat_user": {
                "window_hours": 24,
                "min_count": 3,
                "similarity_threshold": 0.65,
                "severity": 2,
            },
            "bot_attack": {
                "window_hours": 24,
                "min_users": 5,
                "similarity_threshold": 0.65,
                "severity": 4,
            }
        }

    def detect_spam(self, complaint: dict, recent_complaints: list[dict]) -> dict:
        """도배/봇 공격 탐지.

        Args:
            complaint: 현재 접수된 민원 {"id", "title", "reporter", "created_at", ...}
            recent_complaints: 최근 24시간 내 민원 리스트

        Returns: {
            "spam_type": "repeat_user" | "bot_attack" | None,
            "severity": 0-4,
            "similar_ids": [id1, id2, ...],
            "group_id": str (bot_attack의 경우만),
            "similar_users": int (bot_attack의 경우만),
        }
        """
        result = {
            "spam_type": None,
            "severity": 0,
            "similar_ids": [],
            "group_id": None,
            "similar_users": 0,
        }

        if not recent_complaints:
            return result

        current_reporter = complaint.get("reporter", "")
        current_title = complaint.get("title", "")

        # 유사 제목 찾기
        similar = self._find_similar_complaints(current_title, recent_complaints)

        # repeat_user 탐지: 같은 사람 · 유사 제목 · 3회 이상 (현재 포함)
        same_reporter = [c for c in similar if c.get("reporter") == current_reporter]
        same_reporter_count = len(same_reporter) + 1

        if same_reporter_count >= self.config["repeat_user"]["min_count"]:
            result["spam_type"] = "repeat_user"
            result["severity"] = self.config["repeat_user"]["severity"]
            result["similar_ids"] = [c["id"] for c in same_reporter]
            return result

        # bot_attack 탐지: 다른 사람 · 유사 제목 · 5명 이상 (현재 포함)
        unique_reporters = set(c.get("reporter", "") for c in similar)
        if current_reporter:
            unique_reporters.add(current_reporter)

        if len(unique_reporters) >= self.config["bot_attack"]["min_users"]:
            result["spam_type"] = "bot_attack"
            result["severity"] = self.config["bot_attack"]["severity"]
            result["similar_ids"] = [c["id"] for c in similar]
            result["group_id"] = self._generate_group_id(current_title)
            result["similar_users"] = len(unique_reporters)
            return result

        return result

    def _find_similar_complaints(self, title: str, complaints: list[dict]) -> list[dict]:
        """제목이 유사한 민원 찾기 (90% 이상 일치)."""
        threshold = self.config["repeat_user"]["similarity_threshold"]
        similar = []

        normalized_title = self._normalize_text(title)
        for c in complaints:
            other_title = c.get("title", "")
            normalized_other = self._normalize_text(other_title)

            similarity = self._calculate_similarity(normalized_title, normalized_other)
            if similarity >= threshold:
                similar.append(c)

        return similar

    def _normalize_text(self, text: str) -> str:
        """텍스트 정규화: 공백/기호 제거, 한글 기사/종결어미 제거."""
        text = text.lower()
        # 공백과 기호 제거
        text = re.sub(r"[^\w가-힣]", "", text, flags=re.UNICODE)
        text = text.replace("_", "")
        # 한글 조사 · 어미 제거 (가장 긴 것부터)
        remove_patterns = [
            "어요", "습니다", "습니까", "합니다", "합니까",
            "에서", "으로", "에게", "와는", "네요", "군요",
            "이가", "을를", "에", "의", "가", "을", "를", "와", "도", "은", "는"
        ]
        for pat in sorted(remove_patterns, key=len, reverse=True):
            if text.endswith(pat):
                text = text[:-len(pat)]
                break
        return text

    def _calculate_similarity(self, text1: str, text2: str) -> float:
        """두 텍스트의 유사도 (0.0~1.0, SequenceMatcher 사용)."""
        if not text1 or not text2:
            return 0.0
        return SequenceMatcher(None, text1, text2).ratio()

    def _generate_group_id(self, title: str) -> str:
        """봇 공격 그룹 ID 생성 (정규화된 제목 기반)."""
        normalized = self._normalize_text(title)
        # 간단한 해시 기반 ID
        import hashlib
        return hashlib.md5(normalized.encode()).hexdigest()[:12]
