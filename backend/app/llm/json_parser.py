import json
from typing import Any


class LLMJSONParseError(ValueError):
    pass


def extract_json_object(content: str) -> dict[str, Any]:
    """Extract the first JSON object from an LLM response."""

    cleaned = _strip_markdown_fence(content.strip())
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        parsed = _decode_first_object(cleaned)

    if not isinstance(parsed, dict):
        raise LLMJSONParseError("LLM response JSON must be an object.")
    return parsed


def _strip_markdown_fence(content: str) -> str:
    if not content.startswith("```"):
        return content

    lines = content.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _decode_first_object(content: str) -> Any:
    decoder = json.JSONDecoder()
    for index, character in enumerate(content):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(content[index:])
        except json.JSONDecodeError:
            continue
        return parsed
    raise LLMJSONParseError("No JSON object found in LLM response.")
