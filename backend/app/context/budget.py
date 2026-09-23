"""Model-independent estimated sizing for metadata prompt payloads."""

from __future__ import annotations

import json
from math import ceil
from typing import Any


def estimate_context_tokens(value: Any) -> int:
    """Estimate JSON tokens without claiming knowledge of a provider's tokenizer.

    CJK characters are charged one token each; ASCII is charged one per four
    characters.  The formatted JSON is counted because some actors pretty-print
    metadata.  This is a budget heuristic, not an API-reported token count.
    """
    serialized = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    ascii_count = sum(ord(char) < 128 for char in serialized)
    return ceil(ascii_count / 4) + len(serialized) - ascii_count


class ContextBudgetExceeded(ValueError):
    """Required grounded evidence cannot fit in the configured context budget."""
