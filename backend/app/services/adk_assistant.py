from __future__ import annotations

import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

from app.services.municipality import MunicipalityService

logger = logging.getLogger(__name__)

ADK_APP_NAME = "adk_gov_secretary"
DEFAULT_USER_ID = "gov-secretary-user"
TARGETS_FILE = Path(__file__).resolve().parents[1] / "batch" / "targets.json"
MUNICIPALITY_FOLLOW_UP_QUESTION = "お住まいの自治体名（例: 東京都千代田区）を教えてください。"
TOPIC_FOLLOW_UP_QUESTION = (
    "どのような制度や手続きをお探しか教えてください。"
    "制度が未定なら「何でもいい」と入力してください。"
)
MUNICIPALITY_CONFIRMATION_MESSAGE = (
    "自治体が確認できていないため、先にお住まいの自治体名を教えてください。"
    "（例: 東京都千代田区）"
)
POST_MUNICIPALITY_FOLLOW_UP_QUESTION = (
    "制度の種類（任意）と、分かる範囲で世帯・年収などを教えてください。"
    "未入力でもこのまま検索できます。"
)
POST_RESULT_UPDATE_QUESTION = (
    "入力情報を修正・追加しますか？（自治体を変更した場合は再検索します）"
)
ASK_GOAL_PROFILE_GUIDE = (
    "次の情報があると、より精度高くご案内できます（分かる範囲で構いません）。\n"
    "1. 家族構成（夫婦[本人含む]・子ども・親[同居]の人数）\n"
    "2. 各ご家族の年齢\n"
    "3. 妊娠・出産予定\n"
    "4. 今後の転居予定\n"
    "5. 就労状況\n"
    "6. 現在の世帯年収\n"
    "7. 1年後の世帯年収\n"
    "8. ペットの有無\n"
    "9. 子どもを検討中か"
)
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


def _load_model_credentials_env() -> None:
    """
    Load .env for uvicorn/FastAPI execution (adk cli auto-load is not available here).
    Also map legacy GEMINI_API_KEY to GOOGLE_API_KEY for google-genai compatibility.
    """
    backend_dir = Path(__file__).resolve().parents[2]
    repo_root_dir = Path(__file__).resolve().parents[3]

    for path in (repo_root_dir / ".env", backend_dir / ".env"):
        if not path.exists():
            continue
        load_dotenv(path, override=False)

    if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY")


_load_model_credentials_env()

_ADK_IMPORT_ERROR: Exception | None = None
recommend_programs = None  # type: ignore[assignment]
intake_agent = None
root_agent = None
_AGENT_STRUCTURED_STATE_KEYS: list[str] = ["app:intake_structured_signals"]
_MAX_POST_MUNICIPALITY_FOLLOW_UP = 1
_RESULT_PAGE_SIZE = 5
_LLM_MUNICIPALITY_CONFIDENCE_MIN = 0.65
_LLM_DOMAIN_CONFIDENCE_MIN = 0.6
_LLM_PROFILE_CONFIDENCE_MIN = 0.55
_LLM_DEFAULT_MUNICIPALITY_CONFIDENCE = 0.7
_LLM_DEFAULT_DOMAIN_CONFIDENCE = 0.7
_LLM_DEFAULT_PROFILE_CONFIDENCE = 0.6
try:
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.genai import types as genai_types

    _ADK_AVAILABLE = True
except Exception as exc:  # noqa: BLE001
    Runner = None  # type: ignore[assignment]
    InMemorySessionService = None  # type: ignore[assignment]
    genai_types = None  # type: ignore[assignment]
    _ADK_AVAILABLE = False
    _ADK_IMPORT_ERROR = exc


def _load_agent_runtime() -> bool:
    global _ADK_IMPORT_ERROR, recommend_programs, intake_agent, root_agent
    global _AGENT_STRUCTURED_STATE_KEYS
    if recommend_programs is not None and intake_agent is not None and root_agent is not None:
        return True

    try:
        import adk_gov_secretary.agent as adk_agent_module

        from adk_gov_secretary.agent import recommend_programs as loaded_recommend_programs
    except Exception as exc:  # noqa: BLE001
        _ADK_IMPORT_ERROR = exc
        return False

    loaded_intake_agent = getattr(adk_agent_module, "intake_agent", None)
    loaded_root_agent = getattr(adk_agent_module, "root_agent", None)
    if loaded_intake_agent is None or loaded_root_agent is None:
        _ADK_IMPORT_ERROR = ValueError("ADK root agents are not available")
        return False

    recommend_programs = loaded_recommend_programs
    intake_agent = loaded_intake_agent
    root_agent = loaded_root_agent
    structured_key = getattr(adk_agent_module, "INTAKE_SIGNAL_STATE_KEY", None)
    if (
        isinstance(structured_key, str)
        and structured_key
        and structured_key not in _AGENT_STRUCTURED_STATE_KEYS
    ):
        _AGENT_STRUCTURED_STATE_KEYS.insert(0, structured_key)
    return True


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


