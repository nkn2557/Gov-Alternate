import logging
from typing import List, Dict, Any
from app.models.api import UserProfile, RecommendationCard, RecommendationCategory
from app.models.program import (
    Program,
    LifeEventTag,
    DeadlineType,
    ProgramImportance,
    ProgramEligibility,
    ProgramKind,
    ProgramAction,
)
from app.services.catalog import CatalogService

logger = logging.getLogger(__name__)

_PET_KEYWORDS_JA = (
    "ペット",
    "犬",
    "猫",
    "愛犬",
    "愛猫",
    "狂犬病",
    "飼育",
    "動物",
)
_PET_KEYWORDS_EN = ("pet", "dog", "cat", "animal", "rabies")
_PET_TAG_HINTS = {
    "pet",
    "pets",
    "dog",
    "cat",
    "animal",
    "animal_welfare",
    "pet_support",
    "dog_registration",
    "rabies_vaccination",
}
_NEGATIVE_KEYWORDS_JA = (
    "死亡",
    "死去",
    "亡く",
)
_MOVING_ADDRESS_CHANGE_KEYWORDS_JA = (
    "住所",
    "変更",
)


class RecommendationEngine:
    def __init__(self, catalog_service: CatalogService):
        self.catalog_service = catalog_service

    def _normalize_employment_label(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""

        mapping = {
            "就業中": "employed",
            "勤務中": "employed",
            "会社員": "employed",
            "育休・休職中": "leave",
            "育休中": "leave",
            "休職中": "leave",
            "失業中": "unemployed",
            "無職": "unemployed",
            "再就職予定": "reemployment_planned",
        }
        if text in mapping:
            return mapping[text]
        return text

    def _importance_weight(self, importance: ProgramImportance) -> float:
        if importance == ProgramImportance.HIGH:
            return 80.0
        if importance == ProgramImportance.MEDIUM:
            return 45.0
        if importance == ProgramImportance.LOW:
            return 20.0
        return 30.0

    def _common_program_boost(self, tags: set[LifeEventTag]) -> float:
        # Keep tag boost generic and small to avoid domain-specific overfitting.
        return min(float(len(tags)) * 3.0, 15.0)

    def _need_prevalence_boost(self, program: Program) -> float:
        raw = getattr(program, "need_prevalence_score", None)
        if raw is None:
            return 0.0
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return 0.0
        clamped = max(0.0, min(100.0, parsed))
        # 0-100 => 0-80 points
        return clamped * 0.8

    def _importance_rank(self, importance: ProgramImportance) -> int:
        if importance == ProgramImportance.HIGH:
            return 3
        if importance == ProgramImportance.MEDIUM:
            return 2
        if importance == ProgramImportance.LOW:
            return 1
        return 0

    def _is_benefit_kind(self, program: Program) -> bool:
        return program.kind in {
            ProgramKind.CASH_BENEFIT,
            ProgramKind.SUBSIDY_REIMBURSEMENT,
            ProgramKind.VOUCHER_COUPON,
            ProgramKind.FEE_REDUCTION_EXEMPTION,
        }

    def _is_mandatory_procedure(self, program: Program) -> bool:
        eligibility = program.eligibility_profile
        if eligibility and eligibility.is_mandatory is True:
            return True

        if program.kind != ProgramKind.PROCEDURE:
            return False
        if program.importance != ProgramImportance.HIGH:
            return False

        actions = set(program.actions or [])
        if actions.intersection({ProgramAction.REPORT, ProgramAction.CHANGE, ProgramAction.REGISTER}):
            return True

        tags = set(program.life_event_tags or [])
        core_mandatory_tags = {
            LifeEventTag.MOVING_IN,
            LifeEventTag.MOVING_OUT,
            LifeEventTag.MYNUMBER_CHANGE,
        }
        return bool(tags.intersection(core_mandatory_tags))

    def _priority_bucket(self, program: Program) -> int:
        # Mandatory procedures are always on the top tier.
        if self._is_mandatory_procedure(program):
            return 3
        if self._is_benefit_kind(program):
            return 2
        return 1

    def _priority_group(self, priority_bucket: int) -> int:
        # Bucket 3 (mandatory procedures) and bucket 2 (benefits) are treated
        # as the same top group. Ranking inside the group is score-first.
        if priority_bucket >= 2:
            return 2
        return 1

    def _normalize_profile(self, profile: UserProfile) -> Dict[str, Any]:
        """Derive flags from UserProfile."""
        flags = {
            "has_children": None,
            "has_disability_child": False,
            "has_pet": None,
            "is_considering_children": False,
            "is_pregnant": profile.is_pregnant if profile and profile.is_pregnant is not None else None,
            "is_moving": False,
            "child_age_tags": set(),
            "children_ages": [],
            "children_age_ranges": [],
            "income": None,
            "household_size": None,
            "child_count": None,
            "couple_count": None,
            "parent_count": None,
            "adult_count": None,
            "is_single_parent": None,
            "employment": "",
        }
        if not profile:
            return flags

        # Moving
        if profile.moving_date:
            flags["is_moving"] = True
        
        # Pregnancy
        if profile.is_pregnant is not None:
            flags["is_pregnant"] = bool(profile.is_pregnant)

        # Children
        if profile.children_counts and profile.children_counts > 0:
            flags["has_children"] = True
        elif profile.children_counts == 0:
            flags["has_children"] = False
        if profile.child_count and profile.child_count > 0:
            flags["has_children"] = True
        elif profile.child_count == 0 and flags["has_children"] is None:
            flags["has_children"] = False
        if profile.has_disability_child:
            flags["has_disability_child"] = True
        elif profile.has_disability_child is False:
            flags["has_disability_child"] = False
        if profile.has_pet is not None:
            flags["has_pet"] = bool(profile.has_pet)
        if profile.is_considering_children is not None:
            flags["is_considering_children"] = bool(profile.is_considering_children)
        if profile.children_ages:
            flags["has_children"] = True
            flags["children_ages"] = list(profile.children_ages)
            for age in profile.children_ages:
                if isinstance(age, int):
                    flags["children_age_ranges"].append((age, age))
            for age in profile.children_ages:
                if age == 0:
                    flags["child_age_tags"].add(LifeEventTag.NEWBORN)
                    flags["child_age_tags"].add(LifeEventTag.AGE_0_2)
                elif 1 <= age <= 2:
                    flags["child_age_tags"].add(LifeEventTag.AGE_0_2)
                elif 3 <= age <= 5:
                    flags["child_age_tags"].add(LifeEventTag.AGE_3_5)
                    flags["child_age_tags"].add(LifeEventTag.PRESCHOOL)
                # Add more mappings as needed
        if profile.children_age_ranges:
            for raw_range in profile.children_age_ranges:
                normalized_range = self._normalize_child_age_range(raw_range)
                if normalized_range is None:
                    continue
                lower, upper = normalized_range
                if normalized_range not in flags["children_age_ranges"]:
                    flags["children_age_ranges"].append(normalized_range)
                if lower == upper and lower not in flags["children_ages"]:
                    flags["children_ages"].append(lower)
                self._add_child_age_tags_from_range(flags["child_age_tags"], lower, upper)
            if flags["children_age_ranges"]:
                flags["has_children"] = True

        child_count = profile.children_counts
        if not isinstance(child_count, int):
            child_count = profile.child_count
        if not isinstance(child_count, int) and flags["children_ages"]:
            child_count = len(flags["children_ages"])
        flags["child_count"] = child_count if isinstance(child_count, int) else None

        couple_count = profile.couple_count if isinstance(profile.couple_count, int) else None
        parent_count = profile.parent_count if isinstance(profile.parent_count, int) else None
        adult_count = profile.adult_count if isinstance(profile.adult_count, int) else None
        if adult_count is None and isinstance(couple_count, int) and isinstance(parent_count, int):
            adult_count = couple_count + parent_count
        flags["couple_count"] = couple_count
        flags["parent_count"] = parent_count
        flags["adult_count"] = adult_count

        # Infer single parent only when a strong signal exists.
        is_single_parent = None
        if isinstance(flags["child_count"], int) and flags["child_count"] > 0:
            if isinstance(couple_count, int):
                is_single_parent = couple_count <= 1
            elif isinstance(adult_count, int):
                is_single_parent = adult_count == 1
            elif isinstance(profile.family_composition, str):
                family_text = profile.family_composition.strip()
                if family_text:
                    if "ひとり親" in family_text or "母子" in family_text or "父子" in family_text:
                        is_single_parent = True
        flags["is_single_parent"] = is_single_parent

        if profile.income is not None:
            flags["income"] = profile.income
        elif profile.income_t0 is not None:
            flags["income"] = profile.income_t0
        else:
            flags["income"] = profile.income_t1
        flags["household_size"] = profile.household_size
        flags["employment"] = self._normalize_employment_label(profile.employment)
        
        return flags

    def _normalize_child_age_range(self, value: Any) -> tuple[int, int] | None:
        if isinstance(value, dict):
            lower = value.get("min")
            upper = value.get("max")
        elif isinstance(value, (list, tuple)) and len(value) >= 2:
            lower = value[0]
            upper = value[1]
        else:
            lower = getattr(value, "min", None)
            upper = getattr(value, "max", None)

        try:
            lower_i = int(lower) if lower is not None else None
        except (TypeError, ValueError):
            lower_i = None
        try:
            upper_i = int(upper) if upper is not None else None
        except (TypeError, ValueError):
            upper_i = None

        if lower_i is None and upper_i is None:
            return None
        if lower_i is None:
            lower_i = upper_i
        if upper_i is None:
            upper_i = lower_i
        if lower_i is None or upper_i is None:
            return None
        if lower_i > upper_i:
            lower_i, upper_i = upper_i, lower_i
        return (lower_i, upper_i)

    def _add_child_age_tags_from_range(
        self,
        tags: set[LifeEventTag],
        lower: int,
        upper: int,
    ) -> None:
        if lower <= 0 <= upper:
            tags.add(LifeEventTag.NEWBORN)
            tags.add(LifeEventTag.AGE_0_2)
        if max(lower, 1) <= min(upper, 2):
            tags.add(LifeEventTag.AGE_0_2)
        if max(lower, 3) <= min(upper, 5):
            tags.add(LifeEventTag.AGE_3_5)
            tags.add(LifeEventTag.PRESCHOOL)

    def _collect_child_age_ranges(self, flags: Dict[str, Any]) -> list[tuple[int, int]]:
        ranges: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()

        for item in flags.get("children_age_ranges") or []:
            normalized = self._normalize_child_age_range(item)
            if normalized is None:
                continue
            if normalized in seen:
                continue
            seen.add(normalized)
            ranges.append(normalized)

        for age in flags.get("children_ages") or []:
            if not isinstance(age, int):
                continue
            normalized = (age, age)
            if normalized in seen:
                continue
            seen.add(normalized)
            ranges.append(normalized)
        return ranges

    def _child_age_requirement_matches(
        self,
        eligibility: ProgramEligibility,
        flags: Dict[str, Any],
    ) -> bool | None:
        lower = eligibility.child_age_min if eligibility.child_age_min is not None else -10_000
        upper = eligibility.child_age_max if eligibility.child_age_max is not None else 10_000

        observed_ranges = self._collect_child_age_ranges(flags)
        if not observed_ranges:
            if self._is_child_consideration_enabled(flags) and self._eligibility_targets_infant(lower, upper):
                return True
            return None
        return any(max(r_low, lower) <= min(r_high, upper) for r_low, r_high in observed_ranges)

    def _is_child_consideration_enabled(self, flags: Dict[str, Any]) -> bool:
        return bool(flags.get("is_considering_children") is True)

    def _eligibility_targets_infant(self, lower: int, upper: int) -> bool:
        return max(lower, 0) <= min(upper, 1)

    def _structured_inapplicable_reason(
        self,
        eligibility: ProgramEligibility,
        flags: Dict[str, Any],
    ) -> str | None:
        if eligibility.requires_moving is True and not flags["is_moving"]:
            return "requires_moving"
        child_consideration = self._is_child_consideration_enabled(flags)

        if (
            eligibility.requires_pregnancy is True
            and flags["is_pregnant"] is False
            and not child_consideration
        ):
            return "requires_pregnancy"
        if (
            eligibility.requires_children is True
            and flags["has_children"] is False
            and not child_consideration
        ):
            return "requires_children"
        if eligibility.requires_disability_child is True and flags["has_disability_child"] is False:
            return "requires_disability_child"
        if eligibility.requires_single_parent is True and flags.get("is_single_parent") is not True:
            return "requires_single_parent"

        if eligibility.child_age_min is not None or eligibility.child_age_max is not None:
            age_match = self._child_age_requirement_matches(eligibility, flags)
            if age_match is None:
                # Missing age should not hard-block recommendation.
                return None
            if not age_match:
                return "child_age_out_of_range"
        
        child_count = flags.get("child_count")
        if (
            isinstance(child_count, int)
            and eligibility.child_count_min is not None
            and child_count < eligibility.child_count_min
        ):
            return "child_count_too_low"
        if (
            isinstance(child_count, int)
            and eligibility.child_count_max is not None
            and child_count > eligibility.child_count_max
        ):
            return "child_count_too_high"

        household_size = flags.get("household_size")
        if (
            isinstance(household_size, int)
            and eligibility.household_size_min is not None
            and household_size < eligibility.household_size_min
        ):
            return "household_size_too_low"
        if (
            isinstance(household_size, int)
            and eligibility.household_size_max is not None
            and household_size > eligibility.household_size_max
        ):
            return "household_size_too_high"

        income = flags.get("income")
        if isinstance(income, int) and eligibility.income_min is not None and income < eligibility.income_min:
            return "income_too_low"
        if isinstance(income, int) and eligibility.income_max is not None and income > eligibility.income_max:
            return "income_too_high"

        if eligibility.applicable_employment:
            current = self._normalize_employment_label(flags.get("employment"))
            if current:
                allowed = {
                    self._normalize_employment_label(v)
                    for v in eligibility.applicable_employment
                    if str(v or "").strip()
                }
                if current not in allowed:
                    return "employment_not_applicable"

        return None

    def _structured_reason_penalty(self, reason: str) -> float:
        penalties = {
            "requires_moving": 80.0,
            "requires_pregnancy": 90.0,
            "requires_children": 70.0,
            "requires_disability_child": 120.0,
            "requires_single_parent": 120.0,
            "child_age_out_of_range": 70.0,
            "child_count_too_low": 55.0,
            "child_count_too_high": 55.0,
            "household_size_too_low": 45.0,
            "household_size_too_high": 45.0,
            "income_too_low": 45.0,
            "income_too_high": 45.0,
            "employment_not_applicable": 35.0,
        }
        return penalties.get(reason, 0.0)

    def _structured_eligibility_boost(
        self,
        eligibility: ProgramEligibility,
        flags: Dict[str, Any],
    ) -> float:
        def _is_in_range(value: Any, min_value: int | None, max_value: int | None) -> bool:
            if not isinstance(value, int):
                return False
            if min_value is not None and value < min_value:
                return False
            if max_value is not None and value > max_value:
                return False
            return min_value is not None or max_value is not None

        boost = 0.0
        range_match_boost_default = 30.0
        range_match_boost_child_count = 50.0
        range_match_boost_child_age = 50.0
        if eligibility.is_mandatory is True:
            boost += 90.0

        child_consideration = self._is_child_consideration_enabled(flags)
        if eligibility.requires_moving and flags["is_moving"]:
            boost += 20.0
        if eligibility.requires_pregnancy and (flags["is_pregnant"] or child_consideration):
            boost += 20.0
        if eligibility.requires_children and (flags["has_children"] or child_consideration):
            boost += 20.0
        if eligibility.requires_disability_child and flags["has_disability_child"]:
            boost += 25.0
        if eligibility.requires_single_parent and flags.get("is_single_parent") is True:
            boost += 20.0

        child_count = flags.get("child_count")
        if _is_in_range(
            child_count,
            eligibility.child_count_min,
            eligibility.child_count_max,
        ):
            boost += range_match_boost_child_count

        household_size = flags.get("household_size")
        if _is_in_range(
            household_size,
            eligibility.household_size_min,
            eligibility.household_size_max,
        ):
            boost += range_match_boost_default

        income = flags.get("income")
        if _is_in_range(
            income,
            eligibility.income_min,
            eligibility.income_max,
        ):
            boost += range_match_boost_default

        if eligibility.child_age_min is not None or eligibility.child_age_max is not None:
            age_match = self._child_age_requirement_matches(eligibility, flags)
            if age_match is True:
                boost += range_match_boost_child_age

        return boost

    def _profile_signal_boost(self, program: Program, flags: Dict[str, Any]) -> float:
        """
        Lightly boost programs when GUI profile fields can actually be used.
        This keeps optional fields additive and avoids hard failures on missing inputs.
        """
        boost = 0.0
        eligibility = program.eligibility_profile

        income = flags.get("income")
        employment = str(flags.get("employment") or "").strip()
        couple_count = flags.get("couple_count")
        parent_count = flags.get("parent_count")

        if eligibility is not None:
            if (
                isinstance(income, int)
                and (eligibility.income_min is not None or eligibility.income_max is not None)
            ):
                boost += 10.0
            if employment and eligibility.applicable_employment:
                boost += 8.0
            if isinstance(couple_count, int) and eligibility.requires_single_parent is not None:
                boost += 6.0
            if (
                isinstance(parent_count, int)
                and (eligibility.household_size_min is not None or eligibility.household_size_max is not None)
            ):
                boost += 4.0

        # Small additive bias for benefit ranking when profile context exists.
        if self._is_benefit_kind(program):
            if isinstance(income, int):
                boost += 4.0
            if employment:
                boost += 3.0
            if isinstance(couple_count, int):
                boost += 2.0
            if isinstance(parent_count, int):
                boost += 2.0

        return boost

    def _derive_user_life_event_tags(self, flags: Dict[str, Any]) -> set[LifeEventTag]:
        """
        Build user-side life-event tags from inferred profile flags.
        """
        tags: set[LifeEventTag] = set()

        if flags.get("is_moving"):
            tags.update(
                {
                    LifeEventTag.MOVING_IN,
                    LifeEventTag.MOVING_OUT,
                    LifeEventTag.MOVING_WITHIN,
                    LifeEventTag.MYNUMBER_CHANGE,
                }
            )
        if flags.get("is_pregnant"):
            tags.update(
                {
                    LifeEventTag.PREGNANCY,
                    LifeEventTag.BIRTH,
                    LifeEventTag.NEWBORN,
                }
            )
        if flags.get("is_considering_children"):
            tags.update(
                {
                    LifeEventTag.PREGNANCY,
                    LifeEventTag.BIRTH,
                    LifeEventTag.NEWBORN,
                    LifeEventTag.AGE_0_2,
                }
            )
        if flags.get("has_children") is True:
            tags.update(
                {
                    LifeEventTag.CHILD_ALLOWANCE,
                    LifeEventTag.MEDICAL_SUBSIDY,
                    LifeEventTag.CHILDCARE_APPLICATION,
                }
            )
        if flags.get("has_disability_child") is True:
            tags.add(LifeEventTag.MEDICAL_SUBSIDY)

        for tag in flags.get("child_age_tags") or set():
            if isinstance(tag, LifeEventTag):
                tags.add(tag)
        return tags

    def _tag_match_score(self, program: Program, flags: Dict[str, Any]) -> float:
        """
        Fit component: score overlap between user-derived life-event tags and program tags.
        """
        user_tags = self._derive_user_life_event_tags(flags)
        if not user_tags:
            return 0.0
        program_tags = set(program.life_event_tags or [])
        if not program_tags:
            return 0.0
        matched = len(user_tags.intersection(program_tags))
        if matched <= 0:
            return 0.0
        return min(float(matched) * 18.0, 72.0)

    def _urgency_score(self, program: Program) -> float:
        """
        Urgency component: deadline has only a small additive effect.
        """
        deadline = getattr(program, "deadline", None)
        if deadline is None:
            return 0.0

        if deadline.type == DeadlineType.WITHIN_DAYS:
            days = deadline.value
            if isinstance(days, int):
                if days <= 14:
                    return 3.0
                if days <= 30:
                    return 2.0
                if days <= 90:
                    return 1.0
            return 0.5

        if deadline.type == DeadlineType.BY_DATE:
            return 1.5 if deadline.value else 0.5

        return 0.0

    def _is_pet_related_program(self, program: Program) -> bool:
        text = " ".join(
            str(part or "")
            for part in (
                program.title_common,
                program.title_official,
                program.summary,
                program.eligibility_text,
            )
        )
        if any(keyword in text for keyword in _PET_KEYWORDS_JA):
            return True

        lower_text = text.lower()
        if any(keyword in lower_text for keyword in _PET_KEYWORDS_EN):
            return True

        for tag in (program.life_event_tags or []):
            raw_tag = str(getattr(tag, "value", tag) or "").strip().lower()
            if not raw_tag:
                continue
            if raw_tag in _PET_TAG_HINTS:
                return True
            if any(hint in raw_tag for hint in _PET_TAG_HINTS):
                return True
        return False

    def _program_search_text(self, program: Program) -> str:
        parts: list[str] = [
            str(program.title_common or ""),
            str(program.title_official or ""),
            str(program.summary or ""),
            str(program.eligibility_text or ""),
        ]
        for step in (program.steps or []):
            parts.append(str(step or ""))
        return " ".join(parts)

    def _keyword_adjustment(self, program: Program) -> float:
        text = self._program_search_text(program)
        adjustment = 0.0

        if any(keyword in text for keyword in _NEGATIVE_KEYWORDS_JA):
            adjustment -= 50.0

        domain = str(getattr(program, "domain", "") or "").strip().lower()
        if (
            domain == "moving"
            and all(keyword in text for keyword in _MOVING_ADDRESS_CHANGE_KEYWORDS_JA)
        ):
            adjustment += 50.0

        return adjustment

    def _pet_contradiction_penalty(self, program: Program, flags: Dict[str, Any]) -> float:
        has_pet = flags.get("has_pet")
        if has_pet is True:
            return 0.0
        if not self._is_pet_related_program(program):
            return 0.0
        # final_score subtracts contradiction, so 100.0 here means -100 points.
        return 100.0

    def _eligibility_fit_score(self, program: Program, flags: Dict[str, Any]) -> float:
        eligibility = program.eligibility_profile
        if eligibility is None:
            return 0.0
        # Includes min/max checks for child_age / child_count / household_size / income.
        return self._structured_eligibility_boost(eligibility, flags)

    def _contradiction_penalty(self, program: Program, flags: Dict[str, Any]) -> float:
        penalty = 0.0
        if program.eligibility_profile is not None:
            reason = self._structured_inapplicable_reason(program.eligibility_profile, flags)
            if reason is not None:
                penalty += self._structured_reason_penalty(reason)
        penalty += self._pet_contradiction_penalty(program, flags)
        return penalty

    def _calculate_score(self, program: Program, flags: Dict[str, Any]) -> float:
        # final_score = fit + urgency + necessity + generality - contradiction - uncertainty
        fit = self._eligibility_fit_score(program, flags) + self._tag_match_score(program, flags)
        urgency = self._urgency_score(program)
        necessity = self._importance_weight(program.importance)
        generality = self._need_prevalence_boost(program)
        keyword_adjustment = self._keyword_adjustment(program)
        contradiction = self._contradiction_penalty(program, flags)
        uncertainty = 0.0

        return (
            fit
            + urgency
            + necessity
            + generality
            + keyword_adjustment
            - contradiction
            - uncertainty
        )

    def _to_card(self, program: Program, score: float) -> RecommendationCard:
        return RecommendationCard(
            id=program.canonical_key, # Use canonical key or logic ID
            title=program.title_common if program.title_common else program.title_official,
            content=f"{program.summary}\n\n対象: {program.eligibility_text}",
            steps=program.steps,
            deadline=program.deadline,
            official_urls=program.official_urls,
            contact=program.contact,
            required_info=program.required_info,
            score=score,
            tags=[t.value for t in program.life_event_tags]
        )

    async def recommend(self, municipality_id: str, category: RecommendationCategory, profile: UserProfile) -> List[RecommendationCard]:
        domains = []
        if category == RecommendationCategory.MOVING:
            domains = ["moving"]
        elif category == RecommendationCategory.BIRTH:
            domains = ["childcare"] # Mapped to childcare domain
        elif category == RecommendationCategory.EXPLORER:
            domains = ["moving", "childcare"]

        flags = self._normalize_profile(profile)

        all_programs: List[Program] = []
        retrieval_meta_by_domain: dict[str, dict[str, Any]] = {}
        for domain in domains:
            programs: list[Program] = []
            domain_meta: dict[str, Any] = {}
            get_filtered_with_meta = getattr(
                self.catalog_service,
                "get_latest_programs_for_profile_with_meta",
                None,
            )
            if callable(get_filtered_with_meta):
                try:
                    payload = await get_filtered_with_meta(
                        municipality_id,
                        domain,
                        flags,
                    )
                except Exception:
                    payload = {}
                if isinstance(payload, dict):
                    if isinstance(payload.get("programs"), list):
                        programs = payload.get("programs") or []
                    if isinstance(payload.get("meta"), dict):
                        domain_meta = payload.get("meta") or {}

            prefilter_active = bool(domain_meta.get("specs_total"))
            get_filtered = getattr(self.catalog_service, "get_latest_programs_for_profile", None)
            if not programs and not prefilter_active and callable(get_filtered):
                try:
                    programs = await get_filtered(municipality_id, domain, flags)
                except Exception:
                    programs = []
            if not programs and not prefilter_active:
                programs = await self.catalog_service.get_latest_programs(municipality_id, domain)
                domain_meta = {"stage": "full_catalog", "returned_count": len(programs)}
            else:
                if not domain_meta:
                    domain_meta = {"stage": "prefiltered", "returned_count": len(programs)}
            retrieval_meta_by_domain[domain] = domain_meta
            all_programs.extend(programs)
            
        if not all_programs:
            return []

        scored_cards: list[tuple[int, float, int, int, RecommendationCard]] = []
        dedup_by_program_id: dict[str, tuple[int, float, int, int, RecommendationCard]] = {}
        for p in all_programs:
            score = self._calculate_score(p, flags)
            importance_rank = self._importance_rank(p.importance)
            priority_bucket = self._priority_bucket(p)
            priority_group = self._priority_group(priority_bucket)
            card = self._to_card(p, score)
            item = (priority_group, score, importance_rank, priority_bucket, card)

            existing = dedup_by_program_id.get(card.id)
            if existing is None or (priority_group, score, importance_rank) > (
                existing[0],
                existing[1],
                existing[2],
            ):
                dedup_by_program_id[card.id] = item

        scored_cards = list(dedup_by_program_id.values())
        scored_cards.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)

        top5 = [
            {"id": row[4].id, "score": round(row[1], 2), "group": row[0], "bucket": row[3]}
            for row in scored_cards[:5]
        ]
        logger.info(
            "recommend_metrics municipality_id=%s category=%s total=%d stage2_final=%d retrieval_meta=%s top5=%s",
            municipality_id,
            category.value,
            len(all_programs),
            len(scored_cards),
            retrieval_meta_by_domain,
            top5,
        )

        return [item[4] for item in scored_cards]
