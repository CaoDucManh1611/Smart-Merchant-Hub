import unittest

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.models import MessageAttachment
from app.models.channel import Channel
from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.message import Message


class MessageAttachmentModelTests(unittest.TestCase):
    def test_attachment_table_has_tenant_and_provider_identity_columns(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        for model in (Customer, Channel, Conversation, Message, MessageAttachment):
            model.__table__.create(engine)
        columns = {column["name"] for column in inspect(engine).get_columns("message_attachments")}
        self.assertTrue(
            {
                "id",
                "business_id",
                "message_id",
                "channel_id",
                "media_type",
                "mime_type",
                "file_name",
                "duration_ms",
                "external_attachment_id",
                "source_url",
                "storage_key",
                "metadata",
                "created_at",
            }.issubset(columns)
        )


if __name__ == "__main__":
    unittest.main()