def _parse_json_object(text: Any) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    for candidate in _extract_json_candidates(raw):
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _normalize_structured_extraction_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {}

    municipality_text = str(
        payload.get("municipality_text")
        or payload.get("municipality")
        or payload.get("municipality_name")
        or ""
    ).strip()
    domain = _normalize_domain_value(
        str(payload.get("domain") or payload.get("category") or "").strip()
    )
    intent = _normalize_intake_intent(payload.get("intent"))

    profile_source = payload.get("profile")
    if profile_source is None:
        profile_source = payload.get("profile_json")
    profile = _normalize_gui_profile(_try_parse_profile_value(profile_source))

    confidence_source = payload.get("confidence")
    if not isinstance(confidence_source, dict):
        confidence_source = {}

    top_level_municipality_confidence = _safe_confidence(
        payload.get("municipality_confidence"),
        default=0.0,
    )
    top_level_domain_confidence = _safe_confidence(
        payload.get("domain_confidence"),
        default=0.0,
    )
    top_level_profile_confidence = _safe_confidence(
        payload.get("profile_confidence"),
        default=0.0,
    )
    top_level_overall_confidence = _safe_confidence(
        payload.get("overall_confidence"),
        default=0.0,
    )

    confidence_candidates: list[Any] = [
        confidence_source.get("overall"),
        confidence_source.get("municipality"),
        confidence_source.get("domain"),
        confidence_source.get("profile"),
        payload.get("municipality_confidence"),
        payload.get("domain_confidence"),
        payload.get("profile_confidence"),
        payload.get("overall_confidence"),
    ]
    has_any_confidence = any(
        value is not None and _safe_confidence(value, default=0.0) > 0.0
        for value in confidence_candidates
    )
    default_confidence = _safe_confidence(
        confidence_source.get("overall"),
        default=top_level_overall_confidence,
    )
    municipality_confidence = _safe_confidence(
        confidence_source.get("municipality"),
        default=(top_level_municipality_confidence or default_confidence),
    )
    domain_confidence = _safe_confidence(
        confidence_source.get("domain"),
        default=(top_level_domain_confidence or default_confidence),
    )
    profile_confidence = _safe_confidence(
        confidence_source.get("profile"),
        default=(top_level_profile_confidence or default_confidence),
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

    return {
        "municipality_text": municipality_text,
        "domain": domain,
        "intent": intent,
        "profile": profile,
        "municipality_confidence": municipality_confidence,
        "domain_confidence": domain_confidence,
        "profile_confidence": profile_confidence,
        "overall_confidence": default_confidence,
    }


def _has_any_structured_signal(payload: dict[str, Any]) -> bool:
    municipality_text = str(payload.get("municipality_text") or "").strip()
    if municipality_text:
        return True

    domain = _normalize_domain_value(str(payload.get("domain") or ""))
    if domain:
        return True

    profile = payload.get("profile")
    if isinstance(profile, dict):
        return any(_profile_value_present(value) for value in profile.values())
    return False

def _try_parse_profile_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
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


def _profile_value_present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, set, tuple)):
        return len(value) > 0
    return True


def _merge_profile_maps(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base or {})
    for key, value in (extra or {}).items():
        if not _profile_value_present(value):
            continue
        merged[key] = value
    return merged


