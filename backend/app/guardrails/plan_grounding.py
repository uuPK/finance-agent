"""Deterministic evidence checks for business-critical QueryPlan decisions."""

from __future__ import annotations

import re
from typing import Any

from app.agents.query_plan_actor import RuleBasedQueryPlanActor
from app.schemas.query_plan import ClarificationQuestion, QueryFilter, QueryPlan, QueryValue
from app.schemas.v2_protocol import EvidenceRef

_AMBIGUOUS_TERMS = (
    "高净值",
    "缩水严重",
    "活跃客户",
    "沉默客户",
    "流失客户",
    "重点客户",
    "潜力客户",
)
_RELATIVE_TIME = ("最近", "近期", "近段时间")
_NUMBER = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*(?:亿|万|千)?")
_COMPARISON = re.compile(
    r"(?:大于等于|小于等于|不少于|不低于|不超过|不高于|至少|至多|"
    r"超过|高于|大于|低于|少于|小于|>=|<=|>|<|以上|以下)"
)
_OPERATORS = {
    "大于等于": ">=",
    "不少于": ">=",
    "不低于": ">=",
    "至少": ">=",
    "以上": ">=",
    ">=": ">=",
    "超过": ">",
    "高于": ">",
    "大于": ">",
    ">": ">",
    "小于等于": "<=",
    "不超过": "<=",
    "不高于": "<=",
    "至多": "<=",
    "以下": "<=",
    "<=": "<=",
    "低于": "<",
    "少于": "<",
    "小于": "<",
    "<": "<",
}


