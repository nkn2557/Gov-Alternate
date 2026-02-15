import json
import re
from typing import Dict, Any
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from app.core.config import settings


def _extract_json_candidates(text: str) -> list[str]:
    value = (text or "").strip()
    if not value:
        return []

    candidates: list[str] = [value]
    fenced = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```", value, flags=re.IGNORECASE)
    for item in fenced:
        stripped = item.strip()
        if stripped and stripped not in candidates:
            candidates.append(stripped)

    first_obj = value.find("{")
    last_obj = value.rfind("}")
    if first_obj >= 0 and last_obj > first_obj:
        sliced = value[first_obj : last_obj + 1].strip()
        if sliced and sliced not in candidates:
            candidates.append(sliced)

    first_arr = value.find("[")
    last_arr = value.rfind("]")
    if first_arr >= 0 and last_arr > first_arr:
        sliced = value[first_arr : last_arr + 1].strip()
        if sliced and sliced not in candidates:
            candidates.append(sliced)
    return candidates


def _coerce_program_payload(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value

    if isinstance(value, str) and value.strip():
        for candidate in _extract_json_candidates(value):
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            coerced = _coerce_program_payload(parsed)
            if coerced:
                return coerced
        return {}

    if isinstance(value, list):
        # Prefer entries with title_official, then the first dict entry.
        first_dict: Dict[str, Any] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            if not first_dict:
                first_dict = item
            title = str(item.get("title_official") or "").strip()
            if title:
                return item
        return first_dict

    return {}


def _response_text(response: Any) -> str:
    text = None
    try:
        text = response.text
    except Exception:
        text = None

    if isinstance(text, str) and text.strip():
        return text.strip()

    chunks: list[str] = []
    candidates = getattr(response, "candidates", []) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if content is None:
            continue
        parts = getattr(content, "parts", []) or []
        for part in parts:
            part_text = getattr(part, "text", None)
            if isinstance(part_text, str) and part_text.strip():
                chunks.append(part_text.strip())
    return "\n".join(chunks).strip()


class LLMExtractor:
    def __init__(self):
        self.project_id = settings.PROJECT_ID
        self.location = settings.GOOGLE_CLOUD_REGION
        self.model_name = settings.GEMINI_MODEL_NAME
        
        self._initialized = False
        self._model = None

    def _ensure_initialized(self):
        if not self._initialized:
            vertexai.init(project=self.project_id, location=self.location)
            self._model = GenerativeModel(self.model_name)
            self._initialized = True

    async def extract_program_info(self, html_text: str) -> Dict[str, Any]:
        """
        Extracts structured program information from HTML text using Gemini.
        Returns a dictionary matching the Program model fields.
        """
        self._ensure_initialized()

        base_prompt = """
        You are an expert at extracting structured government program data from web pages.
        Analyze the following HTML text (or PDF-extracted text) and extract the details for a "Municipality Program" (public service).
        
        Output must be valid JSON matching this structure:
        {{
            "title_official": "Official name of the program",
            "title_common": "Easy to understand name (Japanese)",
            "summary": "Brief summary of the program (Japanese, max 200 chars)",
            "steps": ["Step 1", "Step 2", ...],
            "kind": "One of [procedure, cash_benefit, subsidy_reimbursement, voucher_coupon, fee_reduction_exemption, consultation_support]",
            "actions": ["One or more of [report, apply, change, register, use, book]"],
            "importance": "One of [high, medium, low, unknown]",
            "life_event_tags": ["One or more of [moving_out, moving_in, moving_within, mynumber_change, childcare_address_change, pregnancy, birth, newborn, age_0_2, age_3_5, preschool, health_checkup, vaccination, child_allowance, medical_subsidy, childcare_application]"],
            "deadline": {{
                "type": "One of [within_days, by_date, none, unknown]",
                "value": "Value corresponding to type (e.g. 14 for within_days, '2025-03-31' for by_date)",
                "note": "Any additional deadline info"
            }},
            "eligibility_text": "Who is eligible",
            "eligibility_profile": {{
                "requires_moving": "true/false/null",
                "requires_pregnancy": "true/false/null",
                "requires_children": "true/false/null",
                "requires_disability_child": "true/false/null",
                "requires_single_parent": "true/false/null",
                "child_count_min": "number or null",
                "child_count_max": "number or null",
                "child_age_min": "number or null",
                "child_age_max": "number or null",
                "household_size_min": "number or null",
                "household_size_max": "number or null",
                "income_min": "number (JPY) or null",
                "income_max": "number (JPY) or null",
                "applicable_employment": ["employment conditions if explicit"],
                "is_mandatory": "true/false/null"
            }},
            "need_prevalence_score": "number 0-100 (estimated share of residents likely to need this)",
            "required_info": ["Item 1", "Item 2"...]
        }}
        
        IMPORTANT Rules:
        1. "kind", "actions", "importance", "life_event_tags", "deadline.type" MUST be one of the Enums listed above. Do not invent new values (e.g. '住民登録' is invalid for life_event_tags).
        2. If "life_event_tags" is unclear, map it to the closest Enum or leave empty list.
        3. "required_info" must be a list of strings, even if empty (use [] not null).
        4. "importance": Use "high" for mandatory procedures (e.g., required filings like move-in notification), "medium" for recommended actions (things people should check/do), "low" for optional actions, "unknown" if unclear.
        5. "eligibility_profile" is optional but preferred; use null for unknown scalar fields.
        6. Do not infer strict thresholds unless explicitly stated in text. Keep unknowns as null.
        7. "need_prevalence_score" must be 0-100 and represent estimated prevalence (how many residents out of 100 may need this).
           Use this calibration:
           - 90-100: Universal/near-universal mandatory procedures for target residents (e.g., move-in/out registration).
           - 70-89: Common procedures/benefits needed by a large subset of residents in the life event.
           - 40-69: Moderately common supports (applicable to some households, not majority).
           - 10-39: Niche programs with specific eligibility (limited subset).
           - 0-9: Very rare/special-case programs.
           If evidence is weak or ambiguous, set 50 (neutral) instead of extreme values.
        8. "need_prevalence_score" and "importance" are different axes:
           prevalence = how common, importance = consequence/priority if missed.
        """

        generation_config = GenerationConfig(
            response_mime_type="application/json",
            temperature=0.0,
        )

        prompt = (
            f"{base_prompt}\n\n"
            f"HTML Content:\n{html_text[:30000]}\n\n"
            "Return only one JSON object. Do not return an array."
        )

        try:
            response = await self._model.generate_content_async(
                prompt,
                generation_config=generation_config
            )
            text = _response_text(response)
            if not text:
                return {}
            return _coerce_program_payload(text)
        except Exception as e:
            print(f"Error calling Vertex AI: {e}")
            return {}