def _collect_state_structured_candidates(node: Any, out: list[dict[str, Any]]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_state_structured_candidates(item, out)
        return

    if not isinstance(node, dict):
        return

    state_delta = node.get("state_delta")
    if isinstance(state_delta, dict):
        for key in _AGENT_STRUCTURED_STATE_KEYS:
            candidate = _normalize_structured_extraction_payload(state_delta.get(key))
            if candidate and _has_any_structured_signal(candidate):
                out.append(candidate)

    actions = node.get("actions")
    if isinstance(actions, dict):
        action_state_delta = actions.get("state_delta")
        if isinstance(action_state_delta, dict):
            for key in _AGENT_STRUCTURED_STATE_KEYS:
                candidate = _normalize_structured_extraction_payload(action_state_delta.get(key))
                if candidate and _has_any_structured_signal(candidate):
                    out.append(candidate)

    for value in node.values():
        _collect_state_structured_candidates(value, out)


def _extract_agent_structured_signals(events: list[Any]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for event in events:
        payload = (
            event.model_dump(mode="json", by_alias=True, exclude_none=True)
            if hasattr(event, "model_dump")
            else event
        )
        _collect_state_structured_candidates(payload, candidates)

    if not candidates:
        text_chunks: list[str] = []
        for event in events:
            content = getattr(event, "content", None)
            if content is None:
                pass
            else:
                role = (getattr(content, "role", "") or "").lower()
                if not role or role in {"assistant", "model"}:
                    for part in getattr(content, "parts", []) or []:
                        text = getattr(part, "text", None)
                        if isinstance(text, str) and text.strip():
                            text_chunks.append(text.strip())

            # Some ADK event shapes only expose content through model_dump payload.
            payload = (
                event.model_dump(mode="json", by_alias=True, exclude_none=True)
                if hasattr(event, "model_dump")
                else event
            )
            if isinstance(payload, dict):
                content_dict = payload.get("content")
                if isinstance(content_dict, dict):
                    role = str(content_dict.get("role") or "").strip().lower()
                    if not role or role in {"assistant", "model"}:
                        parts = content_dict.get("parts")
                        if isinstance(parts, list):
                            for part in parts:
                                if not isinstance(part, dict):
                                    continue
                                text = part.get("text")
                                if isinstance(text, str) and text.strip():
                                    text_chunks.append(text.strip())

        for chunk in reversed(text_chunks):
            parsed = _parse_json_object(chunk)
            candidate = _normalize_structured_extraction_payload(parsed)
            if candidate and _has_any_structured_signal(candidate):
                candidates.append(candidate)
                break

    if not candidates:
        return {}

    merged_profile: dict[str, Any] = {}
    merged: dict[str, Any] = {}
    for item in candidates:
        municipality_text = str(item.get("municipality_text") or "").strip()
        if municipality_text:
            merged["municipality_text"] = municipality_text
            merged["municipality_confidence"] = _safe_confidence(
                item.get("municipality_confidence"),
                default=merged.get("municipality_confidence", 0.0),
            )

        domain = _normalize_domain_value(str(item.get("domain") or ""))
        if domain:
            merged["domain"] = domain
            merged["domain_confidence"] = _safe_confidence(
                item.get("domain_confidence"),
                default=merged.get("domain_confidence", 0.0),
            )

        intent = _normalize_intake_intent(item.get("intent"))
        if intent:
            merged["intent"] = intent

        profile = item.get("profile")
        if isinstance(profile, dict) and profile:
            merged_profile = _merge_profile_maps(merged_profile, profile)
            merged["profile_confidence"] = _safe_confidence(
                item.get("profile_confidence"),
                default=merged.get("profile_confidence", 0.0),
            )

    if merged_profile:
        merged["profile"] = _normalize_gui_profile(merged_profile)
    return merged


def _normalize_municipality_text(value: str) -> str:
    return value.replace(" ", "").replace("　", "").strip()


def _load_target_municipalities() -> list[dict[str, str]]:
    if not TARGETS_FILE.exists():
        return []
    try:
        payload = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []

    rows = payload.get("targets")
    if not isinstance(rows, list):
        return []

    normalized: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        municipality_id = str(row.get("municipality_id") or "").strip()
        municipality_name = str(row.get("municipality_name") or "").strip()
        if not municipality_id or not municipality_name:
            continue
        normalized.append(
            {
                "municipality_id": municipality_id,
                "municipality_name": municipality_name,
            }
        )
    return normalized


def _split_municipality_units(value: str) -> list[str]:
    text = _normalize_municipality_text(value)
    if not text:
        return []

    matched = re.match(r"^(東京都|北海道|(?:京都|大阪)府|.+?県)(.+)$", text)
    if not matched:
        return [text]

    local = matched.group(2).strip()
    if local:
        # 「東京都千代田区」などは、より具体な自治体（千代田区）だけを優先解決する。
        return [local]
    return [text]


def _normalize_domain_value(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized == "birth":
        return "childcare"
    if normalized in {"moving", "childcare", "explorer"}:
        return normalized
    return ""


def _normalize_intake_intent(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"list", "more", "mismatch", "initial"}:
        return normalized
    return "list"


def _looks_like_municipality_id(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", value or ""))


def _expand_municipality_id_prefixes(municipality_id: str) -> list[str]:
    value = (municipality_id or "").strip()
    if not _looks_like_municipality_id(value):
        return []

    parts = [part for part in value.split("-") if part]
    expanded: list[str] = []
    for i in range(1, len(parts) + 1):
        candidate = "-".join(parts[:i])
        if _looks_like_municipality_id(candidate):
            expanded.append(candidate)
    return expanded


def _select_primary_municipality_id(municipality_ids: list[str]) -> str:
    candidates = [item for item in municipality_ids if _looks_like_municipality_id(item)]
    if not candidates:
        return ""
    return sorted(candidates, key=lambda item: (item.count("-"), len(item)), reverse=True)[0]


def _build_search_municipality_ids(primary_municipality_id: str) -> list[str]:
    if not _looks_like_municipality_id(primary_municipality_id):
        return []
    expanded = _expand_municipality_id_prefixes(primary_municipality_id)
    if expanded:
        return expanded
    return [primary_municipality_id]


def _to_int_or_none(value: Any) -> Optional[int]:
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


def _to_bool_or_none(value: Any) -> Optional[bool]:
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


def _normalize_child_age_range_entry(value: Any) -> Optional[tuple[int, int]]:
    if isinstance(value, dict):
        lower = _to_int_or_none(
            value.get("min")
            if value.get("min") is not None
            else value.get("min_age")
        )
        upper = _to_int_or_none(
            value.get("max")
            if value.get("max") is not None
            else value.get("max_age")
        )
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        lower = _to_int_or_none(value[0])
        upper = _to_int_or_none(value[1])
    else:
        parsed = _to_int_or_none(value)
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


def _normalize_gui_profile(raw_profile: Optional[dict[str, Any]]) -> dict[str, Any]:
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
        parsed = _to_int_or_none(normalized.get(key))
        normalized[key] = parsed

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

    for key, value in list(normalized.items()):
        if re.match(r"^(couple|child|parent)_age_\d+$", key):
            normalized[key] = _to_int_or_none(value)

    if normalized.get("children_counts") is None and isinstance(normalized.get("child_count"), int):
        normalized["children_counts"] = normalized["child_count"]
    if normalized.get("child_count") is None and isinstance(normalized.get("children_counts"), int):
        normalized["child_count"] = normalized["children_counts"]

    child_ages: list[int] = []
    child_age_ranges = _normalize_child_age_ranges(normalized.get("children_age_ranges"))
    if isinstance(normalized.get("children_ages"), list):
        for age in normalized["children_ages"]:
            parsed = _to_int_or_none(age)
            if parsed is None:
                continue
            if parsed not in child_ages:
                child_ages.append(parsed)

    indexed_ages: list[tuple[int, int]] = []
    for key, value in normalized.items():
        matched = re.match(r"^child_age_(\d+)$", key)
        if not matched:
            continue
        parsed = _to_int_or_none(value)
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


def _card_key(card: dict[str, Any]) -> str:
    return str(card.get("id") or card.get("title") or "")


def _count_filled_profile_fields(profile: dict[str, Any]) -> int:
    if not isinstance(profile, dict):
        return 0

    keys = (
        "household_size",
        "children_counts",
        "children_ages",
        "children_age_ranges",
        "has_disability_child",
        "has_pet",
        "is_considering_children",
        "is_pregnant",
        "moving_date",
        "employment",
        "income",
        "income_t1",
        "adult_count",
    )
    count = 0
    for key in keys:
        value = profile.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, dict, tuple, set)) and len(value) == 0:
            continue
        count += 1
    return count


def _assign_display_numbers(
    cards: list[dict[str, Any]],
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    next_display_no = int(state.get("next_display_no") or 1)
    numbered_cards = state.setdefault("numbered_cards", {})
    if not isinstance(numbered_cards, dict):
        numbered_cards = {}
        state["numbered_cards"] = numbered_cards

    numbered: list[dict[str, Any]] = []
    for card in cards:
        item = dict(card)
        display_no = item.get("display_no")
        if not isinstance(display_no, int):
            display_no = next_display_no
            next_display_no += 1
        item["display_no"] = display_no
        numbered.append(item)
        numbered_cards[display_no] = dict(item)

    state["next_display_no"] = next_display_no
    if len(numbered_cards) > 300:
        keys = sorted([key for key in numbered_cards.keys() if isinstance(key, int)])
        for key in keys[:-300]:
            numbered_cards.pop(key, None)

    return numbered


def _merge_cards(
    primary: list[dict[str, Any]],
    secondary: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_all: list[dict[str, Any]] = []
    for source in (primary, secondary):
        for raw_card in source:
            if not isinstance(raw_card, dict):
                continue
            merged_all.append(dict(raw_card))

    # De-duplicate by card key while keeping the highest score entry.
    deduped: list[dict[str, Any]] = []
    keyed_positions: dict[str, int] = {}
    for card in merged_all:
        key = _card_key(card).strip()
        if not key:
            deduped.append(card)
            continue

        existing_index = keyed_positions.get(key)
        if existing_index is None:
            keyed_positions[key] = len(deduped)
            deduped.append(card)
            continue

        existing_card = deduped[existing_index]
        if _safe_float(card.get("score"), default=0.0) > _safe_float(
            existing_card.get("score"),
            default=0.0,
        ):
            deduped[existing_index] = card

    # Global score ordering (across municipality ids).
    deduped.sort(key=lambda card: _safe_float(card.get("score"), default=0.0), reverse=True)
    return deduped


def _pick_unseen_cards(
    cards: list[dict[str, Any]],
    shown_keys: set[str],
    limit: int = 5,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for card in cards:
        key = _card_key(card)
        marker = key or str(card.get("title") or "")
        if marker in shown_keys:
            continue
        shown_keys.add(marker)
        selected.append(card)
        if len(selected) >= limit:
            break
    return selected


def _build_initial_ask_goal_message(municipality: str = "") -> str:
    normalized = str(municipality or "").strip()
    if normalized:
        opener = (
            f"行政秘書です。自治体は「{normalized}」で承りました。"
            "次に、どのような制度や手続きをお探しか教えてください。"
        )
    else:
        opener = (
            "行政秘書です。初めに、お住まいの自治体名（必須・例: 東京都千代田区）と、"
            "どのような制度や手続きをお探しかを教えてください。"
        )
    return f"{opener}\n\n{ASK_GOAL_PROFILE_GUIDE}".strip()


def _format_domain_label(domain: str) -> str:
    mapping = {
        "childcare": "出産・子育て",
        "moving": "引越し・住所変更",
        "explorer": "未指定（幅広く）",
    }
    return mapping.get(domain, "")


def _profile_has_any_signal(profile: dict[str, Any]) -> bool:
    return _count_filled_profile_fields(profile) > 0


def _resolve_domain_with_source(
    provided_domain: str,
    inferred_domain: str,
    previous_domain: str,
    previous_source: str,
) -> tuple[str, str]:
    if provided_domain in {"moving", "childcare", "explorer"}:
        return provided_domain, "provided"
    if inferred_domain in {"moving", "childcare", "explorer"}:
        return inferred_domain, "intake"
    if previous_domain in {"moving", "childcare", "explorer"} and previous_source in {
        "provided",
        "intake",
        "state",
    }:
        return previous_domain, "state"
    if previous_domain in {"moving", "childcare"}:
        return previous_domain, "state"
    return "explorer", "default"


def _build_post_municipality_follow_up_message(municipality: str) -> str:
    normalized = str(municipality or "").strip()
    if not normalized:
        return POST_MUNICIPALITY_FOLLOW_UP_QUESTION
    return (
        f"自治体は「{normalized}」で確認できました。"
        f"{POST_MUNICIPALITY_FOLLOW_UP_QUESTION}"
    )


def _build_post_result_loop_message(
    result_count: int,
    municipality: str,
    domain: str,
) -> str:
    normalized_municipality = str(municipality or "").strip()
    domain_label = _format_domain_label(domain)
    scope = normalized_municipality or "指定自治体"
    if domain in {"moving", "childcare"} and domain_label:
        scope = f"{scope} / {domain_label}"

    if result_count > 0:
        return (
            f"{scope}で制度候補を{result_count}件表示します。"
            f"{POST_RESULT_UPDATE_QUESTION}"
        )
    return (
        f"{scope}で制度候補が見つかりませんでした。"
        f"{POST_RESULT_UPDATE_QUESTION}"
    )


def _build_more_result_loop_message(
    *,
    result_count: int,
    remaining_count: int,
    municipality: str,
    domain: str,
) -> str:
    normalized_municipality = str(municipality or "").strip()
    domain_label = _format_domain_label(domain)
    scope = normalized_municipality or "指定自治体"
    if domain in {"moving", "childcare"} and domain_label:
        scope = f"{scope} / {domain_label}"

    if result_count > 0:
        suffix = (
            f"残り{remaining_count}件あります。"
            if remaining_count > 0
            else "これで候補はすべて表示しました。"
        )
        return (
            f"{scope}で次の{result_count}件を表示します。"
            f"{suffix}"
            f"{POST_RESULT_UPDATE_QUESTION}"
        )
    return (
        f"{scope}で追加表示できる候補はありません。"
        f"{POST_RESULT_UPDATE_QUESTION}"
    )


def _mask_user_message_for_log(user_message: str) -> str:
    text = str(user_message or "").strip()
    if not text:
        return ""
    masked = re.sub(r"[0-9０-９]", "＊", text)
    if len(masked) > 200:
        return masked[:200].strip()
    return masked


def _mask_profile_for_log(profile: dict[str, Any]) -> dict[str, Any]:
    masked = dict(profile or {})
    for key in ("income", "income_t0", "income_t1"):
        raw = masked.get(key)
        if not isinstance(raw, int) or raw <= 0:
            continue
        bucket = f"{(raw // 1_000_000) * 100}万円台"
        masked[key] = bucket
    return masked


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _deadline_rank_bonus(deadline: Any) -> float:
    if not isinstance(deadline, dict):
        return 0.0
    dtype = str(deadline.get("type") or "").strip().lower()
    raw_value = deadline.get("value")
    if dtype == "within_days":
        try:
            days = int(raw_value)
        except (TypeError, ValueError):
            return 0.0
        if days <= 14:
            return 16.0
        if days <= 30:
            return 12.0
        if days <= 90:
            return 8.0
        return 3.0
    if dtype == "by_date":
        if not isinstance(raw_value, str):
            return 0.0
        candidate = raw_value.strip()
        if not candidate:
            return 0.0
        parsed = None
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m"):
            try:
                parsed = datetime.strptime(candidate, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return 0.0
        delta_days = (parsed.date() - datetime.now(timezone.utc).date()).days
        if delta_days < 0:
            return 0.0
        if delta_days <= 30:
            return 14.0
        if delta_days <= 90:
            return 10.0
        if delta_days <= 180:
            return 6.0
        return 2.0
    return 0.0


def _rerank_cards_for_presentation(
    cards: list[dict[str, Any]],
    *,
    user_message: str,
    domain: str,
    profile: dict[str, Any],
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    if not isinstance(cards, list) or not cards:
        return []
    _ = user_message, domain, profile

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_card in cards:
        if not isinstance(raw_card, dict):
            continue
        card = dict(raw_card)
        key = str(card.get("id") or card.get("title") or "").strip()
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        deduped.append(card)

    # Preserve base ranking order from recommendation engine.
    # Only reorder within contiguous equal-score groups (tie-break).
    ranked: list[dict[str, Any]] = []
    index = 0
    while index < len(deduped):
        start = index
        score_value = _safe_float(deduped[start].get("score"), default=0.0)
        while index + 1 < len(deduped):
            next_score = _safe_float(deduped[index + 1].get("score"), default=0.0)
            if next_score != score_value:
                break
            index += 1

        group = deduped[start : index + 1]
        if len(group) > 1:
            group.sort(
                key=lambda card: (
                    _deadline_rank_bonus(card.get("deadline")),
                    str(card.get("title") or ""),
                    str(card.get("id") or ""),
                ),
                reverse=True,
            )
        ranked.extend(group)
        index += 1

    if isinstance(limit, int) and limit > 0:
        return ranked[:limit]
    return ranked


def _log_turn_summary(
    *,
    session_id: str,
    user_input: str,
    extracted_user_state: dict[str, Any],
    search_conditions: dict[str, Any],
    presented_program_ids: list[str],
    next_action: str,
) -> None:
    logger.info(
        "assistant_state_machine session_id=%s next_action=%s user_input=%s extracted=%s search=%s presented_ids=%s",
        session_id,
        next_action,
        _mask_user_message_for_log(user_input),
        json.dumps(extracted_user_state, ensure_ascii=False),
        json.dumps(search_conditions, ensure_ascii=False),
        json.dumps(presented_program_ids, ensure_ascii=False),
    )


class AdkAssistantService:
    def __init__(
        self,
        app_name: str = ADK_APP_NAME,
        default_user_id: str = DEFAULT_USER_ID,
    ) -> None:
        self._app_name = app_name
        self._default_user_id = default_user_id

        if not _ADK_AVAILABLE:
            raise ValueError(
                f"Google Agent SDK is not available: {_ADK_IMPORT_ERROR}. "
                "Install backend dependencies including google-adk/google-genai."
            )
        if not _load_agent_runtime():
            raise ValueError(
                f"ADK agent runtime is not available: {_ADK_IMPORT_ERROR}. "
                "Verify backend/adk_gov_secretary/agent.py and related dependencies."
            )

        self._session_service = InMemorySessionService()
        self._intake_runner = Runner(
            app_name=f"{self._app_name}-intake",
            agent=intake_agent,
            session_service=self._session_service,
            auto_create_session=True,
        )
        self._runner = Runner(
            app_name=self._app_name,
            agent=root_agent,
            session_service=self._session_service,
            auto_create_session=True,
        )
        self._conversation_cache: dict[str, dict[str, Any]] = {}
        try:
            self._municipality_service = MunicipalityService()
        except Exception as exc:  # noqa: BLE001
            logger.info("MunicipalityService initialization skipped: %s", exc)
            self._municipality_service = None

    async def _resolve_municipality_id(self, municipality_text: str) -> str:
        value = (municipality_text or "").strip()
        if not value:
            return ""
        if _looks_like_municipality_id(value):
            return value

        normalized = _normalize_municipality_text(value)
        for row in _load_target_municipalities():
            name = row["municipality_name"]
            if _normalize_municipality_text(name) == normalized:
                return row["municipality_id"]
            if normalized and normalized in _normalize_municipality_text(name):
                return row["municipality_id"]

        if self._municipality_service is None:
            return value

        try:
            candidates = await self._municipality_service.search(value)
        except Exception as exc:  # noqa: BLE001
            logger.info("municipality id resolution skipped: %s", exc)
            return value

        if candidates:
            return candidates[0].id
        return value

    async def _resolve_municipality_ids(self, municipality_text: str) -> list[str]:
        value = (municipality_text or "").strip()
        if not value:
            return []

        resolved_ids: list[str] = []
        seen: set[str] = set()
        candidates = _split_municipality_units(value)
        if value not in candidates:
            candidates.append(value)

        for candidate in candidates:
            should_expand_prefixes = _looks_like_municipality_id(candidate)
            resolved = await self._resolve_municipality_id(candidate)
            if should_expand_prefixes:
                expanded_ids = _expand_municipality_id_prefixes(resolved)
            else:
                expanded_ids = [resolved] if _looks_like_municipality_id(resolved) else []

            for municipality_id in expanded_ids:
                if municipality_id in seen:
                    continue
                seen.add(municipality_id)
                resolved_ids.append(municipality_id)

        return resolved_ids

    async def _run_intake_extraction(
        self,
        *,
        user_id: str,
        session_id: str,
        user_message: str,
        base_profile: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(user_message, str) or not user_message.strip():
            return {}

        runner = getattr(self, "_intake_runner", None)
        if runner is None or not hasattr(runner, "run_async"):
            return {}

        events: list[Any] = []
        intake_session_id = f"{session_id}:intake"
        state_delta = {
            "latest_user_message": user_message.strip(),
            "profile": _normalize_gui_profile(base_profile),
        }
        message = genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=user_message.strip())],
        )
        try:
            async for event in runner.run_async(
                user_id=user_id,
                session_id=intake_session_id,
                new_message=message,
                state_delta=state_delta,
            ):
                events.append(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning("intake extraction failed: %s", exc)
            return {}

        signals = _extract_agent_structured_signals(events)
        if not isinstance(signals, dict):
            return {}
        return signals

    def _fallback_recommend_cards(
        self,
        municipality_ids: list[str],
        domain: str,
        profile: dict[str, Any],
        broaden: bool = False,
    ) -> list[dict[str, Any]]:
        if not municipality_ids:
            return []

        category = "explorer" if broaden else ("birth" if domain == "childcare" else domain)
        if recommend_programs is None:
            runner = getattr(self, "_runner", None)
            if runner is None or not hasattr(runner, "run_async"):
                # Lightweight test stubs instantiate the service via __new__
                # without ADK runner/runtime. Skip runtime import in that case.
                return []
            if not _load_agent_runtime():
                return []

        merged_cards: list[dict[str, Any]] = []
        for municipality_id in municipality_ids:
            try:
                result = recommend_programs(
                    municipality_id=municipality_id,
                    category=category,
                    profile_json=json.dumps(profile or {}, ensure_ascii=False),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("fallback recommend failed: %s municipality_id=%s", exc, municipality_id)
                continue

            cards = result.get("cards")
            if isinstance(cards, list):
                merged_cards = _merge_cards(merged_cards, cards)

        return merged_cards

    async def chat(
        self,
        municipality: Optional[str] = None,
        domain: Optional[str] = None,
        profile: Optional[dict[str, Any]] = None,
        user_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        expect_tool_result: bool = False,
        request_more: bool = False,
    ) -> dict[str, Any]:
        resolved_user_id = (user_id or self._default_user_id).strip() or self._default_user_id
        resolved_session_id = session_id or str(uuid.uuid4())
        normalized_user_message = str(user_message or "").strip()
        _ = resolved_user_id

        state = self._conversation_cache.setdefault(
            resolved_session_id,
            {
                "shown_card_keys": set(),
                "last_cards_all": [],
                "last_presented_cards": [],
                "numbered_cards": {},
                "next_display_no": 1,
                "last_profile": {},
                "last_domain": "",
                "last_municipality": "",
                "last_municipality_id": "",
                "last_municipality_ids": [],
                "tool_history": [],
                "last_follow_up_questions": [],
                "last_result_context": None,
                "user_state": {
                    "municipality": "",
                    "domain": "explorer",
                    "domain_source": "default",
                    "profile": {},
                    "free_text_summary": "",
                },
                "system_state": {
                    "post_municipality_prompt_count": 0,
                    "last_search_conditions": {},
                    "last_presented_program_ids": [],
                },
            },
        )
        user_state = state.setdefault("user_state", {})
        if not isinstance(user_state, dict):
            user_state = {}
            state["user_state"] = user_state
        system_state = state.setdefault("system_state", {})
        if not isinstance(system_state, dict):
            system_state = {}
            state["system_state"] = system_state

        previous_profile = _normalize_gui_profile(
            user_state.get("profile")
            if isinstance(user_state.get("profile"), dict)
            else state.get("last_profile")
        )
        incoming_profile = _normalize_gui_profile(dict(profile) if isinstance(profile, dict) else {})
        base_profile = _normalize_gui_profile(_merge_profile_maps(previous_profile, incoming_profile))

        extracted_signals = await self._run_intake_extraction(
            user_id=resolved_user_id,
            session_id=resolved_session_id,
            user_message=normalized_user_message,
            base_profile=base_profile,
        )
        extracted_profile = _normalize_gui_profile(
            dict(extracted_signals.get("profile"))
            if isinstance(extracted_signals.get("profile"), dict)
            else {}
        )
        extracted_profile_confidence = _safe_confidence(
            extracted_signals.get("profile_confidence"),
            default=0.0,
        )
        resolved_profile = _normalize_gui_profile(base_profile)
        if extracted_profile and extracted_profile_confidence >= _LLM_PROFILE_CONFIDENCE_MIN:
            resolved_profile = _normalize_gui_profile(
                _merge_profile_maps(resolved_profile, extracted_profile)
            )

        input_municipality = str(municipality or "").strip()
        extracted_municipality_raw = str(extracted_signals.get("municipality_text") or "").strip()
        extracted_municipality_confidence = _safe_confidence(
            extracted_signals.get("municipality_confidence"),
            default=0.0,
        )
        extracted_municipality_high_conf = (
            extracted_municipality_raw
            if extracted_municipality_confidence >= _LLM_MUNICIPALITY_CONFIDENCE_MIN
            else ""
        )
        previous_municipality = str(
            user_state.get("municipality") or state.get("last_municipality") or ""
        ).strip()
        extracted_municipality_candidate = extracted_municipality_raw or extracted_municipality_high_conf
        resolved_municipality = (
            input_municipality
            or extracted_municipality_high_conf
            or previous_municipality
            or extracted_municipality_candidate
        )

        provided_domain = _normalize_domain_value(str(domain or ""))
        inferred_domain = _normalize_domain_value(str(extracted_signals.get("domain") or ""))
        inferred_domain_confidence = _safe_confidence(
            extracted_signals.get("domain_confidence"),
            default=0.0,
        )
        if inferred_domain_confidence < _LLM_DOMAIN_CONFIDENCE_MIN:
            inferred_domain = ""
        previous_domain = _normalize_domain_value(
            str(user_state.get("domain") or state.get("last_domain") or "")
        )
        previous_domain_source = str(user_state.get("domain_source") or "default").strip().lower()
        resolved_domain, domain_source = _resolve_domain_with_source(
            provided_domain=provided_domain,
            inferred_domain=inferred_domain,
            previous_domain=previous_domain,
            previous_source=previous_domain_source,
        )

        if normalized_user_message:
            user_state["free_text_summary"] = _mask_user_message_for_log(normalized_user_message)

        user_state["municipality"] = resolved_municipality
        user_state["domain"] = resolved_domain
        user_state["domain_source"] = domain_source
        user_state["profile"] = resolved_profile
        state["last_profile"] = resolved_profile
        state["last_domain"] = resolved_domain
        state["last_municipality"] = resolved_municipality

        history = state.setdefault("tool_history", [])
        if not isinstance(history, list):
            history = []
            state["tool_history"] = history

        intent = (
            "initial"
            if not normalized_user_message
            else _normalize_intake_intent(extracted_signals.get("intent"))
        )
        if request_more:
            intent = "more"
        history_count = len([item for item in history if isinstance(item, dict)])
        if history_count == 0 and not normalized_user_message:
            follow_up_questions = (
                [TOPIC_FOLLOW_UP_QUESTION]
                if resolved_municipality
                else [MUNICIPALITY_FOLLOW_UP_QUESTION, TOPIC_FOLLOW_UP_QUESTION]
            )
            assistant_text = _build_initial_ask_goal_message(resolved_municipality)
            state["last_follow_up_questions"] = follow_up_questions
            _log_turn_summary(
                session_id=resolved_session_id,
                user_input=normalized_user_message,
                extracted_user_state={
                    "municipality": resolved_municipality,
                    "domain": "",
                    "profile": _mask_profile_for_log(resolved_profile),
                },
                search_conditions={},
                presented_program_ids=[],
                next_action="ask_goal",
            )
            return {
                "success": True,
                "session_id": resolved_session_id,
                "assistant_text": assistant_text,
                "cards": [],
                "next_action": "ask_goal",
                "follow_up_questions": follow_up_questions,
                "events_count": 0,
            }

        resolved_municipality_candidates = await self._resolve_municipality_ids(resolved_municipality)
        resolved_municipality_id = _select_primary_municipality_id(resolved_municipality_candidates)
        state["last_municipality_id"] = resolved_municipality_id
        state["last_municipality_ids"] = [resolved_municipality_id] if resolved_municipality_id else []

        if not resolved_municipality_id:
            follow_up_questions = [MUNICIPALITY_FOLLOW_UP_QUESTION]
            state["last_follow_up_questions"] = follow_up_questions
            _log_turn_summary(
                session_id=resolved_session_id,
                user_input=normalized_user_message,
                extracted_user_state={
                    "municipality": "",
                    "domain": "",
                    "profile": _mask_profile_for_log(resolved_profile),
                },
                search_conditions={},
                presented_program_ids=[],
                next_action="ask_goal",
            )
            return {
                "success": True,
                "session_id": resolved_session_id,
                "assistant_text": MUNICIPALITY_CONFIRMATION_MESSAGE,
                "cards": [],
                "next_action": "ask_goal",
                "follow_up_questions": follow_up_questions,
                "events_count": 0,
            }

        has_domain_signal = domain_source in {"provided", "intake", "state"} and (
            resolved_domain in {"moving", "childcare", "explorer"}
        )
        has_profile_signal = _profile_has_any_signal(resolved_profile)
        has_non_municipality_info = has_domain_signal or has_profile_signal
        post_municipality_prompt_count = int(system_state.get("post_municipality_prompt_count") or 0)
        if (
            not has_non_municipality_info
            and post_municipality_prompt_count < _MAX_POST_MUNICIPALITY_FOLLOW_UP
        ):
            system_state["post_municipality_prompt_count"] = post_municipality_prompt_count + 1
            follow_up_questions = [POST_MUNICIPALITY_FOLLOW_UP_QUESTION]
            assistant_text = _build_post_municipality_follow_up_message(resolved_municipality)
            state["last_follow_up_questions"] = follow_up_questions
            _log_turn_summary(
                session_id=resolved_session_id,
                user_input=normalized_user_message,
                extracted_user_state={
                    "municipality": resolved_municipality,
                    "domain": "",
                    "profile": _mask_profile_for_log(resolved_profile),
                },
                search_conditions={},
                presented_program_ids=[],
                next_action="ask_more_profile",
            )
            return {
                "success": True,
                "session_id": resolved_session_id,
                "assistant_text": assistant_text,
                "cards": [],
                "next_action": "ask_more_profile",
                "follow_up_questions": follow_up_questions,
                "events_count": 0,
            }

        search_domain = resolved_domain if resolved_domain in {"moving", "childcare"} else "explorer"
        search_municipality_ids = _build_search_municipality_ids(resolved_municipality_id)
        if not search_municipality_ids and resolved_municipality_id:
            search_municipality_ids = [resolved_municipality_id]
        if resolved_municipality_id and resolved_municipality_id not in search_municipality_ids:
            search_municipality_ids.append(resolved_municipality_id)

        search_conditions: dict[str, Any] = {
            "municipality_id": resolved_municipality_id,
            "municipality_ids": search_municipality_ids,
            "domain": search_domain,
            "profile": _mask_profile_for_log(resolved_profile),
        }
        search_context = {
            "municipality_ids": list(search_municipality_ids),
            "domain": search_domain,
            "profile": _normalize_gui_profile(resolved_profile),
        }
        previous_result_context = state.get("last_result_context")
        use_cached_for_more = (
            intent == "more"
            and isinstance(previous_result_context, dict)
            and previous_result_context == search_context
            and isinstance(state.get("last_cards_all"), list)
            and bool(state.get("last_cards_all"))
        )

        tool_calls_for_history: list[str] = []
        if use_cached_for_more:
            ranked_cards = [
                dict(card)
                for card in (state.get("last_cards_all") or [])
                if isinstance(card, dict)
            ]
            shown_card_keys = state.setdefault("shown_card_keys", set())
            if not isinstance(shown_card_keys, set):
                shown_card_keys = set()
                state["shown_card_keys"] = shown_card_keys
            next_cards = _pick_unseen_cards(
                ranked_cards,
                shown_card_keys,
                limit=_RESULT_PAGE_SIZE,
            )
            selected_cards = _assign_display_numbers(next_cards, state) if next_cards else []
            state["last_presented_cards"] = list(selected_cards)
            system_state["last_search_conditions"] = dict(search_conditions)
        else:
            cards = self._fallback_recommend_cards(
                municipality_ids=search_municipality_ids,
                domain=search_domain,
                profile=resolved_profile,
                broaden=False,
            )
            tool_calls_for_history = ["recommend_programs"]
            if not cards and search_domain != "explorer":
                cards = self._fallback_recommend_cards(
                    municipality_ids=search_municipality_ids,
                    domain="explorer",
                    profile=resolved_profile,
                    broaden=True,
                )
                search_conditions["fallback_domain"] = "explorer"

            ranked_cards = _rerank_cards_for_presentation(
                cards,
                user_message=normalized_user_message,
                domain=search_domain,
                profile=resolved_profile,
            )
            state["last_cards_all"] = list(ranked_cards)
            state["last_result_context"] = search_context
            state["numbered_cards"] = {}
            state["next_display_no"] = 1
            shown_card_keys = set()
            state["shown_card_keys"] = shown_card_keys
            next_cards = _pick_unseen_cards(
                ranked_cards,
                shown_card_keys,
                limit=_RESULT_PAGE_SIZE,
            )
            selected_cards = _assign_display_numbers(next_cards, state) if next_cards else []
            state["last_presented_cards"] = list(selected_cards)
            system_state["last_search_conditions"] = dict(search_conditions)

        presented_program_ids = [
            str(card.get("id") or "").strip()
            for card in selected_cards
            if str(card.get("id") or "").strip()
        ]
        system_state["last_presented_program_ids"] = presented_program_ids

        if expect_tool_result and not selected_cards:
            raise ValueError("recommend_programs の結果を取得できませんでした")

        next_action = "present_list"
        follow_up_questions = [POST_RESULT_UPDATE_QUESTION]
        if use_cached_for_more:
            shown_count = len(state.get("shown_card_keys") or set())
            remaining_count = max(0, len(state.get("last_cards_all") or []) - shown_count)
            assistant_text = _build_more_result_loop_message(
                result_count=len(selected_cards),
                remaining_count=remaining_count,
                municipality=resolved_municipality,
                domain=search_domain,
            )
        else:
            assistant_text = _build_post_result_loop_message(
                result_count=len(selected_cards),
                municipality=resolved_municipality,
                domain=search_domain,
            )

        history_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "intent": intent,
            "route_tier": "state_machine",
            "route_reasons": (
                ["state-machine:v2", "pagination:next"]
                if use_cached_for_more
                else ["state-machine:v2"]
            ),
            "next_action": next_action,
            "tool_calls": tool_calls_for_history,
            "events_count": 0,
            "cards_count": len(selected_cards),
            "degraded_reasons": [],
            "list_present_count": 0,
            "detail_show_count": 0,
            "detail_transition_rate": 0.0,
        }
        history.append(history_entry)
        if len(history) > 50:
            del history[:-50]

        state["last_follow_up_questions"] = list(follow_up_questions)
        _log_turn_summary(
            session_id=resolved_session_id,
            user_input=normalized_user_message,
            extracted_user_state={
                "municipality": resolved_municipality,
                "domain": resolved_domain if domain_source in {"provided", "intake", "state"} else "",
                "profile": _mask_profile_for_log(resolved_profile),
            },
            search_conditions=search_conditions,
            presented_program_ids=presented_program_ids,
            next_action=next_action,
        )

        return {
            "success": True,
            "session_id": resolved_session_id,
            "assistant_text": assistant_text,
            "cards": selected_cards,
            "next_action": next_action,
            "follow_up_questions": follow_up_questions,
            "events_count": 0,
        }


_ADK_ASSISTANT_SERVICE: Optional[AdkAssistantService] = None


def get_adk_assistant_service_singleton() -> AdkAssistantService:
    global _ADK_ASSISTANT_SERVICE
    if _ADK_ASSISTANT_SERVICE is None:
        _ADK_ASSISTANT_SERVICE = AdkAssistantService()
    return _ADK_ASSISTANT_SERVICE
