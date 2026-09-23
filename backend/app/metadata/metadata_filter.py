"""Soft candidate narrowing; callers retry without this expression if needed."""

from __future__ import annotations

import json

from app.metadata.query_analysis import QueryAnalysis


def candidate_filter(analysis: QueryAnalysis) -> str | None:
    clauses: list[str] = []
    if analysis.domains:
        domains = list(analysis.domains)
        # Global definitions and links must remain available even with a domain hint.
        clauses.append(
            f"(domain in {json.dumps(domains)} or "
            'doc_type in ["business_term", "join", "example", "rule"])'
        )
    elif analysis.entities:
        clauses.append(
            f"(entity in {json.dumps(list(analysis.entities))} or "
            'doc_type in ["business_term", "join", "example", "rule"])'
        )
    if "rule" not in analysis.preferred_doc_types:
        clauses.append('doc_type != "rule"')
    return " and ".join(clauses) or None
