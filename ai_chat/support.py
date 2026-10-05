"""Service-scoped approved knowledge, immutable evidence and audited supervision."""
import json
import re
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from difflib import SequenceMatcher
from datetime import datetime, timezone
from .chatbot import ChatError, text, redact

CATEGORIES = ('howto','outage','bug','billing','refund','account','privacy','feature','complaint','abuse','other')
SAFE_CATEGORIES = ('howto','feature','other')
RISK_TERMS = ('결제','환불','환급','보상','과금','개인정보','비밀번호','계정 정지','소송','고소')
ABUSE_TERMS = ('씨발','개새끼','병신','죽여','신상공개')
INJECTION_TERMS = ('이전 지시 무시','규칙 무시','정책 무시','시스템 프롬프트','악성 분류 해제','ignore previous','ignore all instructions','system prompt')

def now(): return datetime.now(timezone.utc).isoformat()
def normalized(value): return re.sub(r'[^가-힣a-z0-9]', '', value.lower())

class SupportStore:
    def __init__(self, path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS support_policies(service_id TEXT PRIMARY KEY, value TEXT NOT NULL, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS support_knowledge(id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, category TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', source TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS support_audit(id INTEGER PRIMARY KEY AUTOINCREMENT, service_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL, at TEXT NOT NULL);
            """)
    @contextmanager
    def conn(self):
        c=sqlite3.connect(self.path, timeout=10); c.row_factory=sqlite3.Row
        try:
            with c: yield c
        finally: c.close()
    def _audit(self,c,service_id,action,actor,detail):
        c.execute('INSERT INTO support_audit(service_id,action,actor,detail,at) VALUES(?,?,?,?,?)',(service_id,action,actor,json.dumps(detail,ensure_ascii=False),now()))
    def policy(self, service_id):
        with self.conn() as c:
            row=c.execute('SELECT * FROM support_policies WHERE service_id=?',(service_id,)).fetchone()
        if row: return {**json.loads(row['value']), 'revision':row['revision']}
        return {'auto_enabled':False,'auto_categories':['howto'],'match_threshold':0.9,'revision':0}
    def set_policy(self,service_id,value,expected_revision,actor):
        enabled=value.get('auto_enabled'); cats=value.get('auto_categories'); threshold=value.get('match_threshold')
        if type(enabled) is not bool or not isinstance(cats,list) or any(v not in SAFE_CATEGORIES for v in cats) or type(threshold) not in (int,float) or not 0.85<=threshold<=1:
            raise ChatError('자동 응답 설정을 확인하세요. 고위험 카테고리는 자동 응답할 수 없습니다.')
        with self.conn() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT revision FROM support_policies WHERE service_id=?',(service_id,)).fetchone()
            rev=row['revision'] if row else 0
            if rev != expected_revision: raise ChatError('설정이 변경됐습니다. 다시 불러오세요.',409)
            data={'auto_enabled':enabled,'auto_categories':sorted(set(cats)),'match_threshold':threshold}
            c.execute('INSERT OR REPLACE INTO support_policies VALUES(?,?,?)',(service_id,json.dumps(data),rev+1))
            self._audit(c,service_id,'policy_updated',actor,{'revision':rev+1,**data})
        return self.policy(service_id)
    def knowledge(self,service_id,approved_only=False):
        with self.conn() as c:
            rows=c.execute("SELECT * FROM support_knowledge WHERE service_id=?"+(" AND state='approved'" if approved_only else '')+' ORDER BY id DESC LIMIT 200',(service_id,)).fetchall()
        return [dict(r) for r in rows]
    def propose(self,service_id,question,answer,category,actor,source='manual'):
        question=redact(text(question,'학습 질문',2000)); answer=redact(text(answer,'승인할 답변',5000))
        if category not in CATEGORIES: raise ChatError('카테고리를 확인하세요.')
        with self.conn() as c:
            id=c.execute('INSERT INTO support_knowledge(service_id,question,answer,category,source) VALUES(?,?,?,?,?)',(service_id,question,answer,category,source)).lastrowid
            self._audit(c,service_id,'knowledge_proposed',actor,{'knowledge_id':id,'source':source})
        return next(v for v in self.knowledge(service_id) if v['id']==id)
    def review_knowledge(self,service_id,id,state,revision,actor):
        if state not in ('approved','rejected'): raise ChatError('승인 또는 거절을 선택하세요.')
        with self.conn() as c:
            row=c.execute('SELECT * FROM support_knowledge WHERE id=? AND service_id=?',(id,service_id)).fetchone()
            if not row: raise ChatError('답변 자료가 없습니다.',404)
            if row['revision']!=revision: raise ChatError('답변 자료가 변경됐습니다.',409)
            c.execute('UPDATE support_knowledge SET state=?,revision=revision+1 WHERE id=?',(state,id))
            self._audit(c,service_id,'knowledge_'+state,actor,{'knowledge_id':id,'revision':revision+1})
        return next(v for v in self.knowledge(service_id) if v['id']==id)
    def audit(self,service_id):
        with self.conn() as c:
            return [dict(r) for r in c.execute('SELECT * FROM support_audit WHERE service_id=? ORDER BY id DESC LIMIT 50',(service_id,))]
    def decide(self,service_id,history,previous=None,ai_category=None):
        latest=next((v['content'] for v in reversed(history) if v['role']=='user'),'')
        content=' '.join(v['content'] for v in history if v['role']=='user').lower()
        flags=set((previous or {}).get('locked_flags',[]))
        if any(v in content for v in ABUSE_TERMS): flags.add('abuse_suspected')
        if any(v in content for v in INJECTION_TERMS): flags.add('policy_change_attempt')
        if any(v in content for v in RISK_TERMS): flags.add('sensitive_action')
        category='other'
        for cat,terms in [('privacy',('개인정보','개인 정보')),('refund',('환불','보상','환급')),('billing',('결제','과금','청구')),('account',('로그인','계정','비밀번호')),('outage',('오류','에러','안 돼','안됨')),('bug',('버그','잘못 계산')),('feature',('기능 추가',)),('howto',('어떻게','방법','어디','사용법'))]:
            if any(t in latest for t in terms): category=cat; break
        if category=='other' and ai_category in CATEGORIES: category=ai_category
        policy=self.policy(service_id)
        candidates=[]
        for item in self.knowledge(service_id,True):
            score=SequenceMatcher(None,normalized(latest),normalized(item['question'])).ratio()
            if item['category'] in policy['auto_categories'] and len(normalized(latest))>=6 and score>=policy['match_threshold']:
                candidates.append((score,item))
        match=max(candidates,key=lambda p:p[0]) if candidates else None
        automatic=bool(policy['auto_enabled'] and not flags and category in SAFE_CATEGORIES and match)
        matched=match[1] if automatic else None
        return {'category':matched['category'] if matched else category, 'route':'auto' if automatic else 'review',
                'answerable':automatic,'locked_flags':sorted(flags),'knowledge_id':matched['id'] if matched else None,
                'knowledge_revision':matched['revision'] if matched else None, 'match_score':round(match[0],4) if match else 0,
                'policy_revision':policy['revision'],'reply':matched['answer'] if matched else None,
                'reason':'승인된 서비스 답변과 일치' if automatic else ('검토가 필요한 신호가 있어 자동 답변을 보류합니다.' if flags else '승인된 답변 근거가 부족하여 담당자 검토가 필요합니다.')}
