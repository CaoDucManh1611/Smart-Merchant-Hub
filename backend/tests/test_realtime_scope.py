import asyncio
import json
import unittest

from app.services.realtime import ConnectionManager


class FakeWebSocket:
    def __init__(self):
        self.accepted = False
        self.messages: list[dict] = []

    async def accept(self):
        self.accepted = True

    async def send_text(self, payload: str):
        self.messages.append(json.loads(payload))


class RealtimeScopeTests(unittest.TestCase):
    def test_shop_broadcast_reaches_only_sessions_from_that_shop(self):
        async def scenario():
            manager = ConnectionManager()
            first_staff = FakeWebSocket()
            second_staff = FakeWebSocket()
            other_shop_staff = FakeWebSocket()
            await manager.connect(first_staff, business_id=10, user_id=101)
            await manager.connect(second_staff, business_id=10, user_id=102)
            await manager.connect(other_shop_staff, business_id=20, user_id=201)

            await manager.broadcast({"type": "message_created"}, business_id=10)
            return first_staff, second_staff, other_shop_staff

        first_staff, second_staff, other_shop_staff = asyncio.run(scenario())
        self.assertTrue(first_staff.accepted)
        self.assertEqual([{"type": "message_created"}], first_staff.messages)
        self.assertEqual([{"type": "message_created"}], second_staff.messages)
        self.assertEqual([], other_shop_staff.messages)

    def test_targeted_broadcast_reaches_only_the_assigned_staff_member(self):
        async def scenario():
            manager = ConnectionManager()
            assignee = FakeWebSocket()
            colleague = FakeWebSocket()
            await manager.connect(assignee, business_id=10, user_id=101)
            await manager.connect(colleague, business_id=10, user_id=102)

            await manager.broadcast({"type": "assignment_changed"}, business_id=10, user_ids={101})
            return assignee, colleague

        assignee, colleague = asyncio.run(scenario())
        self.assertEqual([{"type": "assignment_changed"}], assignee.messages)
        self.assertEqual([], colleague.messages)

    def test_staff_presence_uses_authenticated_crm_connection(self):
        async def scenario():
            manager = ConnectionManager()
            assignee = FakeWebSocket()
            await manager.connect(assignee, business_id=10, user_id=101)
            online_before_disconnect = manager.is_user_connected(business_id=10, user_id=101)
            manager.disconnect(assignee)
            online_after_disconnect = manager.is_user_connected(business_id=10, user_id=101)
            return online_before_disconnect, online_after_disconnect

        online_before_disconnect, online_after_disconnect = asyncio.run(scenario())
        self.assertTrue(online_before_disconnect)
        self.assertFalse(online_after_disconnect)

