from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app.services.adk_assistant as adk_assistant_module  # noqa: E402
from app.services.adk_assistant import (  # noqa: E402
    AdkAssistantService,
    _assign_display_numbers,
    _build_initial_ask_goal_message,
    _build_search_municipality_ids,
    _extract_agent_structured_signals,
    _expand_municipality_id_prefixes,
    _normalize_structured_extraction_payload,
    _normalize_gui_profile,
    _rerank_cards_for_presentation,
    _select_primary_municipality_id,
    _split_municipality_units,
)


class _DummyEvent:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def model_dump(self, **_: Any) -> dict[str, Any]:
        return self._payload


class AdkAssistantHelpersTest(unittest.TestCase):
    def _build_service_for_chat_gate(self) -> AdkAssistantService:
        service = AdkAssistantService.__new__(AdkAssistantService)
        service._default_user_id = "test-user"
        service._conversation_cache = {}
        service._runner = object()
        service._municipality_service = None
        return service

    def test_split_municipality_units(self) -> None:
        self.assertEqual(_split_municipality_units("東京都千代田区"), ["千代田区"])
        self.assertEqual(_split_municipality_units("埼玉県さいたま市"), ["さいたま市"])
        self.assertEqual(_split_municipality_units("千代田区"), ["千代田区"])
        self.assertEqual(_split_municipality_units("東京都"), ["東京都"])

    def test_expand_municipality_id_prefixes(self) -> None:
        self.assertEqual(
            _expand_municipality_id_prefixes("tokyo-chiyoda"),
            ["tokyo", "tokyo-chiyoda"],
        )
        self.assertEqual(
            _expand_municipality_id_prefixes("saitama-saitama-omiya"),
            ["saitama", "saitama-saitama", "saitama-saitama-omiya"],
        )
        self.assertEqual(_expand_municipality_id_prefixes("invalid"), ["invalid"])

    def test_select_primary_municipality_id(self) -> None:
        self.assertEqual(
            _select_primary_municipality_id(["tokyo", "tokyo-chiyoda"]),
            "tokyo-chiyoda",
        )
        self.assertEqual(
            _select_primary_municipality_id(["saitama", "saitama-saitama", "saitama-saitama-omiya"]),
            "saitama-saitama-omiya",
        )

    def test_build_search_municipality_ids(self) -> None:
        self.assertEqual(
            _build_search_municipality_ids("tokyo-chiyoda"),
            ["tokyo", "tokyo-chiyoda"],
        )
        self.assertEqual(
            _build_search_municipality_ids("tokyo"),
            ["tokyo"],
        )

    def test_resolve_municipality_ids_text_prefers_specific_only(self) -> None:
        service = AdkAssistantService.__new__(AdkAssistantService)
        service._municipality_service = None

        chiyoda_full = asyncio.run(
            AdkAssistantService._resolve_municipality_ids(service, "東京都千代田区")
        )
        chiyoda_short = asyncio.run(
            AdkAssistantService._resolve_municipality_ids(service, "千代田区")
        )
        tokyo_only = asyncio.run(
            AdkAssistantService._resolve_municipality_ids(service, "東京都")
        )

        self.assertEqual(chiyoda_full, ["tokyo-chiyoda"])
        self.assertEqual(chiyoda_short, ["tokyo-chiyoda"])
        self.assertEqual(tokyo_only, ["tokyo"])

    def test_resolve_municipality_ids_hyphen_input_expands_prefixes(self) -> None:
        service = AdkAssistantService.__new__(AdkAssistantService)
        service._municipality_service = None

        resolved = asyncio.run(
            AdkAssistantService._resolve_municipality_ids(service, "tokyo-chiyoda")
        )
        self.assertEqual(resolved, ["tokyo", "tokyo-chiyoda"])

    def test_chat_initial_turn_returns_ask_goal_without_search(self) -> None:
        service = self._build_service_for_chat_gate()
        result = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain="moving",
                profile={},
                user_message="",
            )
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("next_action"), "ask_goal")
        self.assertEqual(result.get("cards"), [])
        self.assertEqual(result.get("events_count"), 0)

    def test_chat_first_user_turn_with_only_municipality_asks_topic(self) -> None:
        service = self._build_service_for_chat_gate()
        first = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain="moving",
                profile={},
                user_message="",
                session_id="sess-topic",
            )
        )
        second = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain="moving",
                profile={},
                user_message="tokyo-chiyodaです",
                session_id=str(first.get("session_id") or "sess-topic"),
            )
        )
        self.assertEqual(second.get("next_action"), "present_list")
        self.assertIn("入力情報を修正・追加", str(second.get("assistant_text") or ""))

    def test_chat_does_not_search_until_municipality_is_confirmed(self) -> None:
        service = self._build_service_for_chat_gate()

        def _raise_if_called(*_: Any, **__: Any) -> list[dict[str, Any]]:
            raise AssertionError("search worker must not run without municipality")

        service._fallback_recommend_cards = _raise_if_called  # type: ignore[method-assign]
        result = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="",
                domain="",
                profile={},
                user_message="制度を知りたい",
                session_id="sess-no-muni",
            )
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("next_action"), "ask_goal")
        self.assertEqual(result.get("events_count"), 0)

    def test_chat_accepts_low_confidence_intake_municipality_when_id_resolvable(self) -> None:
        service = self._build_service_for_chat_gate()

        async def _fake_intake(
            *,
            user_id: str,
            session_id: str,
            user_message: str,
            base_profile: dict[str, Any],
        ) -> dict[str, Any]:
            _ = user_id, session_id, user_message, base_profile
            return {
                "municipality_text": "千代田区",
                "municipality_confidence": 0.2,
                "domain": "",
                "domain_confidence": 0.0,
                "profile": {},
                "profile_confidence": 0.0,
                "intent": "list",
            }

        service._run_intake_extraction = _fake_intake  # type: ignore[method-assign]
        result = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="",
                domain="",
                profile={},
                user_message="千代田区",
                session_id="sess-low-conf-muni",
            )
        )
        self.assertTrue(result.get("success"))
        self.assertEqual(result.get("next_action"), "ask_more_profile")

    def test_chat_allows_post_municipality_follow_up_only_once(self) -> None:
        service = self._build_service_for_chat_gate()
        first = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain=None,
                profile={},
                user_message="",
                session_id="sess-once",
            )
        )
        second = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain=None,
                profile={},
                user_message="tokyo-chiyodaです",
                session_id=str(first.get("session_id") or "sess-once"),
            )
        )
        third = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain=None,
                profile={},
                user_message="tokyo-chiyodaです",
                session_id=str(first.get("session_id") or "sess-once"),
            )
        )
        self.assertEqual(second.get("next_action"), "ask_more_profile")
        self.assertEqual(third.get("next_action"), "present_list")

    def test_chat_keeps_municipality_across_turns_with_same_session_id(self) -> None:
        service = self._build_service_for_chat_gate()

        async def _fake_intake(
            *,
            user_id: str,
            session_id: str,
            user_message: str,
            base_profile: dict[str, Any],
        ) -> dict[str, Any]:
            _ = user_id, session_id, base_profile
            if "板橋区" in user_message:
                return {
                    "intent": "list",
                    "municipality_text": "板橋区",
                    "municipality_confidence": 0.95,
                    "domain": "",
                    "domain_confidence": 0.0,
                    "profile": {},
                    "profile_confidence": 0.0,
                }
            return {
                "intent": "list",
                "municipality_text": "",
                "municipality_confidence": 0.0,
                "domain": "moving",
                "domain_confidence": 0.95,
                "profile": {},
                "profile_confidence": 0.0,
            }

        service._run_intake_extraction = _fake_intake  # type: ignore[method-assign]
        first = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="",
                domain="",
                profile={},
                user_message="板橋区",
                session_id="sess-itabashi-keep",
            )
        )
        second = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="",
                domain="",
                profile={},
                user_message="引っ越し関連手続きを教えて",
                session_id="sess-itabashi-keep",
            )
        )

        self.assertEqual(first.get("next_action"), "ask_more_profile")
        self.assertEqual(second.get("next_action"), "present_list")
        state = service._conversation_cache["sess-itabashi-keep"]
        self.assertEqual(state.get("last_municipality"), "板橋区")
        self.assertEqual(state.get("last_municipality_id"), "tokyo-itabashi")

    def test_chat_loses_municipality_when_session_id_changes(self) -> None:
        service = self._build_service_for_chat_gate()

        async def _fake_intake(
            *,
            user_id: str,
            session_id: str,
            user_message: str,
            base_profile: dict[str, Any],
        ) -> dict[str, Any]:
            _ = user_id, session_id, base_profile
            if "板橋区" in user_message:
                return {
                    "intent": "list",
                    "municipality_text": "板橋区",
                    "municipality_confidence": 0.95,
                    "domain": "",
                    "domain_confidence": 0.0,
                    "profile": {},
                    "profile_confidence": 0.0,
                }
            return {
                "intent": "list",
                "municipality_text": "",
                "municipality_confidence": 0.0,
                "domain": "moving",
                "domain_confidence": 0.95,
                "profile": {},
                "profile_confidence": 0.0,
            }

        service._run_intake_extraction = _fake_intake  # type: ignore[method-assign]
        _ = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="",
                domain="",
                profile={},
                user_message="板橋区",
                session_id="sess-itabashi-a",
            )
        )
        second = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="",
                domain="",
                profile={},
                user_message="引っ越し関連手続きを教えて",
                session_id="sess-itabashi-b",
            )
        )

        self.assertEqual(second.get("next_action"), "ask_goal")
        self.assertEqual(
            service._conversation_cache["sess-itabashi-a"].get("last_municipality"),
            "板橋区",
        )
        self.assertEqual(
            service._conversation_cache["sess-itabashi-b"].get("last_municipality"),
            "",
        )

    def test_chat_uses_explorer_when_domain_unspecified(self) -> None:
        service = self._build_service_for_chat_gate()
        captured_domains: list[str] = []

        def _fake_search(
            municipality_ids: list[str],
            domain: str,
            profile: dict[str, Any],
            broaden: bool = False,
        ) -> list[dict[str, Any]]:
            _ = municipality_ids, profile, broaden
            captured_domains.append(domain)
            return [
                {"id": "p1", "title": "制度A", "content": "概要", "score": 1.0, "deadline": {"type": "none"}}
            ]

        service._fallback_recommend_cards = _fake_search  # type: ignore[method-assign]
        result = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain=None,
                profile={"household_size": 3},
                user_message="お願いします",
                session_id="sess-explorer",
            )
        )
        self.assertEqual(result.get("next_action"), "present_list")
        self.assertIn("explorer", captured_domains)

    def test_chat_uses_intake_signals_for_domain_and_profile(self) -> None:
        service = self._build_service_for_chat_gate()
        captured_domains: list[str] = []
        captured_profiles: list[dict[str, Any]] = []

        async def _fake_intake(
            *,
            user_id: str,
            session_id: str,
            user_message: str,
            base_profile: dict[str, Any],
        ) -> dict[str, Any]:
            _ = user_id, session_id, user_message, base_profile
            return {
                "municipality_text": "",
                "domain": "moving",
                "domain_confidence": 0.95,
                "profile": {"children_counts": 2, "household_size": 4},
                "profile_confidence": 0.9,
            }

        def _fake_search(
            municipality_ids: list[str],
            domain: str,
            profile: dict[str, Any],
            broaden: bool = False,
        ) -> list[dict[str, Any]]:
            _ = municipality_ids, broaden
            captured_domains.append(domain)
            captured_profiles.append(dict(profile))
            return [
                {"id": "p1", "title": "制度A", "content": "概要", "score": 1.0, "deadline": {"type": "none"}}
            ]

        service._run_intake_extraction = _fake_intake  # type: ignore[method-assign]
        service._fallback_recommend_cards = _fake_search  # type: ignore[method-assign]

        result = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain=None,
                profile={},
                user_message="制度を教えて",
                session_id="sess-intake-signals",
            )
        )

        self.assertEqual(result.get("next_action"), "present_list")
        self.assertIn("moving", captured_domains)
        self.assertTrue(captured_profiles)
        self.assertEqual(captured_profiles[0].get("children_counts"), 2)
        self.assertEqual(captured_profiles[0].get("household_size"), 4)

    def test_chat_more_request_returns_next_page_from_cached_ranked_cards(self) -> None:
        service = self._build_service_for_chat_gate()

        async def _fake_intake(
            *,
            user_id: str,
            session_id: str,
            user_message: str,
            base_profile: dict[str, Any],
        ) -> dict[str, Any]:
            _ = user_id, session_id, base_profile
            intent = "more" if "次の5件" in user_message else "list"
            return {
                "municipality_text": "",
                "domain": "",
                "intent": intent,
                "profile": {},
                "municipality_confidence": 0.0,
                "domain_confidence": 0.0,
                "profile_confidence": 0.0,
            }

        def _fake_search(
            municipality_ids: list[str],
            domain: str,
            profile: dict[str, Any],
            broaden: bool = False,
        ) -> list[dict[str, Any]]:
            _ = municipality_ids, domain, profile, broaden
            cards: list[dict[str, Any]] = []
            for index in range(12):
                cards.append(
                    {
                        "id": f"p{index + 1}",
                        "title": f"制度{index + 1}",
                        "content": f"概要{index + 1}",
                        "score": float(12 - index),
                        "deadline": {"type": "none"},
                    }
                )
            return cards

        service._run_intake_extraction = _fake_intake  # type: ignore[method-assign]
        service._fallback_recommend_cards = _fake_search  # type: ignore[method-assign]

        first = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain="moving",
                profile={},
                user_message="引越し制度を教えてください",
                session_id="sess-more",
            )
        )
        second = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain="moving",
                profile={},
                user_message="次の5件",
                session_id="sess-more",
            )
        )
        third = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain="moving",
                profile={},
                user_message="次の5件",
                session_id="sess-more",
            )
        )

        first_ids = [str(card.get("id") or "") for card in (first.get("cards") or [])]
        second_ids = [str(card.get("id") or "") for card in (second.get("cards") or [])]
        third_ids = [str(card.get("id") or "") for card in (third.get("cards") or [])]

        self.assertEqual(len(first_ids), 5)
        self.assertEqual(len(second_ids), 5)
        self.assertEqual(len(third_ids), 2)
        self.assertEqual(set(first_ids).intersection(second_ids), set())
        self.assertEqual(set(first_ids).intersection(third_ids), set())
        self.assertEqual(set(second_ids).intersection(third_ids), set())

    def test_chat_request_more_flag_returns_next_page_even_if_intake_intent_is_list(self) -> None:
        service = self._build_service_for_chat_gate()

        async def _fake_intake(
            *,
            user_id: str,
            session_id: str,
            user_message: str,
            base_profile: dict[str, Any],
        ) -> dict[str, Any]:
            _ = user_id, session_id, user_message, base_profile
            return {
                "municipality_text": "",
                "domain": "",
                "intent": "list",
                "profile": {},
                "municipality_confidence": 0.0,
                "domain_confidence": 0.0,
                "profile_confidence": 0.0,
            }

        def _fake_search(
            municipality_ids: list[str],
            domain: str,
            profile: dict[str, Any],
            broaden: bool = False,
        ) -> list[dict[str, Any]]:
            _ = municipality_ids, domain, profile, broaden
            cards: list[dict[str, Any]] = []
            for index in range(12):
                cards.append(
                    {
                        "id": f"p{index + 1}",
                        "title": f"制度{index + 1}",
                        "content": f"概要{index + 1}",
                        "score": float(12 - index),
                        "deadline": {"type": "none"},
                    }
                )
            return cards

        service._run_intake_extraction = _fake_intake  # type: ignore[method-assign]
        service._fallback_recommend_cards = _fake_search  # type: ignore[method-assign]

        first = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain="moving",
                profile={},
                user_message="引越し制度を教えてください",
                session_id="sess-more-flag",
            )
        )
        second = asyncio.run(
            AdkAssistantService.chat(
                service,
                municipality="tokyo-chiyoda",
                domain="moving",
                profile={},
                user_message="次の5件",
                session_id="sess-more-flag",
                request_more=True,
            )
        )

        first_ids = [str(card.get("id") or "") for card in (first.get("cards") or [])]
        second_ids = [str(card.get("id") or "") for card in (second.get("cards") or [])]
        self.assertEqual(len(first_ids), 5)
        self.assertEqual(len(second_ids), 5)
        self.assertEqual(set(first_ids).intersection(second_ids), set())

    def test_assign_display_numbers_is_sequential(self) -> None:
        state = {"next_display_no": 1, "numbered_cards": {}}
        first = _assign_display_numbers(
            [{"title": "A"}, {"title": "B"}],
            state,
        )
        second = _assign_display_numbers(
            [{"title": "C"}],
            state,
        )
        self.assertEqual([card["display_no"] for card in first], [1, 2])
        self.assertEqual([card["display_no"] for card in second], [3])

    def test_rerank_only_deduplicates_without_reordering_non_ties(self) -> None:
        cards = [
            {
                "id": "p1",
                "title": "制度A",
                "score": 120.0,
                "deadline": {"type": "within_days", "value": 90},
            },
            {
                "id": "p2",
                "title": "制度B",
                "score": 110.0,
                "deadline": {"type": "within_days", "value": 14},
            },
            {
                "id": "p1",
                "title": "制度A(重複)",
                "score": 130.0,
                "deadline": {"type": "within_days", "value": 7},
            },
        ]

        ranked = _rerank_cards_for_presentation(
            cards,
            user_message="",
            domain="explorer",
            profile={},
        )

        self.assertEqual([card.get("id") for card in ranked], ["p1", "p2"])
        self.assertFalse(any("rerank_score" in card for card in ranked))

    def test_rerank_tie_breaks_by_deadline_then_title(self) -> None:
        cards = [
            {
                "id": "t2",
                "title": "制度B",
                "score": 80.0,
                "deadline": {"type": "within_days", "value": 30},
            },
            {
                "id": "t1",
                "title": "制度A",
                "score": 80.0,
                "deadline": {"type": "within_days", "value": 14},
            },
            {
                "id": "x1",
                "title": "制度X",
                "score": 70.0,
                "deadline": {"type": "within_days", "value": 7},
            },
        ]

        ranked = _rerank_cards_for_presentation(
            cards,
            user_message="",
            domain="explorer",
            profile={},
        )

        self.assertEqual([card.get("id") for card in ranked], ["t1", "t2", "x1"])

    def test_fallback_recommend_cards_merges_and_sorts_globally_by_score(self) -> None:
        service = self._build_service_for_chat_gate()
        original_recommend_programs = adk_assistant_module.recommend_programs

        def _fake_recommend_programs(
            municipality_id: str,
            category: str,
            profile_json: str = "{}",
        ) -> dict[str, Any]:
            _ = category, profile_json
            if municipality_id == "tokyo":
                return {
                    "cards": [
                        {"id": "tokyo-1", "title": "東京都制度1", "score": 80.0},
                        {"id": "shared-1", "title": "共通制度", "score": 60.0},
                    ]
                }
            if municipality_id == "tokyo-itabashi":
                return {
                    "cards": [
                        {"id": "itabashi-1", "title": "板橋区制度1", "score": 95.0},
                        {"id": "shared-1", "title": "共通制度", "score": 90.0},
                    ]
                }
            return {"cards": []}

        adk_assistant_module.recommend_programs = _fake_recommend_programs
        try:
            cards = AdkAssistantService._fallback_recommend_cards(
                service,
                municipality_ids=["tokyo", "tokyo-itabashi"],
                domain="moving",
                profile={},
                broaden=False,
            )
        finally:
            adk_assistant_module.recommend_programs = original_recommend_programs

        self.assertEqual([str(card.get("id") or "") for card in cards], ["itabashi-1", "shared-1", "tokyo-1"])
        shared = next(card for card in cards if str(card.get("id") or "") == "shared-1")
        self.assertEqual(shared.get("score"), 90.0)

    def test_normalize_gui_profile_keeps_optional_fields_and_derives_core_values(self) -> None:
        profile = _normalize_gui_profile(
            {
                "couple_count": "2",
                "child_count": "1",
                "parent_count": "0",
                "pregnancy": "半年以内に出産予定",
                "moving": "1年以内",
                "employment": "就業中",
                "income_t0": "5000000",
                "income_t1": "5500000",
                "child_age_1": "4",
                "has_pet": "1",
            }
        )

        self.assertEqual(profile.get("couple_count"), 2)
        self.assertEqual(profile.get("child_count"), 1)
        self.assertEqual(profile.get("parent_count"), 0)
        self.assertEqual(profile.get("children_counts"), 1)
        self.assertEqual(profile.get("household_size"), 3)
        self.assertEqual(profile.get("child_age_1"), 4)
        self.assertEqual(profile.get("children_ages"), [4])
        self.assertTrue(profile.get("is_pregnant"))
        self.assertEqual(profile.get("moving_date"), "1年以内")
        self.assertEqual(profile.get("income"), 5_000_000)
        self.assertEqual(profile.get("income_t1"), 5_500_000)
        self.assertIn("has_disability_child", profile)
        self.assertIsNone(profile.get("has_disability_child"))
        self.assertIn("has_pet", profile)
        self.assertTrue(profile.get("has_pet"))

    def test_normalize_gui_profile_does_not_infer_from_child_age_text(self) -> None:
        profile = _normalize_gui_profile(
            {
                "children_ages": ["小学生", "11歳の小学生", "11歳", "小学校のこども", "中学生"],
                "children_age_ranges": ["小学生", "中学生"],
            }
        )

        self.assertIsNone(profile.get("children_ages"))
        self.assertIsNone(profile.get("children_age_ranges"))

    def test_normalize_structured_extraction_payload(self) -> None:
        payload = _normalize_structured_extraction_payload(
            {
                "municipality": "千代田区",
                "category": "moving",
                "profile": {"household_size": 4, "income_t1": "6000000", "has_pet": "0"},
                "confidence": {
                    "municipality": 0.92,
                    "domain": 0.88,
                    "profile": 0.66,
                    "overall": 0.8,
                },
            }
        )
        self.assertEqual(payload.get("municipality_text"), "千代田区")
        self.assertEqual(payload.get("domain"), "moving")
        self.assertEqual(payload.get("municipality_confidence"), 0.92)
        self.assertEqual(payload.get("domain_confidence"), 0.88)
        self.assertEqual(payload.get("profile_confidence"), 0.66)
        profile = payload.get("profile") or {}
        self.assertEqual(profile.get("household_size"), 4)
        self.assertEqual(profile.get("income_t1"), 6_000_000)
        self.assertFalse(profile.get("has_pet"))

    def test_normalize_structured_extraction_payload_without_confidence_uses_defaults(self) -> None:
        payload = _normalize_structured_extraction_payload(
            {
                "municipality_text": "板橋区",
                "domain": "moving",
                "profile": {"children_counts": 1},
            }
        )
        self.assertEqual(payload.get("municipality_text"), "板橋区")
        self.assertEqual(payload.get("domain"), "moving")
        self.assertGreaterEqual(float(payload.get("municipality_confidence") or 0.0), 0.65)
        self.assertGreaterEqual(float(payload.get("domain_confidence") or 0.0), 0.6)
        self.assertGreaterEqual(float(payload.get("profile_confidence") or 0.0), 0.55)

    def test_normalize_structured_extraction_payload_zero_confidence_uses_defaults(self) -> None:
        payload = _normalize_structured_extraction_payload(
            {
                "municipality_text": "千代田区",
                "domain": "moving",
                "profile": {"children_counts": 1},
                "confidence": {
                    "municipality": 0.0,
                    "domain": 0.0,
                    "profile": 0.0,
                    "overall": 0.0,
                },
            }
        )
        self.assertEqual(payload.get("municipality_text"), "千代田区")
        self.assertEqual(payload.get("domain"), "moving")
        self.assertGreaterEqual(float(payload.get("municipality_confidence") or 0.0), 0.65)
        self.assertGreaterEqual(float(payload.get("domain_confidence") or 0.0), 0.6)
        self.assertGreaterEqual(float(payload.get("profile_confidence") or 0.0), 0.55)

    def test_extract_agent_structured_signals_from_state_delta(self) -> None:
        events = [
            _DummyEvent(
                {
                    "actions": {
                        "state_delta": {
                            "app:intake_structured_signals": {
                                "municipality_text": "千代田区",
                                "domain": "moving",
                                "profile": {"children_counts": 1},
                                "confidence": {
                                    "municipality": 0.9,
                                    "domain": 0.95,
                                    "profile": 0.7,
                                },
                            }
                        }
                    }
                }
            )
        ]

        signals = _extract_agent_structured_signals(events)
        self.assertEqual(signals.get("municipality_text"), "千代田区")
        self.assertEqual(signals.get("domain"), "moving")
        self.assertGreaterEqual(float(signals.get("domain_confidence") or 0.0), 0.9)
        profile = signals.get("profile") or {}
        self.assertEqual(profile.get("children_counts"), 1)

    def test_extract_agent_structured_signals_fallbacks_to_content_json(self) -> None:
        class _ContentPart:
            def __init__(self, text: str) -> None:
                self.text = text

        class _Content:
            def __init__(self, role: str, parts: list[Any]) -> None:
                self.role = role
                self.parts = parts

        class _EventWithContent:
            def __init__(self, content: Any) -> None:
                self.content = content

        events = [
            _EventWithContent(
                _Content(
                    "model",
                    [
                        _ContentPart(
                            '{"municipality_text":"千代田区","domain":"moving","profile":{"children_counts":1}}'
                        )
                    ],
                )
            )
        ]

        signals = _extract_agent_structured_signals(events)
        self.assertEqual(signals.get("municipality_text"), "千代田区")
        self.assertEqual(signals.get("domain"), "moving")
        self.assertGreaterEqual(float(signals.get("municipality_confidence") or 0.0), 0.65)
        profile = signals.get("profile") or {}
        self.assertEqual(profile.get("children_counts"), 1)

    def test_extract_agent_structured_signals_fallbacks_to_model_dump_content_json(self) -> None:
        events = [
            _DummyEvent(
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "text": (
                                    '{"municipality_text":"千代田区","domain":"moving",'
                                    '"profile":{"children_counts":1}}'
                                )
                            }
                        ],
                    }
                }
            )
        ]

        signals = _extract_agent_structured_signals(events)
        self.assertEqual(signals.get("municipality_text"), "千代田区")
        self.assertEqual(signals.get("domain"), "moving")
        profile = signals.get("profile") or {}
        self.assertEqual(profile.get("children_counts"), 1)

    def test_build_initial_ask_goal_message_with_known_municipality(self) -> None:
        message = _build_initial_ask_goal_message("東京都千代田区")
        self.assertIn("東京都千代田区", message)
        self.assertIn("どのような制度や手続きをお探し", message)

if __name__ == "__main__":
    unittest.main()
