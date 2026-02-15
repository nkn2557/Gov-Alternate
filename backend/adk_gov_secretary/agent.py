from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.adk.agents import LlmAgent
from google.genai import types as genai_types

from app.models.api import RecommendationCategory, UserProfile
from app.services.catalog import CatalogService
from app.services.municipality import MunicipalityService
from app.services.recommendation import RecommendationEngine

TARGETS_FILE = Path(__file__).resolve().parents[1] / "app" / "batch" / "targets.json"
ROOT_PAYLOAD_STATE_KEY = "app:last_root_payload"
INTAKE_PROFILE_STATE_KEY = "app:intake_inferred_profile"
INTAKE_SIGNAL_STATE_KEY = "app:intake_structured_signals"

_ALLOWED_NEXT_ACTIONS = {
    "ask_goal",
    "ask_more_profile",
    "present_list",
    "continue",
}
_TOOL_CACHE_PREFIX = "app:tool_cache:"
_TEMP_TOOL_CACHE_KEY = "temp:last_tool_cache_key"
_MAX_ASSISTANT_TEXT_CHARS = 1600
_LLM_STDOUT_MAX_CHARS = 4000
GUI_OPTIONAL_PROFILE_FIELDS: tuple[str, ...] = (
    "couple_count",
    "child_count",
    "parent_count",
    "pregnancy",
    "moving",
    "employment",
    "income_t0",
    "income_t1",
    "adult_count",
    "family_composition",
    "household_size",
    "children_counts",
    "children_ages",
    "children_age_ranges",
    "has_disability_child",
    "has_pet",
    "is_considering_children",
    "is_pregnant",
    "is_moving",
    "expected_birth_date",
    "moving_date",
    "income",
)
_LLM_MUNICIPALITY_CONFIDENCE_MIN = 0.65
_LLM_DOMAIN_CONFIDENCE_MIN = 0.6
_LLM_PROFILE_CONFIDENCE_MIN = 0.55
_LLM_DEFAULT_MUNICIPALITY_CONFIDENCE = 0.7
_LLM_DEFAULT_DOMAIN_CONFIDENCE = 0.7
_LLM_DEFAULT_PROFILE_CONFIDENCE = 0.6


def _env_text(name: str) -> str:
    return str(os.getenv(name, "") or "").strip()


def _resolve_model_name(default: str, *env_keys: str) -> str:
    for key in env_keys:
        value = _env_text(key)
        if value:
            return value
    return default


_DEFAULT_EASY_MODEL = "gemini-2.5-flash"
_DEFAULT_HARD_MODEL = "gemini-3-pro-preview"

MODEL_EASY = _resolve_model_name(
    _DEFAULT_EASY_MODEL,
    "ADK_MODEL_EASY",
    "ADK_MODEL",
)
MODEL_HARD = _resolve_model_name(
    _DEFAULT_HARD_MODEL,
    "ADK_MODEL_HARD",
    "ADK_MODEL_COMPLEX",
)

# Agent assignment policy:
# - difficult agents: Gemini 3.0
# - agents sufficiently handled by Gemini 2.5 Flash class: Gemini 2.5
MODEL_ROOT = _resolve_model_name(MODEL_HARD, "ADK_MODEL_ROOT")
MODEL_INTAKE = _resolve_model_name(MODEL_EASY, "ADK_MODEL_INTAKE")
MODEL_RETRIEVER = _resolve_model_name(
    MODEL_EASY,
    "ADK_MODEL_RETRIEVER",
)
MODEL_RANKER = _resolve_model_name(
    MODEL_HARD,
    "ADK_MODEL_RANKER",
)


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _build_generation_config() -> genai_types.GenerateContentConfig:
    return genai_types.GenerateContentConfig(
        temperature=_float_env("ADK_TEMPERATURE", 0.2),
        top_p=_float_env("ADK_TOP_P", 0.9),
        max_output_tokens=_int_env("ADK_MAX_OUTPUT_TOKENS", 2048),
        candidate_count=1,
    )


def _debug_llm_stdout_enabled() -> bool:
    raw = os.getenv("ADK_DEBUG_PRINT_LLM_STDOUT")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _build_intake_generation_config() -> genai_types.GenerateContentConfig:
    # NOTE:
    # ADK function-calling does not support response_mime_type="application/json".
    # Intake needs tool usage (municipality search), so keep standard config and
    # normalize JSON in after_model_callback.
    return _build_generation_config()


def _safe_text(value: Any, *, max_len: int = 120) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len].strip()


def _json_dump_compact(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _safe_confidence(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed < 0.0:
        return 0.0
    if parsed > 1.0:
        return 1.0
    return parsed


def _build_tool_cache_key(tool_name: str, args: dict[str, Any]) -> str:
    payload = _json_dump_compact({"tool": tool_name, "args": args})
    digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]
    return f"{_TOOL_CACHE_PREFIX}{tool_name}:{digest}"


def _normalize_tool_category(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "childcare":
        normalized = "birth"
    if normalized in {"moving", "birth", "explorer"}:
        return normalized
    return "explorer"


def _parse_int_value(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text.replace(",", ""))
    except ValueError:
        return None


def _normalize_child_age_range_entry(value: Any) -> tuple[int, int] | None:
    if isinstance(value, dict):
        lower = _parse_int_value(
            value.get("min")
            if value.get("min") is not None
            else value.get("min_age")
        )
        upper = _parse_int_value(
            value.get("max")
            if value.get("max") is not None
            else value.get("max_age")
        )
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        lower = _parse_int_value(value[0])
        upper = _parse_int_value(value[1])
    else:
        parsed = _parse_int_value(value)
        if parsed is None:
            return None
        return (parsed, parsed)

    if lower is None and upper is None:
        return None
    if lower is None:
        lower = upper
    if upper is None:
        upper = lower
    if lower is None or upper is None:
        return None
    if lower > upper:
        lower, upper = upper, lower
    return (lower, upper)


def _normalize_child_age_ranges(value: Any) -> list[tuple[int, int]]:
    entries = value if isinstance(value, list) else [value]
    normalized: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for entry in entries:
        parsed = _normalize_child_age_range_entry(entry)
        if parsed is None:
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        normalized.append(parsed)
    return normalized


def _profile_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, set, tuple)):
        return len(value) > 0
    return True


