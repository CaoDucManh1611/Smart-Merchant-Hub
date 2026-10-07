import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.models.business import Business
from app.models.business_setting import BusinessSetting
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_fact import CustomerFact
from app.models.crm_job import CrmJob
from app.models.message import Message
from app.services.customer_fact_extractor import (
    extract_customer_facts,
    extract_and_persist_customer_facts,
    parse_extraction_response,
    persist_extracted_facts,
    get_customer_fact_extraction_enabled,
    dispatch_weekly_customer_fact_scan,
)


class CustomerFactExtractorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Business.metadata.create_all(cls.engine)
        with Session(cls.engine) as db:
            one = Business(name="Extractor One", slug="extractor-one")
            two = Business(name="Extractor Two", slug="extractor-two")
            db.add_all([one, two])
            db.flush()
            customer = Customer(
                business_id=one.id,
                channel="telegram",
                external_user_id="extractor-user",
            )
            other = Customer(
                business_id=two.id,
                channel="telegram",
                external_user_id="other-extractor-user",
            )
            db.add_all([customer, other])
            db.flush()
            conversation = Conversation(
                business_id=one.id,
                customer_id=customer.id,
                channel="telegram",
            )
            db.add(conversation)
            db.flush()
            message = Message(
                conversation_id=conversation.id,
                channel="telegram",
                external_user_id="extractor-user",
                external_message_id="extractor-message-1",
                direction="inbound",
                content="Tôi muốn serum dưới 500 nghìn",
            )
            db.add(message)
            db.flush()
            verified = CustomerFact(
                business_id=one.id,
                customer_id=customer.id,
                fact_type="preference",
                fact_key="budget_max",
                fact_value_json=400000,
                confidence=1.0,
                source_type="manual",
                is_verified=True,
            )
            db.add(verified)
            db.commit()
            cls.business_id = one.id
            cls.other_business_id = two.id
            cls.customer_id = customer.id
            cls.other_customer_id = other.id
            cls.message_id = message.id
            cls.verified_fact_id = verified.id

    def test_parser_accepts_fenced_json_and_discards_unsupported_candidates(self):
        raw = """```json
        {"facts": [
          {"fact_type": "preference", "fact_key": "budget_max", "fact_value": 500000, "confidence": 0.94},
          {"fact_type": "profile", "fact_key": "phone", "fact_value": "0912345678", "confidence": 0.99},
          {"fact_type": "preference", "fact_key": "preferred_brand", "fact_value": "buyer@example.com", "confidence": 0.99},
          {"fact_type": "", "fact_key": "", "fact_value": null, "confidence": 0.99},
          {"fact_type": "preference", "fact_key": "weak", "fact_value": "x", "confidence": 0.2}
        ]}
        ```"""
        facts = parse_extraction_response(raw, min_confidence=0.65)
        self.assertEqual(1, len(facts))
        self.assertEqual("budget_max", facts[0]["fact_key"])
        self.assertEqual(500000, facts[0]["fact_value"])

    def test_extraction_calls_llm_with_strict_json_contract(self):
        with patch(
            "app.services.customer_fact_extractor.call_llm",
            return_value='{"facts":[{"fact_type":"preference","fact_key":"interested_category","fact_value":"serum","confidence":0.9}]}',
        ) as call:
            facts = extract_customer_facts("Tôi đang quan tâm serum")

        self.assertEqual("interested_category", facts[0]["fact_key"])
        prompt_messages = call.call_args.args[0]
        self.assertEqual("system", prompt_messages[0]["role"])
        self.assertIn("JSON", prompt_messages[0]["content"])
        self.assertEqual("Tôi đang quan tâm serum", prompt_messages[1]["content"])

    def test_commands_and_empty_messages_do_not_call_llm(self):
        with patch("app.services.customer_fact_extractor.call_llm") as call:
            self.assertEqual([], extract_customer_facts("/start"))
            self.assertEqual([], extract_customer_facts("   "))
        call.assert_not_called()

    def test_business_setting_overrides_global_feature_flag(self):
        with Session(self.engine) as db:
            db.add(BusinessSetting(
                business_id=self.business_id,
                key="customer_fact_extraction_enabled",
                value="false",
            ))
            db.commit()
            self.assertFalse(get_customer_fact_extraction_enabled(db, self.business_id))

            setting = db.query(BusinessSetting).filter(
                BusinessSetting.business_id == self.business_id,
                BusinessSetting.key == "customer_fact_extraction_enabled",
            ).one()
            setting.value = "true"
            db.commit()
            self.assertTrue(get_customer_fact_extraction_enabled(db, self.business_id))

    def test_persistence_is_idempotent_tenant_scoped_and_preserves_verified_fact(self):
        candidate = {
            "fact_type": "preference",
            "fact_key": "interested_category",
            "fact_value": "serum",
            "confidence": 0.9,
        }
        with Session(self.engine) as db:
            created = persist_extracted_facts(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                source_message_id=self.message_id,
                candidates=[candidate],
            )
            duplicate = persist_extracted_facts(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                source_message_id=self.message_id,
                candidates=[candidate],
            )
            verified_attempt = persist_extracted_facts(
                db,
                business_id=self.business_id,
                customer_id=self.customer_id,
                source_message_id=self.message_id,
                candidates=[{
                    "fact_type": "preference",
                    "fact_key": "budget_max",
                    "fact_value": 900000,
                    "confidence": 0.99,
                }],
            )

            self.assertEqual(1, len(created))
            self.assertEqual([], duplicate)
            self.assertEqual([], verified_attempt)
            verified = db.get(CustomerFact, self.verified_fact_id)
            self.assertEqual(400000, verified.fact_value_json)

            cross_tenant = persist_extracted_facts(
                db,
                business_id=self.other_business_id,
                customer_id=self.customer_id,
                source_message_id=self.message_id,
                candidates=[candidate],
            )
            self.assertEqual([], cross_tenant)
            self.assertEqual(
                1,
                db.query(CustomerFact).filter(
                    CustomerFact.business_id == self.business_id,
                    CustomerFact.fact_key == "interested_category",
                ).count(),
            )

    def test_customer_opt_out_prevents_llm_extraction_and_persistence(self):
        with Session(self.engine) as db:
            db.get(Customer, self.customer_id).fact_extraction_opt_out = True
            db.commit()
            with patch("app.services.customer_fact_extractor.reserve_ai_budget") as reserve, patch(
                "app.services.customer_fact_extractor.call_llm"
            ) as call:
                facts = extract_and_persist_customer_facts(
                    db,
                    business_id=self.business_id,
                    customer_id=self.customer_id,
                    source_message_id=self.message_id,
                    content="Tôi thích màu hồng",
                )
            self.assertEqual([], facts)
            reserve.assert_not_called()
            call.assert_not_called()
            db.get(Customer, self.customer_id).fact_extraction_opt_out = False
            db.commit()

    def test_weekly_history_scan_is_resumable_and_does_not_reprocess_completed_rows(self):
        with Session(self.engine) as db:
            setting = db.query(BusinessSetting).filter(
                BusinessSetting.business_id == self.business_id,
                BusinessSetting.key == "customer_fact_extraction_enabled",
            ).first()
            if setting is None:
                setting = BusinessSetting(
                    business_id=self.business_id,
                    key="customer_fact_extraction_enabled",
                    value="true",
                )
                db.add(setting)
            else:
                setting.value = "true"
            conversation = db.query(Conversation).filter(
                Conversation.business_id == self.business_id,
                Conversation.customer_id == self.customer_id,
            ).one()
            db.add(Message(
                conversation_id=conversation.id,
                channel="telegram",
                external_user_id="extractor-user",
                external_message_id="extractor-message-2",
                direction="inbound",
                content="Mình thích màu hồng",
            ))
            db.add(Message(
                conversation_id=conversation.id,
                channel="telegram",
                external_user_id="extractor-user",
                external_message_id="extractor-message-outbound",
                direction="outbound",
                content="Shop chào bạn",
            ))
            db.commit()

        with Session(self.engine) as db, patch(
            "app.services.customer_fact_extractor.extract_and_persist_customer_facts",
            return_value=[],
        ) as extract:
            result = dispatch_weekly_customer_fact_scan(db, business_id=self.business_id)
            self.assertEqual(2, result["scanned"])
            self.assertFalse(result["has_more"])
            # The original message already has a durable extraction from an
            # earlier test; only the newly appended inbound row should call AI.
            self.assertEqual(1, extract.call_count)
            jobs = db.query(CrmJob).filter(
                CrmJob.business_id == self.business_id,
                CrmJob.kind == "customer.facts.weekly_scan",
            ).all()
            self.assertTrue(jobs)

        with Session(self.engine) as db, patch(
            "app.services.customer_fact_extractor.extract_and_persist_customer_facts",
            return_value=[],
        ) as extract:
            result = dispatch_weekly_customer_fact_scan(db, business_id=self.business_id)
            self.assertEqual(0, result["scanned"])
            extract.assert_not_called()


if __name__ == "__main__":
    unittest.main()
