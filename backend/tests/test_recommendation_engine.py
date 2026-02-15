from __future__ import annotations

import asyncio
import sys
import unittest
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.models.api import RecommendationCategory, UserProfile  # noqa: E402
from app.models.program import (  # noqa: E402
    Contact,
    Deadline,
    DeadlineType,
    LifeEventTag,
    Program,
    ProgramEligibility,
    ProgramAction,
    ProgramImportance,
    ProgramKind,
    Source,
)
from app.services.recommendation import RecommendationEngine  # noqa: E402


def _build_program(
    key: str,
    title: str,
    tags: list[LifeEventTag],
    deadline_days: int,
    importance: ProgramImportance = ProgramImportance.MEDIUM,
    domain: str = "moving",
    eligibility_profile: ProgramEligibility | None = None,
    need_prevalence_score: float | None = None,
    kind: ProgramKind = ProgramKind.PROCEDURE,
) -> Program:
    return Program(
        municipality_id="tokyo-chiyoda",
        domain=domain,
        canonical_key=key,
        title_official=title,
        title_common=title,
        summary=f"{title}の概要",
        steps=["step-1", "step-2"],
        kind=kind,
        actions=[ProgramAction.APPLY],
        importance=importance,
        life_event_tags=tags,
        official_urls=["https://example.com"],
        contact=Contact(name="窓口", tel="00-0000-0000", url="https://example.com/contact"),
        deadline=Deadline(type=DeadlineType.WITHIN_DAYS, value=deadline_days),
        eligibility_text="対象要件",
        eligibility_profile=eligibility_profile,
        need_prevalence_score=need_prevalence_score,
        required_info=["本人確認書類"],
        source=Source(retrieved_at=datetime.now()),
    )


class _FakeCatalogService:
    def __init__(
        self,
        domain_programs: dict[str, list[Program]],
        filtered_domain_programs: dict[str, list[Program]] | None = None,
    ) -> None:
        self._domain_programs = domain_programs
        self._filtered_domain_programs = filtered_domain_programs
        self.last_profile_flags: dict | None = None

    async def get_latest_programs(self, municipality_id: str, domain: str) -> list[Program]:
        _ = municipality_id
        return self._domain_programs.get(domain, [])

    async def get_latest_programs_for_profile_with_meta(
        self,
        municipality_id: str,
        domain: str,
        profile_flags: dict,
    ) -> dict:
        _ = municipality_id
        self.last_profile_flags = profile_flags
        if self._filtered_domain_programs is not None:
            programs = self._filtered_domain_programs.get(domain, [])
            return {
                "programs": programs,
                "meta": {
                    "stage": "prefilter_minimal",
                    "specs_total": 1,
                    "returned_count": len(programs),
                },
            }

        programs = self._domain_programs.get(domain, [])
        has_disability_child = profile_flags.get("has_disability_child")
        is_single_parent = profile_flags.get("is_single_parent")

        specs_total = 0
        if has_disability_child is True:
            specs_total += 1
        if is_single_parent is True:
            specs_total += 1

        if specs_total == 0:
            return {
                "programs": [],
                "meta": {
                    "stage": "prefilter_minimal",
                    "specs_total": 0,
                    "returned_count": 0,
                },
            }

        filtered: list[Program] = []
        for program in programs:
            eligibility = program.eligibility_profile
            if eligibility is None:
                filtered.append(program)
                continue
            if has_disability_child is True:
                if eligibility.requires_disability_child is False:
                    continue
            if is_single_parent is True:
                if eligibility.requires_single_parent is False:
                    continue
            filtered.append(program)

        return {
            "programs": filtered,
            "meta": {
                "stage": "prefilter_minimal",
                "specs_total": specs_total,
                "returned_count": len(filtered),
            },
        }

    async def get_latest_programs_for_profile(
        self,
        municipality_id: str,
        domain: str,
        profile_flags: dict,
    ) -> list[Program]:
        _ = municipality_id
        self.last_profile_flags = profile_flags
        if self._filtered_domain_programs is None:
            programs = self._domain_programs.get(domain, [])
            has_disability_child = profile_flags.get("has_disability_child")
            is_single_parent = profile_flags.get("is_single_parent")
            filtered: list[Program] = []
            for program in programs:
                eligibility = program.eligibility_profile
                if eligibility is None:
                    filtered.append(program)
                    continue
                if has_disability_child is True:
                    if eligibility.requires_disability_child is False:
                        continue
                if is_single_parent is True:
                    if eligibility.requires_single_parent is False:
                        continue
                filtered.append(program)
            return filtered
        return self._filtered_domain_programs.get(domain, [])


