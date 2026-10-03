"""규칙 분류 결과에 따른 한국어 답변 초안."""


class AnswerGenerator:
    """카테고리와 라우팅에 맞는 답변 초안을 생성한다."""

    def __init__(self):
        self.templates = {
            "payment": {
                "auto": "결제 관련 건으로 확인되었습니다. 담당 팀에서 빠르게 처리하겠습니다.",
                "owner": "결제 관련 문제입니다. 영수증 번호나 결제 시각을 알려주시면 확인하겠습니다.",
            },
            "login": {
                "auto": "로그인 오류로 문의해 주셨습니다. 현재 상황을 확인하고 1시간 내에 연락드리겠습니다.",
                "owner": "로그인 오류입니다. 최근 비밀번호 변경 여부, 계정 잠금 여부, 에러 메시지를 알려주시면 확인하겠습니다.",
            },
            "technical": {
                "auto": "기술 문제로 보고해 주셨습니다. 확인 후 연락드리겠습니다.",
                "owner": "기술 지원이 필요합니다. 에러 메시지, 사용 기기와 브라우저, 재현 단계를 알려주세요.",
            },
            "account": {
                "auto": "계정 관련 문의입니다. 안전 확인 후 처리하겠습니다.",
                "owner": "계정 관련 사항입니다. 정보 보호를 위해 추가 인증이 필요할 수 있습니다.",
            },
            "refund": {
                "auto": "환불 요청으로 접수되었습니다. 정책에 따라 검토 후 안내드리겠습니다.",
                "owner": "환불 신청입니다. 구매 날짜, 주문 번호, 환불 이유를 확인한 후 진행하겠습니다.",
            },
            "service_request": {
                "auto": "서비스 요청으로 접수되었습니다. 가능한 범위에서 검토하겠습니다.",
                "owner": "기능 요청이나 개선 사항을 보내주셨습니다. 제품 팀과 검토하겠습니다.",
            },
            "abuse": {
                "owner": "문의 내용을 담당자가 검토한 후 별도로 안내드리겠습니다.",
            },
            "other": {
                "auto": "문의 주셨습니다. 확인 후 안내드리겠습니다.",
                "owner": "문의 사항을 정확히 파악하기 위해 추가 정보가 필요합니다.",
            },
        }

    def generate(self, complaint: dict, classification: dict) -> tuple[str, float]:
        """초안과 신뢰도(0.0~1.0)를 반환한다."""
        category = classification.get("category", "other")
        route = classification.get("route", "owner")
        risk = classification.get("risk", "low")
        abuse_score = classification.get("abuse_score", 0)

        # 실제 Classifier 카테고리를 템플릿 키에 맞춘다.
        if category == "account" and "로그인" in f"{complaint.get('title', '')} {complaint.get('body', '')}":
            category = "login"
        else:
            category = {
                "billing": "payment", "outage": "technical", "bug": "technical",
                "feature": "service_request", "howto": "service_request",
            }.get(category, category)

        if route == "vip":
            return "VIP 고객님의 문의입니다. 담당자가 직접 확인하여 최우선으로 처리하겠습니다.", 0.80

        templates = self.templates.get(category, self.templates["other"])
        if route == "auto" and "auto" in templates:
            return templates["auto"], 0.85 if risk == "low" and abuse_score < 10 else 0.65
        if route in ("approve", "owner") and "owner" in templates:
            return templates["owner"], 0.70
        return self.templates["other"]["owner"], 0.50
