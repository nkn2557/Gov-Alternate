from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.v1.endpoints.assistant import chat_with_assistant  # noqa: E402
from app.models.api import AssistantChatRequest  # noqa: E402


class _StubAssistantService:
    async def chat(
        self,
        municipality: str,
        domain: str,
        profile: Optional[dict[str, Any]] = None,
        user_message: Optional[str] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        expect_tool_result: bool = False,
        request_more: bool = False,
    ) -> dict[str, Any]:
        _ = municipality, domain, profile, user_id, expect_tool_result
        sid = session_id or "session-test"
        message = (user_message or "").strip()

        if not message:
            return {
                "success": True,
                "session_id": sid,
                "assistant_text": "まず、今いちばん知りたい制度や手続きを教えてください。",
                "cards": [],
                "next_action": "ask_goal",
                "follow_up_questions": [],
                "events_count": 0,
            }

        if request_more or "他にも" in message or "もっと" in message or "次の5件" in message:
            return {
                "success": True,
                "session_id": sid,
                "assistant_text": "追加候補です。",
                "cards": [{"id": "p2", "title": "住民票の写し", "content": "追加候補"}],
                "next_action": "present_list",
                "follow_up_questions": [],
                "events_count": 1,
            }

        if "詳しく" in message:
            return {
                "success": True,
                "session_id": sid,
                "assistant_text": "制度詳細です。",
                "cards": [
                    {
                        "id": "p1",
                        "title": "児童手当",
                        "content": "制度詳細",
                        "official_urls": ["https://example.com/program"],
                    }
                ],
                "next_action": "present_list",
                "follow_up_questions": [],
                "events_count": 1,
            }

        if "違" in message or "当てはまら" in message:
            return {
                "success": True,
                "session_id": sid,
                "assistant_text": "条件を追加で教えてください。",
                "cards": [],
                "next_action": "ask_more_profile",
                "follow_up_questions": [
                    "世帯人数を教えてください。",
                    "お子さまの年齢を教えてください。",
                ],
                "events_count": 1,
            }

        return {
            "success": True,
            "session_id": sid,
            "assistant_text": "候補制度です。",
            "cards": [{"id": "p1", "title": "転入届", "content": "制度概要"}],
            "next_action": "present_list",
            "follow_up_questions": [],
            "events_count": 1,
        }


class AssistantEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def test_accepts_missing_municipality_and_domain(self) -> None:
        response = await chat_with_assistant(
            request=AssistantChatRequest(
                profile={},
                user_message="引越しの制度を知りたいです",
            ),
            service=_StubAssistantService(),
        )
        self.assertTrue(response.success)
        self.assertEqual(response.next_action, "present_list")

    async def test_initial_turn(self) -> None:
        request = AssistantChatRequest(
            municipality="千代田区",
            domain="moving",
            profile={},
            user_message="",
        )
        response = await chat_with_assistant(request=request, service=_StubAssistantService())

        self.assertTrue(response.success)
        self.assertEqual(response.next_action, "ask_goal")
        self.assertEqual(response.cards, [])

    async def test_present_list_and_more_request(self) -> None:
        service = _StubAssistantService()
        list_response = await chat_with_assistant(
            request=AssistantChatRequest(
                session_id="sess-1",
                municipality="千代田区",
                domain="moving",
                profile={},
                user_message="引越しで使える制度を教えてください。",
            ),
            service=service,
        )
        self.assertEqual(list_response.next_action, "present_list")
        self.assertGreaterEqual(len(list_response.cards), 1)

        more_response = await chat_with_assistant(
            request=AssistantChatRequest(
                session_id="sess-1",
                municipality="千代田区",
                domain="moving",
                profile={},
                user_message="他にもありますか？",
            ),
            service=service,
        )
        self.assertEqual(more_response.session_id, "sess-1")
        self.assertEqual(more_response.next_action, "present_list")
        self.assertGreaterEqual(len(more_response.cards), 1)

    async def test_detail_query_and_mismatch(self) -> None:
        service = _StubAssistantService()
        detail_response = await chat_with_assistant(
            request=AssistantChatRequest(
                session_id="sess-2",
                municipality="千代田区",
                domain="childcare",
                profile={},
                user_message="1番を詳しく",
            ),
            service=service,
        )
        self.assertEqual(detail_response.next_action, "present_list")
        self.assertEqual(len(detail_response.cards), 1)

        mismatch_response = await chat_with_assistant(
            request=AssistantChatRequest(
                session_id="sess-2",
                municipality="千代田区",
                domain="childcare",
                profile={},
                user_message="当てはまらないです",
            ),
            service=service,
        )
        self.assertEqual(mismatch_response.next_action, "ask_more_profile")
        self.assertGreaterEqual(len(mismatch_response.follow_up_questions), 1)


if __name__ == "__main__":
    unittest.main()