class RecommendationEngineTest(unittest.TestCase):
    def test_normalize_profile_derives_flags(self) -> None:
        engine = RecommendationEngine(_FakeCatalogService({}))
        profile = UserProfile(
            moving_date="2026-02",
            children_counts=1,
            children_ages=[0, 4],
            is_pregnant=True,
        )

        flags = engine._normalize_profile(profile)

        self.assertTrue(flags["is_moving"])
        self.assertTrue(flags["has_children"])
        self.assertTrue(flags["is_pregnant"])
        self.assertIn(LifeEventTag.NEWBORN, flags["child_age_tags"])
        self.assertIn(LifeEventTag.AGE_0_2, flags["child_age_tags"])
        self.assertIn(LifeEventTag.AGE_3_5, flags["child_age_tags"])
        self.assertIn(LifeEventTag.PRESCHOOL, flags["child_age_tags"])
        self.assertEqual(flags["income"], None)
        self.assertEqual(flags["employment"], "")

    def test_normalize_profile_accepts_children_age_ranges(self) -> None:
        engine = RecommendationEngine(_FakeCatalogService({}))
        profile = UserProfile(
            children_age_ranges=[
                {"min": 6, "max": 12},
                {"min": 12, "max": 15},
                {"min": 11, "max": 11},
            ],
        )

        flags = engine._normalize_profile(profile)

        self.assertTrue(flags["has_children"])
        self.assertIn((6, 12), flags["children_age_ranges"])
        self.assertIn((12, 15), flags["children_age_ranges"])
        self.assertIn((11, 11), flags["children_age_ranges"])
        self.assertIn(11, flags["children_ages"])
        self.assertEqual(flags.get("child_count"), 1)

    def test_recommend_sorts_by_score(self) -> None:
        moving_priority = _build_program(
            key="moving-priority",
            title="転入届",
            tags=[LifeEventTag.MOVING_IN],
            deadline_days=7,
        )
        generic_program = _build_program(
            key="generic-program",
            title="一般案内",
            tags=[],
            deadline_days=60,
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [generic_program, moving_priority]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(moving_date="2026-02"),
            )
        )

        self.assertGreaterEqual(len(cards), 2)
        self.assertEqual(cards[0].id, "moving-priority")
        self.assertGreater(cards[0].score, cards[1].score)

    def test_child_age_range_matching_prefers_over_non_matching(self) -> None:
        matching = _build_program(
            key="matching-age",
            title="学童向け支援",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=30,
            domain="childcare",
            eligibility_profile=ProgramEligibility(
                requires_children=True,
                child_age_min=10,
                child_age_max=12,
            ),
        )
        non_matching = _build_program(
            key="non-matching-age",
            title="乳幼児向け支援",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=30,
            domain="childcare",
            eligibility_profile=ProgramEligibility(
                requires_children=True,
                child_age_min=0,
                child_age_max=2,
            ),
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"childcare": [non_matching, matching]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.BIRTH,
                profile=UserProfile(children_age_ranges=[{"min": 6, "max": 12}]),
            )
        )

        self.assertEqual(cards[0].id, "matching-age")
        self.assertGreater(cards[0].score, cards[1].score)

    def test_need_prevalence_score_prioritizes_common_program(self) -> None:
        high_prevalence = _build_program(
            key="high-prevalence",
            title="高頻度制度",
            tags=[],
            deadline_days=30,
            need_prevalence_score=90.0,
        )
        low_prevalence = _build_program(
            key="low-prevalence",
            title="低頻度制度",
            tags=[],
            deadline_days=30,
            need_prevalence_score=10.0,
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [low_prevalence, high_prevalence]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(moving_date="2026-02"),
            )
        )
        self.assertEqual(cards[0].id, "high-prevalence")

    def test_high_importance_program_is_prioritized(self) -> None:
        high_importance = _build_program(
            key="high-importance",
            title="重要手続き",
            tags=[],
            deadline_days=60,
            importance=ProgramImportance.HIGH,
        )
        low_importance = _build_program(
            key="low-importance",
            title="一般手続き",
            tags=[],
            deadline_days=60,
            importance=ProgramImportance.LOW,
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [low_importance, high_importance]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(),
            )
        )
        self.assertEqual(cards[0].id, "high-importance")
        self.assertGreater(cards[0].score, cards[1].score)

    def test_negative_keyword_penalty_lowers_score(self) -> None:
        negative_program = _build_program(
            key="negative-procedure",
            title="死亡手続き案内",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        neutral_program = _build_program(
            key="neutral-procedure",
            title="一般手続き案内",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [neutral_program, negative_program]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(),
            )
        )

        self.assertEqual(cards[0].id, "neutral-procedure")
        self.assertGreaterEqual(cards[0].score - cards[1].score, 45.0)

    def test_moving_address_change_keywords_boost_score(self) -> None:
        boosted_program = _build_program(
            key="moving-address-change",
            title="住所変更手続き",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        neutral_program = _build_program(
            key="moving-generic",
            title="一般手続き",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [neutral_program, boosted_program]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(),
            )
        )

        self.assertEqual(cards[0].id, "moving-address-change")
        self.assertGreaterEqual(cards[0].score - cards[1].score, 45.0)

    def test_pet_related_program_is_not_boosted_when_has_pet_true(self) -> None:
        pet_program = _build_program(
            key="pet-support",
            title="犬の登録支援",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        generic_program = _build_program(
            key="generic-support",
            title="一般支援",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [generic_program, pet_program]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(has_pet=True),
            )
        )

        by_id = {card.id: card for card in cards}
        self.assertIn("pet-support", by_id)
        self.assertIn("generic-support", by_id)
        self.assertLessEqual(by_id["pet-support"].score, by_id["generic-support"].score)

    def test_pet_related_program_is_penalized_when_has_pet_false(self) -> None:
        pet_program = _build_program(
            key="pet-support",
            title="犬の登録支援",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        generic_program = _build_program(
            key="generic-support",
            title="一般支援",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [generic_program, pet_program]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(has_pet=False),
            )
        )

        self.assertEqual(cards[0].id, "generic-support")
        self.assertGreater(cards[0].score, cards[1].score)
        self.assertGreaterEqual(cards[0].score - cards[1].score, 50.0)

    def test_pet_related_program_is_penalized_when_has_pet_unknown(self) -> None:
        pet_program = _build_program(
            key="pet-support",
            title="犬の登録支援",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        generic_program = _build_program(
            key="generic-support",
            title="一般支援",
            tags=[],
            deadline_days=30,
            domain="moving",
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [generic_program, pet_program]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(),
            )
        )

        self.assertEqual(cards[0].id, "generic-support")
        self.assertGreater(cards[0].score, cards[1].score)
        self.assertGreaterEqual(cards[0].score - cards[1].score, 90.0)

    def test_child_related_program_filtered_without_children_context(self) -> None:
        childcare_program = _build_program(
            key="child-allowance",
            title="児童手当",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=30,
            domain="childcare",
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"childcare": [childcare_program]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.BIRTH,
                profile=UserProfile(),
            )
        )
        self.assertEqual([card.id for card in cards], ["child-allowance"])

    def test_disability_related_program_is_not_hard_filtered_without_disability_flag(self) -> None:
        disability_program = _build_program(
            key="disability-child-support",
            title="障害児福祉手当",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=30,
            domain="childcare",
            eligibility_profile=ProgramEligibility(
                requires_disability_child=True,
            ),
        )
        general_program = _build_program(
            key="general-child-support",
            title="児童手当",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=30,
            domain="childcare",
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"childcare": [disability_program, general_program]})
        )

        cards_without_flag = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.BIRTH,
                profile=UserProfile(children_counts=1),
            )
        )
        ids_without_flag = [card.id for card in cards_without_flag]
        self.assertEqual(ids_without_flag[0], "general-child-support")
        self.assertIn("disability-child-support", ids_without_flag)

        cards_with_flag = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.BIRTH,
                profile=UserProfile(children_counts=1, has_disability_child=True),
            )
        )
        self.assertIn("disability-child-support", [card.id for card in cards_with_flag])

    def test_structured_eligibility_profile_filters_candidates(self) -> None:
        income_limited = _build_program(
            key="income-limited",
            title="所得制限制度",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=30,
            domain="childcare",
            eligibility_profile=ProgramEligibility(
                requires_children=True,
                income_max=4_000_000,
            ),
        )
        standard = _build_program(
            key="standard-child-support",
            title="標準制度",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=30,
            domain="childcare",
            eligibility_profile=ProgramEligibility(
                requires_children=True,
            ),
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"childcare": [income_limited, standard]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.BIRTH,
                profile=UserProfile(children_counts=1, income=6_000_000),
            )
        )
        ids = [card.id for card in cards]
        self.assertEqual(ids[0], "standard-child-support")
        self.assertIn("income-limited", ids)

    def test_structured_mandatory_boost_prioritizes_program(self) -> None:
        mandatory = _build_program(
            key="mandatory-procedure",
            title="必須手続き",
            tags=[LifeEventTag.MOVING_IN],
            deadline_days=30,
            eligibility_profile=ProgramEligibility(
                requires_moving=True,
                is_mandatory=True,
            ),
        )
        optional = _build_program(
            key="optional-support",
            title="任意支援",
            tags=[LifeEventTag.MOVING_IN],
            deadline_days=14,
            eligibility_profile=ProgramEligibility(
                requires_moving=True,
            ),
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [optional, mandatory]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(moving_date="2026-02"),
            )
        )
        self.assertEqual(cards[0].id, "mandatory-procedure")

    def test_bucket_3_and_2_are_same_priority_group_and_score_first(self) -> None:
        mandatory = _build_program(
            key="mandatory-procedure",
            title="必須手続き",
            tags=[],
            deadline_days=60,
            domain="moving",
            importance=ProgramImportance.MEDIUM,
            eligibility_profile=ProgramEligibility(is_mandatory=True),
            need_prevalence_score=0.0,
            kind=ProgramKind.PROCEDURE,
        )
        high_score_benefit = _build_program(
            key="high-score-benefit",
            title="高スコア給付",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=14,
            domain="moving",
            importance=ProgramImportance.HIGH,
            need_prevalence_score=100.0,
            kind=ProgramKind.CASH_BENEFIT,
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"moving": [mandatory, high_score_benefit]})
        )

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(moving_date="2026-02"),
            )
        )
        self.assertEqual(cards[0].id, "high-score-benefit")

    def test_structured_single_parent_and_child_count_penalty(self) -> None:
        single_parent_support = _build_program(
            key="single-parent-support",
            title="ひとり親支援",
            tags=[LifeEventTag.CHILD_ALLOWANCE],
            deadline_days=30,
            domain="childcare",
            eligibility_profile=ProgramEligibility(
                requires_children=True,
                requires_single_parent=True,
                child_count_min=2,
            ),
        )
        engine = RecommendationEngine(
            _FakeCatalogService({"childcare": [single_parent_support]})
        )

        cards_not_matching = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.BIRTH,
                profile=UserProfile(children_counts=2, couple_count=2),
            )
        )
        self.assertEqual([card.id for card in cards_not_matching], ["single-parent-support"])

        cards_matching = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.BIRTH,
                profile=UserProfile(children_counts=2, couple_count=1),
            )
        )
        self.assertEqual([card.id for card in cards_matching], ["single-parent-support"])
        self.assertGreater(cards_matching[0].score, cards_not_matching[0].score)

    def test_recommend_uses_prefiltered_catalog_api_when_available(self) -> None:
        filtered_program = _build_program(
            key="filtered-program",
            title="絞り込み候補",
            tags=[LifeEventTag.MOVING_IN],
            deadline_days=14,
            domain="moving",
        )
        fallback_program = _build_program(
            key="fallback-program",
            title="通常候補",
            tags=[LifeEventTag.MOVING_OUT],
            deadline_days=14,
            domain="moving",
        )
        fake_service = _FakeCatalogService(
            {"moving": [fallback_program]},
            filtered_domain_programs={"moving": [filtered_program]},
        )
        engine = RecommendationEngine(fake_service)

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(moving_date="2026-02"),
            )
        )

        self.assertEqual([card.id for card in cards], ["filtered-program"])
        self.assertIsNotNone(fake_service.last_profile_flags)
        self.assertTrue(fake_service.last_profile_flags.get("is_moving"))

    def test_recommend_relaxes_sparse_prefilter_result(self) -> None:
        filtered_program = _build_program(
            key="filtered-program",
            title="絞り込み候補",
            tags=[LifeEventTag.MOVING_IN],
            deadline_days=14,
            domain="moving",
        )
        full_programs = [
            _build_program(
                key="full-1",
                title="転入届",
                tags=[LifeEventTag.MOVING_IN],
                deadline_days=14,
                domain="moving",
            ),
            _build_program(
                key="full-2",
                title="転出届",
                tags=[LifeEventTag.MOVING_OUT],
                deadline_days=14,
                domain="moving",
            ),
            _build_program(
                key="full-3",
                title="住民票変更",
                tags=[LifeEventTag.MYNUMBER_CHANGE],
                deadline_days=30,
                domain="moving",
            ),
            _build_program(
                key="full-4",
                title="転校手続き",
                tags=[LifeEventTag.MOVING_WITHIN],
                deadline_days=30,
                domain="moving",
            ),
        ]
        fake_service = _FakeCatalogService(
            {"moving": full_programs},
            filtered_domain_programs={"moving": [filtered_program]},
        )
        engine = RecommendationEngine(fake_service)

        cards = asyncio.run(
            engine.recommend(
                municipality_id="tokyo-chiyoda",
                category=RecommendationCategory.MOVING,
                profile=UserProfile(moving_date="2026-02"),
            )
        )

        ids = [card.id for card in cards]
        self.assertEqual(ids, ["filtered-program"])

if __name__ == "__main__":
    unittest.main()
