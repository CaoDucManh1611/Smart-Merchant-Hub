import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database.bases import TenantBase
from app.models import Business, Conversation, Customer, Message, CrmJob, CustomerFact, CustomerProductInteraction, RecommendationRequest
from app.models.customer_collection import CustomerConsent
from app.models.experimentation import BanditDecision, Experiment
from app.services.conversation_turn_service import dispatch_chatbot_turn, schedule_chatbot_turn
from app.services.customer_collection_flow import CollectionFlowResult
from app.services.customer_fact_extractor import dispatch_customer_fact_extraction
from app.services.recommendation_service import _preferred_color
from app.services.privacy_service import stop_customer_personalization


class ConversationTurnTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Business.metadata.create_all(self.engine)
        TenantBase.metadata.create_all(self.engine)
        with Session(self.engine) as db:
            one = Business(name="Turn shop A", slug="turn-shop-a")
            two = Business(name="Turn shop B", slug="turn-shop-b")
            db.add_all([one, two])
            db.flush()
            customer = Customer(business_id=one.id, channel="shopee", external_user_id="turn-customer")
            db.add(customer)
            db.flush()
            conversation = Conversation(business_id=one.id, customer_id=customer.id, channel="shopee")
            db.add(conversation)
            db.flush()
            self.business_id, self.other_id, self.conversation_id, self.customer_id = one.id, two.id, conversation.id, customer.id
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            for index, content in enumerate(("tôi muốn áo", "màu hồng", "size M")):
                db.add(Message(conversation_id=conversation.id, channel="shopee", direction="inbound",
                               content=content, received_at=now + timedelta(seconds=index)))
            db.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_one_reply_for_three_fragments_and_retry(self):
        with Session(self.engine) as db:
            rows = db.query(Message).order_by(Message.id).all()
            for row in rows:
                schedule_chatbot_turn(db, business_id=self.business_id,
                                      conversation_id=self.conversation_id, message_id=row.id)
            self.assertEqual(3, db.query(CrmJob).count())
            schedule_chatbot_turn(db, business_id=self.business_id,
                                  conversation_id=self.conversation_id, message_id=rows[-1].id)
            self.assertEqual(3, db.query(CrmJob).count())
            with patch("app.services.conversation_turn_service._merge_fragments", side_effect=lambda parts: " ".join(parts)), \
                 patch("app.services.auto_reply_service.process_rag_auto_reply", return_value=True) as reply:
                for row in rows:
                    dispatch_chatbot_turn(db, business_id=self.business_id,
                                          payload={"conversation_id": self.conversation_id, "message_id": row.id})
            reply.assert_called_once()
            kwargs = reply.call_args.kwargs
            self.assertEqual("tôi muốn áo màu hồng size M", kwargs["query_text"])
            self.assertEqual(f"turn:{self.business_id}:{self.conversation_id}:{rows[0].id}:{rows[-1].id}", kwargs["auto_reply_key"])
            self.assertEqual(rows[-1].id, kwargs["expected_latest_inbound_id"])

    def test_collection_sees_one_complete_turn_instead_of_each_fragment(self):
        with Session(self.engine) as db:
            latest = db.query(Message.id).order_by(Message.id.desc()).limit(1).scalar()
            result = CollectionFlowResult(session_id=1, status="quoted", current_field=None, prompt="Còn hàng ạ.")
            with patch("app.services.conversation_turn_service._merge_fragments", side_effect=lambda parts: " ".join(parts)), \
                 patch("app.services.customer_collection_flow.advance_customer_collection", return_value=result) as collect, \
                 patch("app.services.auto_reply_service.send_text_reply", return_value={"message_id": "test"}) as send, \
                 patch("app.services.auto_reply_service.process_rag_auto_reply") as rag:
                self.assertTrue(dispatch_chatbot_turn(db, business_id=self.business_id,
                    payload={"conversation_id": self.conversation_id, "message_id": latest}))
            self.assertEqual("tôi muốn áo màu hồng size M", collect.call_args.kwargs["text"])
            send.assert_called_once()
            rag.assert_not_called()

    def test_collection_is_not_applied_twice_when_delivery_retries(self):
        with Session(self.engine) as db:
            latest = db.query(Message).order_by(Message.id.desc()).first()
            schedule_chatbot_turn(db, business_id=self.business_id,
                                  conversation_id=self.conversation_id, message_id=latest.id)
            result = CollectionFlowResult(session_id=1, status="quoted", current_field=None, prompt="Báo giá mới")
            with patch("app.services.customer_collection_flow.advance_customer_collection", return_value=result) as collect, \
                 patch("app.services.auto_reply_service.send_text_reply", side_effect=[OSError("offline"), {"message_id": "ok"}]) as send:
                with self.assertRaises(OSError):
                    dispatch_chatbot_turn(db, business_id=self.business_id,
                        payload={"conversation_id": self.conversation_id, "message_id": latest.id})
                db.rollback()
                job = db.query(CrmJob).filter_by(idempotency_key=f"chatbot-turn:{self.conversation_id}:{latest.id}").one()
                dispatch_chatbot_turn(db, business_id=self.business_id, payload=job.payload)
            collect.assert_called_once()
            self.assertEqual(2, send.call_count)

    def test_unknown_shopee_delivery_does_not_retry_automatically(self):
        from fastapi import HTTPException

        with Session(self.engine) as db:
            latest = db.query(Message).order_by(Message.id.desc()).first()
            result = CollectionFlowResult(session_id=1, status="quoted", current_field=None, prompt="Báo giá mới")
            with patch("app.services.customer_collection_flow.advance_customer_collection", return_value=result), \
                 patch("app.services.auto_reply_service.send_text_reply", side_effect=HTTPException(
                     status_code=409, detail={"code": "delivery_unknown"})) as send:
                self.assertTrue(dispatch_chatbot_turn(db, business_id=self.business_id,
                    payload={"conversation_id": self.conversation_id, "message_id": latest.id}))
            send.assert_called_once()

    def test_latest_inbound_guard_accepts_multiple_prior_messages(self):
        from app.services.auto_reply_service import process_rag_auto_reply

        with Session(self.engine) as db:
            latest = db.query(Message.id).order_by(Message.id.desc()).first()[0]
            with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
                 patch("app.services.auto_reply_service.is_business_open", return_value=True), \
                 patch("app.services.auto_reply_service.customer_order_reply", return_value="Còn hàng."), \
                 patch("app.services.auto_reply_service.send_text_reply", return_value={"message_id": "test"}) as send:
                self.assertTrue(process_rag_auto_reply(
                    db, self.conversation_id, "shopee", "Còn hàng không?", self.business_id,
                    expected_latest_inbound_id=latest,
                ))
                self.assertFalse(process_rag_auto_reply(
                    db, self.conversation_id, "shopee", "Còn hàng không?", self.business_id,
                    expected_latest_inbound_id=latest - 1,
                ))
            send.assert_called_once()

    def test_bridge_unavailable_keeps_turn_retryable(self):
        from fastapi import HTTPException
        from app.services.auto_reply_service import process_rag_auto_reply

        with Session(self.engine) as db:
            latest = db.query(Message.id).order_by(Message.id.desc()).first()[0]
            with patch("app.services.auto_reply_service.get_auto_reply_enabled", return_value=True), \
                 patch("app.services.auto_reply_service.is_business_open", return_value=True), \
                 patch("app.services.auto_reply_service.customer_order_reply", return_value="Còn hàng."), \
                 patch("app.services.auto_reply_service.send_text_reply", side_effect=HTTPException(502, "bridge offline")):
                with self.assertRaises(HTTPException):
                    process_rag_auto_reply(
                        db, self.conversation_id, "shopee", "Còn hàng không?", self.business_id,
                        expected_latest_inbound_id=latest,
                    )

    def test_wrong_shop_and_human_mode_never_reply(self):
        with Session(self.engine) as db:
            source = db.query(Message).order_by(Message.id.desc()).first()
            with patch("app.services.auto_reply_service.process_rag_auto_reply") as reply:
                self.assertFalse(dispatch_chatbot_turn(db, business_id=self.other_id,
                                 payload={"conversation_id": self.conversation_id, "message_id": source.id}))
                conversation = db.get(Conversation, self.conversation_id)
                conversation.bot_mode = "human"
                db.commit()
                self.assertFalse(dispatch_chatbot_turn(db, business_id=self.business_id,
                                 payload={"conversation_id": self.conversation_id, "message_id": source.id}))
            reply.assert_not_called()

    def test_mock_shopee_and_tiktok_outbound_routing(self):
        with Session(self.engine) as db:
            source = db.query(Message).order_by(Message.id.desc()).first()
            conversation = db.get(Conversation, self.conversation_id)
            for channel in ("shopee", "tiktok"):
                conversation.channel = channel
                db.commit()
                with patch("app.services.auto_reply_service.process_rag_auto_reply", return_value=True) as reply:
                    dispatch_chatbot_turn(db, business_id=self.business_id,
                        payload={"conversation_id": self.conversation_id, "message_id": source.id})
                self.assertEqual(channel, reply.call_args.kwargs["channel"])

    def test_gemini_error_keeps_ordered_multilingual_fragments(self):
        from types import SimpleNamespace
        from app.services import conversation_turn_service

        with patch.object(conversation_turn_service, "settings", SimpleNamespace(conversation_gemini_api_keys=["mock-key"])), \
             patch("app.rag.llm_caller.call_gemini_for_turn", side_effect=TimeoutError):
            result = conversation_turn_service._merge_fragments(["Mình muốn áo màu hồng", "size M please"])
        self.assertEqual("Mình muốn áo màu hồng\nsize M please", result)
        with patch.object(conversation_turn_service, "settings", SimpleNamespace(conversation_gemini_api_keys=["mock-key"])), \
             patch("app.rag.llm_caller.call_gemini_for_turn", return_value="Tôi muốn áo đỏ, size M"):
            guarded = conversation_turn_service._merge_fragments(["Mình muốn áo màu hồng", "size M please"])
        self.assertEqual("Mình muốn áo màu hồng\nsize M please", guarded)

    def test_separated_turn_is_not_merged_with_old_fragment(self):
        with Session(self.engine) as db:
            old, latest = db.query(Message).order_by(Message.id).first(), db.query(Message).order_by(Message.id.desc()).first()
            latest.received_at = old.received_at + timedelta(seconds=20)
            db.commit()
            with patch("app.services.conversation_turn_service._merge_fragments", side_effect=lambda parts: " ".join(parts)), \
                 patch("app.services.auto_reply_service.process_rag_auto_reply", return_value=True) as reply:
                dispatch_chatbot_turn(db, business_id=self.business_id,
                    payload={"conversation_id": self.conversation_id, "message_id": latest.id})
            self.assertEqual(latest.content, reply.call_args.kwargs["query_text"])

    def test_preference_uses_only_explicit_fact(self):
        with Session(self.engine) as db:
            customer = db.query(Customer).filter(Customer.business_id == self.business_id).first()
            db.add(CustomerFact(business_id=self.business_id, customer_id=customer.id,
                fact_type="preference", fact_key="preferred_color", fact_value_json="hồng",
                confidence=0.9, source_type="extracted", is_verified=False))
            db.commit()
            self.assertEqual("hồng", _preferred_color(db, self.business_id, customer.id))
            self.assertIsNone(_preferred_color(db, self.other_id, customer.id))

    def test_opt_out_removes_derived_facts_and_persisted_queries(self):
        with Session(self.engine) as db:
            customer = db.query(Customer).filter(Customer.business_id == self.business_id).first()
            fact = CustomerFact(business_id=self.business_id, customer_id=customer.id,
                fact_type="preference", fact_key="preferred_color", fact_value_json="hồng",
                confidence=0.9, source_type="extracted", is_verified=False)
            interaction = CustomerProductInteraction(business_id=self.business_id, customer_id=customer.id,
                event_type="search", source="chat", query_text="áo khoác màu hồng",
                idempotency_key="turn-search-1", event_metadata={})
            db.add_all([fact, interaction])
            db.commit()
            stop_customer_personalization(db, self.business_id, customer.id)
            db.commit()
            self.assertEqual(0, db.query(CustomerFact).filter(CustomerFact.id == fact.id).count())
            self.assertEqual(0, db.query(CustomerProductInteraction).filter(CustomerProductInteraction.id == interaction.id).count())

    def test_opt_out_scrubs_personal_recommendation_experiment_context(self):
        with Session(self.engine) as db:
            experiment = Experiment(business_id=self.business_id, name="turn-test", variants=["balanced"], status="running")
            db.add(experiment)
            db.flush()
            decision = BanditDecision(business_id=self.business_id, experiment_id=experiment.id,
                subject_key=f"customer:{self.customer_id}", arm="balanced",
                context={"query": "private search"}, context_hash="sensitive-hash")
            db.add(decision)
            db.flush()
            request = RecommendationRequest(business_id=self.business_id, request_id="turn-test-request",
                customer_id=self.customer_id, experiment_id=experiment.id, bandit_decision_id=decision.id,
                strategy="balanced", model_version="test", context={"query": "private search"}, served_items=[])
            db.add(request)
            db.commit()
            stop_customer_personalization(db, self.business_id, self.customer_id)
            db.commit()
            db.refresh(decision)
            db.refresh(request)
            self.assertEqual("anonymous", decision.subject_key)
            self.assertEqual({}, decision.context)
            self.assertIsNone(decision.context_hash)
            self.assertIsNone(request.customer_id)
            self.assertIsNone(request.experiment_id)
            self.assertIsNone(request.bandit_decision_id)
            self.assertEqual({}, request.context)

    def test_personalization_revocation_blocks_extraction_and_color_preference(self):
        with Session(self.engine) as db:
            source = db.query(Message).order_by(Message.id).first()
            db.add(CustomerConsent(business_id=self.business_id, customer_id=self.customer_id,
                                   purpose="personalization", status="revoked"))
            db.commit()
            with patch("app.services.customer_fact_extractor.get_customer_fact_extraction_enabled", return_value=True), \
                 patch("app.services.customer_fact_extractor.extract_and_persist_customer_facts") as extractor:
                result = dispatch_customer_fact_extraction(db, business_id=self.business_id,
                            payload={"customer_id": self.customer_id, "message_id": source.id})
            self.assertEqual(0, result)
            extractor.assert_not_called()
            self.assertIsNone(_preferred_color(db, self.business_id, self.customer_id))