def _parse_profile_source(source: Any) -> dict[str, Any]:
    if isinstance(source, dict):
        return dict(source)
    if not isinstance(source, str) or not source.strip():
        return {}
    try:
        parsed = json.loads(source)
    except json.JSONDecodeError:
        return {}
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, str):
        try:
            nested = json.loads(parsed)
        except json.JSONDecodeError:
            return {}
        if isinstance(nested, dict):
            return nested
    return {}


def _merge_profile_maps(*sources: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        profile = _parse_profile_source(source)
        for key, value in profile.items():
            if not _profile_value_present(value):
                continue
            merged[key] = value
    return merged


def _normalize_gui_profile_map(raw_profile: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(raw_profile or {})
    normalized: dict[str, Any] = {key: None for key in GUI_OPTIONAL_PROFILE_FIELDS}

    for key, value in source.items():
        normalized[key] = value

    for key in GUI_OPTIONAL_PROFILE_FIELDS:
        value = normalized.get(key)
        if isinstance(value, str):
            stripped = value.strip()
            normalized[key] = stripped if stripped else None

    for key in (
        "couple_count",
        "child_count",
        "parent_count",
        "adult_count",
        "household_size",
        "children_counts",
        "income",
        "income_t0",
        "income_t1",
    ):
        normalized[key] = _parse_int_value(normalized.get(key))

    for key, value in list(normalized.items()):
        if re.match(r"^(couple|child|parent)_age_\d+$", key):
            normalized[key] = _parse_int_value(value)

    if normalized.get("children_counts") is None and isinstance(normalized.get("child_count"), int):
        normalized["children_counts"] = normalized["child_count"]
    if normalized.get("child_count") is None and isinstance(normalized.get("children_counts"), int):
        normalized["child_count"] = normalized["children_counts"]

    child_ages: list[int] = []
    child_age_ranges = _normalize_child_age_ranges(normalized.get("children_age_ranges"))
    if isinstance(normalized.get("children_ages"), list):
        for age in normalized["children_ages"]:
            parsed = _parse_int_value(age)
            if parsed is None:
                continue
            if parsed not in child_ages:
                child_ages.append(parsed)

    indexed_ages: list[tuple[int, int]] = []
    for key, value in normalized.items():
        matched = re.match(r"^child_age_(\d+)$", key)
        if not matched:
            continue
        parsed = _parse_int_value(value)
        if parsed is None:
            continue
        indexed_ages.append((int(matched.group(1)), parsed))
    indexed_ages.sort(key=lambda item: item[0])
    for _, age in indexed_ages:
        if age not in child_ages:
            child_ages.append(age)

    for age in child_ages:
        child_age_ranges.extend(_normalize_child_age_ranges(age))
    deduped_ranges = _normalize_child_age_ranges(child_age_ranges)

    for lower, upper in deduped_ranges:
        if lower == upper and lower not in child_ages:
            child_ages.append(lower)

    normalized["children_ages"] = child_ages if child_ages else None
    normalized["children_age_ranges"] = (
        [{"min": lower, "max": upper} for lower, upper in deduped_ranges]
        if deduped_ranges
        else None
    )

    if normalized.get("is_pregnant") is None:
        pregnancy_text = str(normalized.get("pregnancy") or "").strip()
        if pregnancy_text and pregnancy_text not in {"なし / 未定", "特になし / 未定"}:
            normalized["is_pregnant"] = True
        elif pregnancy_text in {"なし / 未定", "特になし / 未定"}:
            normalized["is_pregnant"] = False

    for key in (
        "has_disability_child",
        "has_pet",
        "is_considering_children",
        "is_pregnant",
        "is_moving",
    ):
        parsed_bool = _to_bool_or_none(normalized.get(key))
        if parsed_bool is not None:
            normalized[key] = parsed_bool

    if not normalized.get("moving_date") and normalized.get("moving"):
        normalized["moving_date"] = str(normalized["moving"]).strip() or None
    if normalized.get("is_moving") is True and not normalized.get("moving_date"):
        normalized["moving_date"] = "予定あり"
    if normalized.get("is_moving") is None and normalized.get("moving_date"):
        normalized["is_moving"] = True

    if normalized.get("income") is None and isinstance(normalized.get("income_t0"), int):
        normalized["income"] = normalized["income_t0"]

    if normalized.get("adult_count") is None:
        adults = 0
        has_adult_info = False
        for key in ("couple_count", "parent_count"):
            value = normalized.get(key)
            if isinstance(value, int) and value >= 0:
                adults += value
                has_adult_info = True
        if has_adult_info:
            normalized["adult_count"] = adults

    if normalized.get("household_size") is None:
        total = 0
        has_any_count = False
        for key in ("couple_count", "child_count", "parent_count"):
            value = normalized.get(key)
            if isinstance(value, int) and value >= 0:
                total += value
                has_any_count = True
        if has_any_count:
            normalized["household_size"] = total

    if not normalized.get("family_composition"):
        members: list[str] = []
        for key, label in (
            ("couple_count", "夫婦（本人含）"),
            ("child_count", "子ども"),
            ("parent_count", "親（同居）"),
        ):
            value = normalized.get(key)
            if isinstance(value, int) and value > 0:
                members.append(f"{label}{value}人")
        if members:
            normalized["family_composition"] = "・".join(members)

    return normalized


def _normalize_profile_json(*sources: Any) -> str:
    profile = _normalize_gui_profile_map(_merge_profile_maps(*sources))
    return _json_dump_compact(profile)


def _normalize_card_rows(cards: Any, *, limit: int = 25) -> list[dict[str, Any]]:
    if not isinstance(cards, list):
        return []

    normalized_cards: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for card in cards:
        if not isinstance(card, dict):
            continue
        key = str(card.get("id") or card.get("title") or "").strip()
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)

        item = dict(card)
        item["title"] = _safe_text(item.get("title"), max_len=120)
        item["content"] = _safe_text(item.get("content"), max_len=600)

        for field in ("steps", "required_info", "official_urls"):
            values = item.get(field)
            if not isinstance(values, list):
                item[field] = []
                continue
            cleaned: list[str] = []
            for value in values:
                max_len = 300 if field == "official_urls" else 160
                text = _safe_text(value, max_len=max_len)
                if not text:
                    continue
                if text in cleaned:
                    continue
                cleaned.append(text)
            item[field] = cleaned[:8] if field != "official_urls" else cleaned[:5]

        normalized_cards.append(item)
        if len(normalized_cards) >= limit:
            break

    return normalized_cards


def _extract_json_candidates(text: str) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []

    candidates: list[str] = [value]
    fenced = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", value, flags=re.IGNORECASE)
    for item in fenced:
        stripped = item.strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)

    first = value.find("{")
    last = value.rfind("}")
    if first >= 0 and last > first:
        bracket_slice = value[first : last + 1].strip()
        if bracket_slice and bracket_slice not in candidates:
            candidates.append(bracket_slice)

    return candidates