def _rows(context: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = context.get(key)
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _amounts(text: str) -> set[float]:
    amounts: set[float] = set()
    for match in _NUMBER.finditer(text):
        token = match.group().replace(" ", "")
        suffix = token[-1] if token[-1] in "亿万千" else ""
        number = token[:-1] if suffix else token
        amounts.add(float(number) * {"亿": 1e8, "万": 1e4, "千": 1e3, "": 1}[suffix])
    return amounts


def _user_value(question: str, value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return float(value) in _amounts(question)
    rendered = str(value).strip()
    return bool(rendered and (rendered in question or _amounts(rendered) & _amounts(question)))


def _explicit_threshold(
    question: str, value: object, operator: str, term: str | None = None
) -> bool:
    expected = {float(value)} if isinstance(value, (int, float)) else _amounts(str(value))
    if not expected:
        return False
    if operator == "between":
        return (
            len(expected) == 2
            and expected.issubset(_amounts(question))
            and bool(
                re.search(
                    r"(?:介于|在)?[^，。；]*?\d+[^，。；]*?(?:到|至|~|-)[^，。；]*?\d+", question
                )
            )
        )
    matches = list(_NUMBER.finditer(question))
    repeated_value = sum(bool(_amounts(match.group()) & expected) for match in matches) > 1
    previous_end = 0
    for match in matches:
        before = question[max(previous_end, match.start() - 16) : match.start()]
        after = question[match.end() : min(len(question), match.end() + 4)]
        previous_end = match.end()
        if not (_amounts(match.group()) & expected):
            continue
        if repeated_value and term and term not in before:
            continue
        prior = list(_COMPARISON.finditer(before))
        marker = prior[-1].group() if prior else None
        if marker is None:
            following = _COMPARISON.match(after)
            marker = following.group() if following else None
        if marker and _OPERATORS.get(marker) == operator:
            return True
    return False


def _term_for(text: str, terms: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches: list[tuple[int, dict[str, Any]]] = []
    for row in terms:
        synonyms = row.get("synonyms")
        names = [row.get("term"), *(synonyms if isinstance(synonyms, list) else [])]
        for name in names:
            if isinstance(name, str) and name and name in text:
                matches.append((len(name) + (1000 if name == text else 0), row))
    return max(matches, key=lambda item: item[0])[1] if matches else None


def _metadata_value(row: dict[str, Any] | None, item: QueryFilter, value: object) -> bool:
    if not row or value is None:
        return False
    if item.operator in {">", ">=", "<", "<=", "between"}:
        fragment = row.get("default_plan_fragment")
        if isinstance(fragment, dict):
            definitions = fragment.get("filters")
            if not isinstance(definitions, list):
                definitions = [fragment]
            if any(
                isinstance(definition, dict)
                and definition.get("operator") == item.operator
                and _amounts(str(definition.get("value"))) == _amounts(str(value))
                and (
                    not definition.get("metric_code")
                    or definition["metric_code"] == item.metric_code
                )
                and (
                    not definition.get("field_code") or definition["field_code"] == item.field_code
                )
                for definition in definitions
            ):
                return True
        return _explicit_threshold(str(row.get("definition") or ""), value, item.operator)
    evidence = f"{row.get('definition') or ''} {row.get('default_plan_fragment') or ''}"
    return _user_value(evidence, value)


def ground_query_plan(plan: QueryPlan, question: str, context: dict[str, Any]) -> QueryPlan:
    """Recompute provenance from the original question and retrieved metadata.

    A model's self-reported provenance is never trusted. Unsupported business
    thresholds become clarification requests before SQL generation.
    """
    if plan.plan_status == "invalid":
        return plan
    terms = _rows(context, "business_terms")
    metrics_catalog = {
        str(row.get("metric_code")): row
        for row in _rows(context, "metrics")
        if row.get("metric_code")
    }
    clarifications = list(plan.clarifications)
    known_fields = {item.field for item in clarifications}
    candidate_tables = set(plan.data_requirements.candidate_tables)

    def clarify(field: str, reason: str) -> None:
        if not any(field in known or known in field for known in known_fields):
            clarifications.append(
                ClarificationQuestion(
                    field=field,
                    question=f"请明确“{field}”的业务口径或具体范围。",
                    reason=reason,
                )
            )
            known_fields.add(field)

    grounded_metrics = []
    for metric in plan.metrics:
        term = _term_for(metric.name, terms)
        code = metric.metric_code
        fragment = term.get("default_plan_fragment") if term else None
        if not code and isinstance(fragment, dict):
            candidate = fragment.get("metric_code")
            if candidate in metrics_catalog:
                code = candidate
        row = metrics_catalog.get(code or "")
        if row:
            evidence = EvidenceRef(
                source_type="metadata_definition",
                source_id=f"metric:{code}",
                source_text=str(row.get("metric_name") or row.get("description") or code),
            )
        elif metric.name in question:
            evidence = EvidenceRef(source_type="user_explicit", source_text=metric.name)
        else:
            evidence = EvidenceRef(source_type="llm_inferred", source_text=metric.name)
        grounded_metrics.append(
            metric.model_copy(
                update={
                    "metric_code": code,
                    "provenance": [evidence],
                }
            )
        )

    grounded_filters = []
    for item in plan.filters:
        term = _term_for(item.term, terms)
        value = item.value.normalized if item.value.normalized is not None else item.value.raw
        critical = item.operator in {">", ">=", "<", "<=", "between"}
        explicit = (
            _explicit_threshold(question, value, item.operator, item.term)
            or _explicit_threshold(question, item.value.raw, item.operator, item.term)
            if critical
            else _user_value(question, value) or _user_value(question, item.value.raw)
        )
        metadata_defined = _metadata_value(term, item, value) or _metadata_value(
            term, item, item.value.raw
        )
        if explicit:
            evidence = EvidenceRef(source_type="user_explicit", source_text=str(item.value.raw))
        elif metadata_defined:
            evidence = EvidenceRef(
                source_type="metadata_definition",
                source_id=f"term:{term['term']}",
                source_text=str(term.get("definition") or term.get("default_plan_fragment")),
            )
        else:
            evidence = EvidenceRef(source_type="llm_inferred", source_text=str(item.value.raw))
        ambiguous = any(token in question for token in _AMBIGUOUS_TERMS)
        unresolved = (critical or ambiguous) and not (explicit or metadata_defined)
        if unresolved:
            clarify(item.term, "筛选值既非用户明示，也无已召回元数据定义；不能猜测阈值。")
            continue
        grounded_filters.append(
            item.model_copy(
                update={
                    "provenance": [evidence],
                    "requires_clarification": item.requires_clarification or unresolved,
                    "is_resolved": item.is_resolved and not unresolved,
                }
            )
        )

    metadata_terms = []
    for row in terms:
        fragment = row.get("default_plan_fragment")
        has_filter_default = isinstance(fragment, dict) and (
            ("operator" in fragment and "value" in fragment)
            or (isinstance(fragment.get("filters"), list) and bool(fragment["filters"]))
        )
        if not row.get("clarification_required") and not has_filter_default:
            continue
        synonyms = row.get("synonyms")
        names = [row.get("term"), *(synonyms if isinstance(synonyms, list) else [])]
        metadata_terms.extend(
            name for name in names if isinstance(name, str) and name and name in question
        )
    for token in dict.fromkeys([*_AMBIGUOUS_TERMS, *metadata_terms]):
        if token not in question:
            continue
        row = _term_for(token, terms)
        fragment = row.get("default_plan_fragment") if row else None
        if isinstance(fragment, dict) and not row.get("clarification_required"):
            definitions = fragment.get("filters")
            if not isinstance(definitions, list):
                definitions = [fragment] if "operator" in fragment and "value" in fragment else []
            for definition in definitions:
                if not isinstance(definition, dict):
                    continue
                if not (definition.get("metric_code") or definition.get("field_code")):
                    continue
                if not definition.get("operator") or "value" not in definition:
                    continue
                if (
                    definition.get("metric_code")
                    and definition["metric_code"] not in metrics_catalog
                ):
                    continue
                try:
                    value = definition["value"]
                    built = QueryFilter(
                        term=token,
                        operator=definition["operator"],
                        value=QueryValue(
                            raw=value,
                            normalized=value,
                            value_type="number" if isinstance(value, (int, float)) else "string",
                        ),
                        metric_code=definition.get("metric_code"),
                        field_code=definition.get("field_code"),
                        source="business_term",
                        is_resolved=True,
                        provenance=[
                            EvidenceRef(
                                source_type="metadata_definition",
                                source_id=f"term:{row['term']}",
                                source_text=str(fragment),
                            )
                        ],
                    )
                except (TypeError, ValueError):
                    continue
                grounded_filters = [
                    item
                    for item in grounded_filters
                    if not (
                        item.metric_code == built.metric_code
                        and item.field_code == built.field_code
                        and item.provenance
                        and item.provenance[0].source_type == "llm_inferred"
                    )
                ]
                if not any(
                    item.term == built.term
                    and item.operator == built.operator
                    and item.value.normalized == built.value.normalized
                    for item in grounded_filters
                ):
                    grounded_filters.append(built)
                    metric_row = metrics_catalog.get(built.metric_code or "")
                    source_tables = metric_row.get("source_tables") if metric_row else None
                    if isinstance(source_tables, list):
                        candidate_tables.update(
                            table for table in source_tables if isinstance(table, str)
                        )
        has_default = (
            any(
                item.provenance
                and item.provenance[0].source_type == "metadata_definition"
                and item.provenance[0].source_id == f"term:{row['term']}"
                for item in grounded_filters
            )
            if row
            else False
        )
        has_explicit_filter = any(
            item.provenance
            and item.provenance[0].source_type == "user_explicit"
            and (token in item.term or (token == "高净值" and "asset" in (item.metric_code or "")))
            for item in grounded_filters
        )
        if has_explicit_filter or (has_default and row and not row.get("clarification_required")):
            clarifications = [item for item in clarifications if token not in item.field]
            known_fields = {item.field for item in clarifications}
        if not has_explicit_filter and (
            not row or row.get("clarification_required") or not has_default
        ):
            clarify(token, "该业务词缺少可执行的元数据默认口径，且用户未明确给出。")

    time_range = plan.time_range
    if time_range is not None:
        time_text = time_range.label or time_range.relative or ""
        parsed_user_time = RuleBasedQueryPlanActor()._detect_time_range(question)
        explicit_time = (
            bool(time_text and time_text in question)
            or bool(time_range.start and _user_value(question, time_range.start))
            or bool(
                parsed_user_time
                and time_range.start == parsed_user_time.start
                and time_range.end == parsed_user_time.end
            )
        )
        reference_date = (context.get("semantic_contract") or {}).get("reference_date")
        metadata_time = bool(reference_date and time_range.anchor_date == reference_date)
        if explicit_time:
            evidence = EvidenceRef(
                source_type="user_explicit", source_text=time_text or str(time_range.start)
            )
        elif metadata_time:
            evidence = EvidenceRef(
                source_type="metadata_definition",
                source_id="semantic_contract:reference_date",
                source_text=str(reference_date),
            )
        else:
            evidence = EvidenceRef(
                source_type="llm_inferred", source_text=time_text or str(time_range.start)
            )
        if not time_range.is_resolved:
            clarify("time_range", "时间范围尚未解析为可执行的起止日期。")
        elif time_range.is_resolved and evidence.source_type == "llm_inferred":
            clarify("time_range", "计划中的时间范围既非用户明示，也无元数据默认日期依据。")
        time_range = time_range.model_copy(update={"provenance": [evidence]})
    elif any(token in question for token in _RELATIVE_TIME):
        clarify("time_range", "“最近/近期”没有明确的时间范围。")

    return plan.model_copy(
        update={
            "metrics": grounded_metrics,
            "filters": grounded_filters,
            "time_range": time_range,
            "data_requirements": plan.data_requirements.model_copy(
                update={"candidate_tables": sorted(candidate_tables)}
            ),
            "clarifications": clarifications,
            "plan_status": (
                "needs_clarification"
                if clarifications
                else "ready"
                if plan.plan_status == "needs_clarification"
                else plan.plan_status
            ),
        }
    )
