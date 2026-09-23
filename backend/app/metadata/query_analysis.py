"""Lightweight, retrieval-only interpretation of a user question."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.metadata.retriever import _ALIASES

_DOMAIN_TERMS: dict[str, tuple[str, ...]] = {
    "customer": ("客户", "人数", "年龄", "性别", "学历", "customer"),
    "asset": ("资产", "余额", "高净值", "asset", "aset"),
    "cash_flow": ("资金", "流入", "流出", "转账", "划拨", "现金", "cash"),
    "holding": ("持仓", "持有", "市值", "hold"),
    "trade": ("交易", "成交", "买入", "卖出", "trade", "tran"),
    "product": ("产品", "基金", "股票", "债券", "product", "prdt"),
    "branch": ("营业部", "分支", "机构", "branch", "org"),
    "dimension": ("代码", "枚举", "字典", "等级", "学历", "性别"),
}
_ENTITY_TERMS: dict[str, tuple[str, ...]] = {
    "customer": ("客户", "人数", "年龄", "高净值"),
    "product": ("产品", "基金", "股票", "债券"),
    "branch": ("营业部", "机构", "分支"),
}
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*|[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True, slots=True)
class QueryAnalysis:
    rewritten_query: str
    domains: tuple[str, ...]
    entities: tuple[str, ...]
    intent_hint: str
    keywords: tuple[str, ...]
    preferred_doc_types: tuple[str, ...]


def analyze_query(question: str) -> QueryAnalysis:
    normalized = " ".join(question.strip().split())
    lower = normalized.lower()
    domains = tuple(
        domain for domain, terms in _DOMAIN_TERMS.items() if any(term in lower for term in terms)
    )
    entities = tuple(
        entity for entity, terms in _ENTITY_TERMS.items() if any(term in lower for term in terms)
    )
    if any(term in lower for term in ("关联", "连接", "join")):
        intent_hint = "join_lookup"
    elif any(term in lower for term in ("平均", "总数", "多少", "合计", "统计", "数量")):
        intent_hint = "aggregation"
    elif any(term in lower for term in ("明细", "列表", "列出", "查询")):
        intent_hint = "detail_query"
    else:
        intent_hint = "unspecified"

    tokens = [match.group(0).lower() for match in _WORD_RE.finditer(normalized)]
    for alias, expansions in _ALIASES.items():
        if alias.lower() in lower:
            tokens.extend(value.lower() for value in expansions)
    keywords = tuple(dict.fromkeys(token for token in tokens if len(token) >= 2))[:40]
    types = ("table", "column", "metric", "business_term", "join", "example")
    if any(term in lower for term in ("规则", "限制", "敏感", "权限")):
        types += ("rule",)
    return QueryAnalysis(normalized, domains, entities, intent_hint, keywords, types)