def _parse_payload_dict(text: str) -> dict[str, Any] | None:
    for candidate in _extract_json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _normalize_detail_selection(value: Any) -> dict[str, list[Any]]:
    if not isinstance(value, dict):
        value = {}
    numbers: list[int] = []
    titles: list[str] = []

    raw_numbers = value.get("display_numbers")
    if isinstance(raw_numbers, list):
        for item in raw_numbers:
            try:
                parsed = int(item)
            except (TypeError, ValueError):
                continue
            if parsed <= 0 or parsed in numbers:
                continue
            numbers.append(parsed)

    raw_titles = value.get("titles")
    if isinstance(raw_titles, list):
        for item in raw_titles:
            text = _safe_text(item, max_len=120)
            if len(text) < 2 or text in titles:
                continue
            titles.append(text)

    return {
        "display_numbers": numbers[:3],
        "titles": titles[:3],
    }


def _normalize_intake_domain(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized == "birth":
        normalized = "childcare"
    if normalized in {"moving", "childcare", "explorer"}:
        return normalized
    return ""


def _normalize_intake_intent(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"list", "more", "mismatch", "initial"}:
        return normalized
    return "list"


def _normalize_intake_payload(payload: Any, fallback_text: str = "") -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    municipality_text = _safe_text(
        data.get("municipality_text")
        or data.get("municipality")
        or data.get("municipality_name")
        or "",
        max_len=80,
    )
    domain = _normalize_intake_domain(data.get("domain") or data.get("category"))
    intent = _normalize_intake_intent(data.get("intent"))
    profile_source = data.get("profile")
    if profile_source is None:
        profile_source = data.get("profile_json")
    profile = _normalize_gui_profile_map(_parse_profile_source(profile_source))

    confidence_source = data.get("confidence")
    if not isinstance(confidence_source, dict):
        confidence_source = {}
    confidence_candidates: list[Any] = [
        confidence_source.get("overall"),
        confidence_source.get("municipality"),
        confidence_source.get("domain"),
        confidence_source.get("profile"),
    ]
    has_any_confidence = any(
        value is not None and _safe_confidence(value, default=0.0) > 0.0
        for value in confidence_candidates
    )
    default_confidence = _safe_confidence(confidence_source.get("overall"), default=0.0)
    municipality_confidence = _safe_confidence(
        confidence_source.get("municipality"),
        default=default_confidence,
    )
    domain_confidence = _safe_confidence(
        confidence_source.get("domain"),
        default=default_confidence,
    )
    profile_confidence = _safe_confidence(
        confidence_source.get("profile"),
        default=default_confidence,
    )
    if not has_any_confidence:
        if municipality_text:
            municipality_confidence = _LLM_DEFAULT_MUNICIPALITY_CONFIDENCE
        if domain:
            domain_confidence = _LLM_DEFAULT_DOMAIN_CONFIDENCE
        profile_fields_count = sum(1 for value in profile.values() if _profile_value_present(value))
        if profile_fields_count > 0:
            if profile_fields_count >= 3:
                profile_confidence = _LLM_DEFAULT_PROFILE_CONFIDENCE
            else:
                profile_confidence = max(
                    _LLM_PROFILE_CONFIDENCE_MIN,
                    _LLM_DEFAULT_PROFILE_CONFIDENCE - 0.05,
                )
    if not municipality_text:
        municipality_confidence = 0.0
    if not domain:
        domain_confidence = 0.0
    if not any(_profile_value_present(v) for v in profile.values()):
        profile_confidence = 0.0

    assistant_text = _safe_text(
        data.get("assistant_text")
        or data.get("question")
        or data.get("message")
        or data.get("text")
        or fallback_text,
        max_len=200,
    )
    return {
        "municipality_text": municipality_text,
        "domain": domain,
        "intent": intent,
        "profile": profile,
        "confidence": {
            "municipality": municipality_confidence,
            "domain": domain_confidence,
            "profile": profile_confidence,
            "overall": default_confidence,
        },
        "assistant_text": assistant_text,
    }


def _normalize_root_payload(payload: Any, fallback_text: str = "") -> dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    next_action = str(data.get("next_action") or "").strip().lower()
    if next_action not in _ALLOWED_NEXT_ACTIONS:
        next_action = "continue"

    assistant_text = _safe_text(data.get("assistant_text"), max_len=_MAX_ASSISTANT_TEXT_CHARS)
    if not assistant_text:
        for key in ("question", "message", "text", "reply"):
            assistant_text = _safe_text(data.get(key), max_len=_MAX_ASSISTANT_TEXT_CHARS)
            if assistant_text:
                break
    if not assistant_text:
        assistant_text = _safe_text(fallback_text, max_len=_MAX_ASSISTANT_TEXT_CHARS)

    follow_up_questions: list[str] = []
    raw_questions = data.get("follow_up_questions")
    if isinstance(raw_questions, list):
        for item in raw_questions:
            question = _safe_text(item, max_len=200)
            if not question:
                continue
            follow_up_questions.append(question)
            if len(follow_up_questions) >= 3:
                break

    detail_selection = _normalize_detail_selection(data.get("detail_selection"))

    return {
        "next_action": next_action,
        "assistant_text": assistant_text,
        "follow_up_questions": follow_up_questions,
        "detail_selection": detail_selection,
    }


def _extract_response_text_from_llm_response(llm_response: Any) -> str:
    content = getattr(llm_response, "content", None)
    if content is None:
        return ""

    text_chunks: list[str] = []
    for part in getattr(content, "parts", []) or []:
        if getattr(part, "function_call", None) is not None:
            return ""
        text = getattr(part, "text", None)
        if not isinstance(text, str):
            continue
        stripped = text.strip()
        if stripped:
            text_chunks.append(stripped)
    return "\n".join(text_chunks).strip()


def _extract_llm_output_preview(llm_response: Any) -> str:
    content = getattr(llm_response, "content", None)
    if content is None:
        return ""

    chunks: list[str] = []
    for part in getattr(content, "parts", []) or []:
        function_call = getattr(part, "function_call", None)
        if function_call is not None:
            name = _safe_text(getattr(function_call, "name", None), max_len=80) or "unknown"
            args = getattr(function_call, "args", None)
            if isinstance(args, dict):
                args_text = _json_dump_compact(args)
            else:
                args_text = _safe_text(args, max_len=300)
            chunks.append(f"<function_call name={name} args={args_text}>")

        text = getattr(part, "text", None)
        if isinstance(text, str):
            stripped = text.strip()
            if stripped:
                chunks.append(stripped)

    return "\n".join(chunks).strip()


def _debug_print_llm_output(agent_name: str, llm_response: Any, text_hint: str = "") -> None:
    if not _debug_llm_stdout_enabled():
        return

    preview = _safe_text(text_hint, max_len=_LLM_STDOUT_MAX_CHARS)
    if not preview:
        preview = _safe_text(
            _extract_llm_output_preview(llm_response),
            max_len=_LLM_STDOUT_MAX_CHARS,
        )
    if not preview:
        preview = "<empty>"
    print(f"[LLM_OUTPUT:{agent_name}] {preview}", flush=True)


def _before_intake_model_callback(callback_context, llm_request) -> None:
    _ = llm_request
    base_profile = _normalize_gui_profile_map(
        _merge_profile_maps(
            callback_context.state.get("profile"),
            callback_context.state.get(INTAKE_PROFILE_STATE_KEY),
        )
    )
    callback_context.state[INTAKE_PROFILE_STATE_KEY] = base_profile
    callback_context.state["profile"] = base_profile


def _after_intake_model_callback(callback_context, llm_response):
    text = _extract_response_text_from_llm_response(llm_response)
    _debug_print_llm_output("intake_agent", llm_response, text_hint=text)
    if not text:
        return None

    payload = _parse_payload_dict(text)
    normalized_payload = _normalize_intake_payload(payload, fallback_text=text)

    base_profile = _normalize_gui_profile_map(
        _merge_profile_maps(
            callback_context.state.get("profile"),
            callback_context.state.get(INTAKE_PROFILE_STATE_KEY),
        )
    )
    llm_profile = _normalize_gui_profile_map(
        _parse_profile_source(normalized_payload.get("profile"))
    )
    llm_profile_confidence = _safe_confidence(
        ((normalized_payload.get("confidence") or {}).get("profile")),
        default=0.0,
    )
    merged_profile = base_profile
    if llm_profile and llm_profile_confidence >= _LLM_PROFILE_CONFIDENCE_MIN:
        merged_profile = _normalize_gui_profile_map(_merge_profile_maps(base_profile, llm_profile))

    municipality_text = _safe_text(normalized_payload.get("municipality_text"), max_len=80)
    municipality_confidence = _safe_confidence(
        ((normalized_payload.get("confidence") or {}).get("municipality")),
        default=0.0,
    )
    if municipality_text and municipality_confidence >= _LLM_MUNICIPALITY_CONFIDENCE_MIN:
        callback_context.state["municipality_text"] = municipality_text

    domain = _normalize_intake_domain(normalized_payload.get("domain"))
    domain_confidence = _safe_confidence(
        ((normalized_payload.get("confidence") or {}).get("domain")),
        default=0.0,
    )
    if domain and domain_confidence >= _LLM_DOMAIN_CONFIDENCE_MIN:
        callback_context.state["requested_category"] = "birth" if domain == "childcare" else domain

    callback_context.state[INTAKE_PROFILE_STATE_KEY] = merged_profile
    callback_context.state["profile"] = merged_profile
    callback_context.state[INTAKE_SIGNAL_STATE_KEY] = {
        "municipality_text": callback_context.state.get("municipality_text") or municipality_text,
        "domain": domain,
        "intent": _normalize_intake_intent(normalized_payload.get("intent")),
        "profile": merged_profile,
        "municipality_confidence": municipality_confidence,
        "domain_confidence": domain_confidence,
        "profile_confidence": llm_profile_confidence,
        "assistant_text": _safe_text(normalized_payload.get("assistant_text"), max_len=200),
    }
    # Keep intake model text intact for parent-agent orchestration.
    # Structured signals are passed via state only.
    return llm_response


def _after_retriever_model_callback(callback_context, llm_response):
    _ = callback_context
    text = _extract_response_text_from_llm_response(llm_response)
    _debug_print_llm_output("retriever_agent", llm_response, text_hint=text)
    return llm_response


def _after_ranker_model_callback(callback_context, llm_response):
    _ = callback_context
    text = _extract_response_text_from_llm_response(llm_response)
    _debug_print_llm_output("ranker_agent", llm_response, text_hint=text)
    return llm_response


def _before_tool_callback(tool, args: dict[str, Any], tool_context) -> dict[str, Any] | None:
    tool_name = str(getattr(tool, "name", "") or "")
    if not isinstance(args, dict):
        return {
            "success": False,
            "tool": tool_name,
            "error": "invalid_tool_args",
        }

    if tool_name in {"search_municipality_candidates", "search_target_municipalities"}:
        args["query"] = _safe_text(
            args.get("query") or tool_context.state.get("municipality_text") or "",
            max_len=80,
        )

    elif tool_name == "recommend_programs":
        municipality_id = _safe_text(
            args.get("municipality_id") or tool_context.state.get("municipality_id") or "",
            max_len=80,
        )
        if not municipality_id:
            state_ids = tool_context.state.get("municipality_ids")
            if isinstance(state_ids, list) and state_ids:
                municipality_id = _safe_text(state_ids[0], max_len=80)

        if not municipality_id:
            return {
                "success": False,
                "municipality_id": "",
                "category": _normalize_tool_category(args.get("category")),
                "program_count": 0,
                "cards": [],
                "error": "missing_municipality_id",
            }

        args["municipality_id"] = municipality_id
        requested_category = _normalize_tool_category(tool_context.state.get("requested_category"))
        proposed_category = _normalize_tool_category(args.get("category") or requested_category)
        # Keep category stable to avoid accidental broadening during retrieval.
        if requested_category in {"moving", "birth"}:
            if proposed_category != requested_category:
                proposed_category = requested_category
        args["category"] = proposed_category
        args["profile_json"] = _normalize_profile_json(
            tool_context.state.get("profile"),
            args.get("profile_json"),
            tool_context.state.get(INTAKE_PROFILE_STATE_KEY),
        )

    if tool_name in {"recommend_programs"}:
        cache_key = _build_tool_cache_key(tool_name, args)
        tool_context.state[_TEMP_TOOL_CACHE_KEY] = cache_key
        cached = tool_context.state.get(cache_key)
        if isinstance(cached, dict):
            tool_context.state["app:last_tool_cache_hit"] = tool_name
            return cached

    return None


def _after_tool_callback(tool, args: dict[str, Any], tool_context, tool_response: dict[str, Any]) -> dict[str, Any] | None:
    tool_name = str(getattr(tool, "name", "") or "")
    if not isinstance(tool_response, dict):
        return None

    normalized = dict(tool_response)
    if tool_name == "recommend_programs":
        cards = _normalize_card_rows(normalized.get("cards"), limit=25)
        normalized["cards"] = cards
        normalized["program_count"] = len(cards)
        normalized["success"] = bool(normalized.get("success", True))
        tool_context.state["app:last_program_titles"] = [
            card["title"] for card in cards if isinstance(card.get("title"), str) and card["title"]
        ][:10]
        tool_context.state["app:last_program_count"] = len(cards)

    cache_key = tool_context.state.get(_TEMP_TOOL_CACHE_KEY)
    if isinstance(cache_key, str) and cache_key.startswith(_TOOL_CACHE_PREFIX):
        tool_context.state[cache_key] = normalized

    return normalized


def _on_tool_error_callback(tool, args: dict[str, Any], tool_context, error: Exception) -> dict[str, Any]:
    tool_name = str(getattr(tool, "name", "") or "")
    error_text = _safe_text(str(error), max_len=300)
    tool_context.state["app:last_tool_error"] = {
        "tool": tool_name,
        "error": error_text,
    }
    return {
        "success": False,
        "tool": tool_name,
        "error": "tool_execution_error",
        "error_detail": error_text,
    }


def _before_root_model_callback(callback_context, llm_request) -> None:
    call_count = callback_context.state.get("app:root_model_call_count", 0)
    if not isinstance(call_count, int):
        call_count = 0
    callback_context.state["app:root_model_call_count"] = call_count + 1

    config = getattr(llm_request, "config", None)
    if config is None:
        return
    if getattr(config, "temperature", None) is None:
        config.temperature = _float_env("ADK_TEMPERATURE", 0.2)
    if getattr(config, "top_p", None) is None:
        config.top_p = _float_env("ADK_TOP_P", 0.9)
    if getattr(config, "max_output_tokens", None) is None:
        config.max_output_tokens = _int_env("ADK_MAX_OUTPUT_TOKENS", 2048)


def _after_root_model_callback(callback_context, llm_response):
    text = _extract_response_text_from_llm_response(llm_response)
    _debug_print_llm_output("gov_secretary_orchestrator", llm_response, text_hint=text)
    if not text:
        return None

    payload = _parse_payload_dict(text)
    fallback_text = text if payload is None else ""
    normalized_payload = _normalize_root_payload(payload, fallback_text=fallback_text)

    callback_context.state[ROOT_PAYLOAD_STATE_KEY] = normalized_payload
    llm_response.content = genai_types.Content(
        role="model",
        parts=[genai_types.Part.from_text(text=_json_dump_compact(normalized_payload))],
    )
    return llm_response


def _ensure_model_credentials_env() -> None:
    """
    Align legacy env names with google-genai expected names for ADK.
    """
    if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY")


_ensure_model_credentials_env()


def search_target_municipalities(query: str) -> list[dict[str, str]]:
    """
    Search municipalities from backend/app/batch/targets.json.

    This is a Phase 1 bootstrap tool to help intake. It does not query Firestore.
    """
    if not TARGETS_FILE.exists():
        return []

    q = (query or "").strip().lower()
    if not q:
        return []
    data = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    results = []

    for target in data.get("targets", []):
        municipality_id = target.get("municipality_id", "")
        municipality_name = target.get("municipality_name", "")
        candidate = f"{municipality_id} {municipality_name}".lower()
        if q and q not in candidate:
            continue
        results.append(
            {
                "municipality_id": municipality_id,
                "municipality_name": municipality_name,
            }
        )

    return results[:10]


def _run_coro_sync(coro):
    """
    Run async service calls from a sync ADK tool function.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: dict[str, object] = {}
    error: dict[str, object] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            error["value"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "value" in error:
        raise error["value"]
    return result.get("value")


def search_municipality_candidates(query: str) -> list[dict[str, str]]:
    """
    Search municipalities from Firestore first, then fallback to targets.json.
    """
    q = (query or "").strip()
    if not q:
        return []

    query_variants: list[str] = []
    for candidate in (
        q,
        q.replace("　", " "),
        q.replace(" ", ""),
    ):
        candidate = candidate.strip()
        if candidate and candidate not in query_variants:
            query_variants.append(candidate)

    for token in re.split(r"[ 　]+", q):
        token = token.strip()
        if token and token not in query_variants:
            query_variants.append(token)

    stripped = re.sub(r"^(東京都|北海道|(?:京都|大阪)府|.+県)\s*", "", q).strip()
    if stripped and stripped not in query_variants:
        query_variants.append(stripped)

    service = MunicipalityService()
    for variant in query_variants:
        items = _run_coro_sync(service.search(variant)) or []
        if not items:
            continue
        return [
            {
                "municipality_id": item.id,
                "municipality_name": item.name,
            }
            for item in items[:10]
        ]

    for variant in query_variants:
        fallback = search_target_municipalities(variant)
        if fallback:
            return fallback

    return []


def _to_int_or_none(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_bool_or_none(value) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
    text = str(value).strip().lower()
    if not text:
        return None
    if text in {"1", "true", "yes", "あり", "有", "該当"}:
        return True
    if text in {"0", "false", "no", "なし", "無", "非該当"}:
        return False
    return None


def _extract_child_ages(raw_profile: dict) -> list[int]:
    ages: list[int] = []
    if isinstance(raw_profile.get("children_ages"), list):
        for age in raw_profile["children_ages"]:
            parsed = _to_int_or_none(age)
            if parsed is None:
                continue
            if parsed not in ages:
                ages.append(parsed)

    pattern = re.compile(r"^child_age_(\d+)$")
    indexed = []
    for key, value in raw_profile.items():
        matched = pattern.match(key)
        if not matched:
            continue
        parsed = _to_int_or_none(value)
        if parsed is None:
            continue
        indexed.append((int(matched.group(1)), parsed))

    indexed.sort(key=lambda x: x[0])
    for _, age in indexed:
        if age not in ages:
            ages.append(age)

    for lower, upper in _normalize_child_age_ranges(raw_profile.get("children_age_ranges")):
        if lower == upper and lower not in ages:
            ages.append(lower)
    return ages


def _extract_child_age_ranges(raw_profile: dict) -> list[dict[str, int]]:
    ranges = _normalize_child_age_ranges(raw_profile.get("children_age_ranges"))
    return [{"min": lower, "max": upper} for lower, upper in ranges]


def _normalize_profile(raw_profile: dict | None) -> UserProfile:
    raw = _normalize_gui_profile_map(raw_profile or {})

    child_count = _to_int_or_none(raw.get("children_counts"))
    if child_count is None:
        child_count = _to_int_or_none(raw.get("child_count"))

    children_ages = _extract_child_ages(raw)
    children_age_ranges = _extract_child_age_ranges(raw)

    is_pregnant = _to_bool_or_none(raw.get("is_pregnant"))
    if is_pregnant is None and "pregnancy" in raw:
        pregnancy = str(raw.get("pregnancy", "")).strip()
        is_pregnant = pregnancy not in {"", "なし / 未定", "特になし / 未定"}

    moving_date = raw.get("moving_date")
    if moving_date is None and raw.get("moving"):
        moving_date = str(raw.get("moving"))
    is_moving = _to_bool_or_none(raw.get("is_moving"))
    if moving_date is None and is_moving is True:
        moving_date = "予定あり"

    income = _to_int_or_none(raw.get("income"))
    if income is None:
        income = _to_int_or_none(raw.get("income_t0"))

    has_disability_child = _to_bool_or_none(raw.get("has_disability_child"))
    if has_disability_child is None:
        has_disability_child = _to_bool_or_none(raw.get("child_disability"))
    if has_disability_child is None:
        has_disability_child = _to_bool_or_none(raw.get("disability_child"))
    if has_disability_child is None:
        disability_text = str(raw.get("disability", "")).strip().lower()
        if disability_text in {"1", "true", "yes", "あり", "有", "該当"}:
            has_disability_child = True
        elif disability_text in {"0", "false", "no", "なし", "無", "非該当"}:
            has_disability_child = False

    has_pet = _to_bool_or_none(raw.get("has_pet"))
    is_considering_children = _to_bool_or_none(raw.get("is_considering_children"))

    household_size = _to_int_or_none(raw.get("household_size"))
    if household_size is None:
        family_total = 0
        has_any = False
        for key in ("couple_count", "child_count", "parent_count"):
            value = _to_int_or_none(raw.get(key))
            if value is None:
                continue
            family_total += value
            has_any = True
        if has_any:
            household_size = family_total

    profile_dict = {
        "couple_count": _to_int_or_none(raw.get("couple_count")),
        "child_count": _to_int_or_none(raw.get("child_count")),
        "parent_count": _to_int_or_none(raw.get("parent_count")),
        "adult_count": _to_int_or_none(raw.get("adult_count")),
        "family_composition": raw.get("family_composition"),
        "household_size": household_size,
        "children_counts": child_count,
        "children_ages": children_ages if children_ages else None,
        "children_age_ranges": children_age_ranges if children_age_ranges else None,
        "has_disability_child": (
            bool(has_disability_child) if has_disability_child is not None else None
        ),
        "has_pet": bool(has_pet) if has_pet is not None else None,
        "is_considering_children": (
            bool(is_considering_children) if is_considering_children is not None else None
        ),
        "is_pregnant": bool(is_pregnant) if is_pregnant is not None else None,
        "expected_birth_date": raw.get("expected_birth_date"),
        "moving_date": moving_date,
        "employment": raw.get("employment"),
        "income": income,
        "income_t0": _to_int_or_none(raw.get("income_t0")),
        "income_t1": _to_int_or_none(raw.get("income_t1")),
    }
    return UserProfile(**profile_dict)


def _parse_profile_json(profile_json: str | None) -> dict:
    if not profile_json:
        return {}
    try:
        parsed = json.loads(profile_json)
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, str):
            try:
                parsed_nested = json.loads(parsed)
                if isinstance(parsed_nested, dict):
                    return parsed_nested
                return {}
            except json.JSONDecodeError:
                return {}
        return {}
    except json.JSONDecodeError:
        return {}


def _normalize_category(category: str) -> RecommendationCategory:
    value = (category or "").strip().lower()
    if value == "childcare":
        value = RecommendationCategory.BIRTH.value
    if value not in {c.value for c in RecommendationCategory}:
        raise ValueError("category must be one of: explorer, moving, childcare, birth")
    return RecommendationCategory(value)


def recommend_programs(
    municipality_id: str,
    category: str,
    profile_json: str = "{}",
) -> dict:
    """
    Call existing RecommendationEngine and return structured recommendation cards.
    """
    category_enum = _normalize_category(category)
    raw_profile = _parse_profile_json(profile_json)
    profile_model = _normalize_profile(raw_profile)

    engine = RecommendationEngine(CatalogService())
    cards = _run_coro_sync(
        engine.recommend(
            municipality_id=municipality_id,
            category=category_enum,
            profile=profile_model,
        )
    ) or []

    return {
        "success": True,
        "municipality_id": municipality_id,
        "category": category_enum.value,
        "program_count": len(cards),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards": [card.model_dump(mode="json") for card in cards],
    }


_INTAKE_INSTRUCTION = (
    "あなたは入力抽出ワーカーです。"
    "利用者の発話から自治体・制度カテゴリ・プロフィール情報を構造化してください。"
    "利用者の追加要求意図（list/more/mismatch/initial）も抽出してください。"
    "自治体候補が曖昧なら search_municipality_candidates または search_target_municipalities を使って候補を確認してください。"
    "プロフィール（世帯人数、子どもの人数・年齢、子ども検討フラグ、妊娠、障害児、ペット有無、引越予定、就労、年収など）を抽出してください。"
    "子どもの年齢は children_ages（確定年齢）と children_age_ranges（年齢レンジ）の両方を使えます。"
    "例: 「小学生」「小学校のこども」→ children_age_ranges に {min:6,max:12}、"
    "「中学生」→ {min:12,max:15}。"
    "「11歳」や「11歳の小学生」は children_ages=[11]、必要なら children_age_ranges に {min:11,max:11} を入れてください。"
    "children_ages には整数のみ、children_age_ranges には {min,max} の整数のみを入れ、自由文や学齢語そのものは入れないでください。"
    "カテゴリは moving / childcare / explorer のいずれかに正規化し、不明なら unknown としてください。"
    "プロフィールは推定を断定せず、不明は null のまま返してください。"
    "質問文や提案文は生成せず、JSONのみ返してください。"
    "返答は必ずJSONオブジェクトのみとし、Markdownやコードフェンスは禁止です。"
    "JSONスキーマ: "
    '{"municipality_text":"文字列または空文字",'
    '"intent":"list|more|mismatch|initial",'
    '"domain":"moving|childcare|explorer|unknown",'
    '"profile":{"household_size":null,"children_counts":null,"children_ages":[],"children_age_ranges":[],'
    '"is_considering_children":null,"is_pregnant":null,'
    '"has_disability_child":null,"has_pet":null,"moving_date":null,"employment":null,"income":null,"income_t1":null},'
    '"confidence":{"municipality":0.0,"domain":0.0,"profile":0.0,"overall":0.0}}'
)
_INTAKE_TOOLS = [
    search_municipality_candidates,
    search_target_municipalities,
]

intake_agent = LlmAgent(
    name="intake_agent",
    model=MODEL_INTAKE,
    generate_content_config=_build_intake_generation_config(),
    description="利用者発話から意図・自治体・domain・ユーザープロファイル（子ども検討フラグ・ペット有無を含む）を抽出し、曖昧な自治体名を解決する担当",
    instruction=_INTAKE_INSTRUCTION,
    tools=_INTAKE_TOOLS,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
    before_model_callback=_before_intake_model_callback,
    after_model_callback=_after_intake_model_callback,
    before_tool_callback=_before_tool_callback,
    after_tool_callback=_after_tool_callback,
    on_tool_error_callback=_on_tool_error_callback,
)

retriever_agent = LlmAgent(
    name="retriever_agent",
    model=MODEL_RETRIEVER,
    generate_content_config=_build_generation_config(),
    description="Firestore由来の制度候補を取得する担当",
    instruction=(
        "あなたは検索ワーカーです。recommend_programs を使って制度候補を取得してください。"
        "profile_json は JSON文字列で渡し、カテゴリは moving / birth / explorer を使ってください。"
        "カテゴリ指定がない場合は explorer を使って自治体制度を広く取得してください。"
        "厳密な適用可否判定は行わず、候補取得を優先してください。"
    ),
    tools=[recommend_programs],
    before_tool_callback=_before_tool_callback,
    after_tool_callback=_after_tool_callback,
    after_model_callback=_after_retriever_model_callback,
    on_tool_error_callback=_on_tool_error_callback,
)

ranker_agent = LlmAgent(
    name="ranker_agent",
    model=MODEL_RANKER,
    generate_content_config=_build_generation_config(),
    description="候補制度をrerankして提示整形する担当",
    instruction=(
        "あなたは reranker です。候補制度を提示優先度順に並べ替えてください。"
        "制度カテゴリ一致、キーワード一致、必要性、期限の近さを加味してください。"
        "入力が少ない場合は一般性の高い制度を上位に寄せてください。"
        "厳密な適用可否判定は行わず、断定表現を避けて提示してください。"
    ),
    after_model_callback=_after_ranker_model_callback,
)

_ROOT_INSTRUCTION_BASE = (
    "あなたは行政秘書エージェントのオーケストレーターです。"
    "会話は状態機械で制御し、抽出→検索→rerankの順で委譲してください。"
    "自治体未確定時は自治体確認を継続し、自治体確定後の追加質問は最大1回にしてください。"
    "追加質問文言は固定文言を優先し、自由生成は避けてください。"
    "制度カテゴリ未指定時は自治体制度を広く検索してください。"
    "厳密な適用可否判定は行わず、候補提示と次の確認促進を優先してください。"
    "最終回答は必ずJSONオブジェクトのみを返してください（Markdown禁止、コードフェンス禁止）。"
    "JSONスキーマ: "
    '{"next_action":"ask_goal|ask_more_profile|present_list|continue",'
    '"assistant_text":"利用者向けの返答本文",'
    '"follow_up_questions":["追加質問"],'
    '"detail_selection":{"display_numbers":[1],"titles":["制度名"]}}'
    "follow_up_questions と detail_selection は不要なら空配列で返してください。"
    "候補提示時は next_action を present_list にしてください。"
)

root_agent = LlmAgent(
    name="gov_secretary_orchestrator",
    model=MODEL_ROOT,
    generate_content_config=_build_generation_config(),
    description="自治体制度案内を統合するオーケストレーター",
    instruction=(
        _ROOT_INSTRUCTION_BASE
        + "2) 制度取得は retriever_agent"
        + "3) 並び替えは ranker_agent"
        + "このオーケストレーターは仕様準拠の最小構成です。"
    ),
    before_model_callback=_before_root_model_callback,
    after_model_callback=_after_root_model_callback,
    sub_agents=[
        intake_agent,
        retriever_agent,
        ranker_agent,
    ],
)
