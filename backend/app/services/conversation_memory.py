"""Short-lived reply context; caller persists the result in messages.metadata_.

No writes, migrations, delivery, price/stock snapshots, or model calls here.
Use metadata_[MEMORY_KEY] on a successfully sent outbound reply only.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.models.customer import Customer
from app.models.customer_collection import CustomerConsent
from app.models.message import Message
from app.models.sales import Product

MEMORY_KEY = "reply_memory"
SCHEMA_VERSION = 1
MEMORY_TTL = timedelta(minutes=30)


def _utc(value: datetime | None) -> datetime:
    value = value if value is not None else datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _text(value: str) -> str:
    # Keep accents, punctuation and dimensions: no typo/fuzzy normalization.
    return " ".join(unicodedata.normalize("NFC", str(value or "")).casefold().split())


def _fold(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", _text(value).replace("đ", "d"))
                   if not unicodedata.combining(c))


def _positive_id(value) -> bool:
    return type(value) is int and value > 0


def _scope(db, business_id, conversation_id) -> dict | None:
    if not _positive_id(business_id) or not _positive_id(conversation_id):
        return None
    conversation = db.scalars(select(Conversation).where(
        Conversation.id == conversation_id, Conversation.business_id == business_id,
    ).execution_options(populate_existing=True)).first()
    if (conversation is None or conversation.business_id != business_id
            or conversation.id != conversation_id or not _positive_id(conversation.customer_id)):
        return None
    return {"business_id": business_id, "customer_id": conversation.customer_id,
            "conversation_id": conversation_id}


def _reply_memory_allowed(db, business_id: int, customer_id: int, *, lock_consent=False) -> bool:
    """Preserve chat context unless the customer explicitly opted out or revoked it.

    Missing personalization consent is not reinterpreted here: this key is
    single-conversation operational context, not a profile/training signal.
    The owner still needs to approve its standalone purpose and retention.
    """
    if not _positive_id(business_id) or not _positive_id(customer_id):
        return False
    try:
        customer_query = select(Customer).where(
            Customer.id == customer_id,
            Customer.business_id == business_id,
        )
        if lock_consent:
            customer_query = customer_query.with_for_update()
        customer = db.scalars(customer_query.execution_options(populate_existing=True)).first()
        if customer is None or bool(customer.fact_extraction_opt_out):
            return False
        consent_query = select(CustomerConsent).where(
            CustomerConsent.business_id == business_id,
            CustomerConsent.customer_id == customer_id,
            CustomerConsent.purpose == "personalization",
        ).order_by(CustomerConsent.id.desc()).limit(1)
        if lock_consent:
            consent_query = consent_query.with_for_update()
        consent = db.scalars(consent_query.execution_options(populate_existing=True)).first()
    except Exception:
        return False
    return consent is None or (consent.status == "granted" and consent.revoked_at is None)


def _catalog(db, business_id, *, active_only=False) -> list[Product]:
    statement = select(Product).where(Product.business_id == business_id)
    if active_only:
        statement = statement.where(Product.status == "active")
    return [p for p in db.scalars(statement.order_by(Product.id).execution_options(
        populate_existing=True,
    )).all() if p.business_id == business_id and (not active_only or p.status == "active")]


def _aliases(product) -> set[str]:
    metadata = product.metadata_ if isinstance(product.metadata_, dict) else {}
    aliases = metadata.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    if not isinstance(aliases, list):
        aliases = []
    names = metadata.get("display_names", {})
    names = list(names.values()) if isinstance(names, dict) else []
    values = [product.name, metadata.get("display_name_en"), *names, *aliases]
    result = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            continue
        identity = re.sub(r"\d+(?:[.,]\d+)?\s*/\s*\d+(?:[.,]\d+)?\s*[-r]\s*\d+", "", _fold(value))
        identity = re.sub(r"\b(?:mm|cm|inch|inches|size|kich thuoc|co)\b", "", identity)
        if any(c.isalpha() for c in identity):
            result.add(_text(value))
    return result


def _mentioned(products, answer: str) -> list[int]:
    owners = defaultdict(set)
    for product in products:
        for alias in _aliases(product):
            owners[alias].add(product.id)
    hits = []
    for alias, ids in owners.items():
        for match in re.finditer(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", _text(answer)):
            hits.append((match.start(), match.end(), ids))
    found = set()
    for start, end, ids in hits:
        # A longer full label owns its span (A must not also match A Plus).
        if len(ids) == 1 and not any(
            left <= start and right >= end and (left, right) != (start, end)
            for left, right, _ in hits
        ):
            found.update(ids)
    return [p.id for p in products if p.id in found and p.status == "active"]


def _reset(text: str) -> bool:
    return bool(re.search(r"\b(?:reset|start over|forget (?:that|previous)|"
                          r"bat dau lai|xoa (?:ngu canh|bo nho)|quen (?:cai do|phan truoc)|"
                          r"doi chu de|chuyen chu de)\b", _fold(text)))


def _constraints(query: str) -> dict:
    text = _fold(query)
    result = {}
    budget = re.search(
        r"\b(ngan sach|budget|duoi|toi da|khong qua|under|at most)\s*(?:la\s*|of\s*)?"
        r"(\d+(?:[.,]\d+)*)\s*(trieu|million|tr|nghin|ngan|k|vnd|dong|đ)\b", text,
    )
    if budget:
        unit = budget[3]
        multiplier = 1_000_000 if unit in {"trieu", "million", "tr"} else (
            1_000 if unit in {"nghin", "ngan", "k"} else 1)
        number = budget[2]
        if unit in {"vnd", "dong", "đ"} and re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", number):
            number = re.sub(r"[.,]", "", number)
        # Ambiguous separators with k/tr are not a reliable explicit amount.
        if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", number):
            amount = Decimal(number.replace(",", ".")) * multiplier
            if 0 < amount <= 10**12 and amount == int(amount):
                result["budget"] = {"amount": int(amount), "currency": "VND", "operator": "lte"}
    qty = re.search(r"\b(?:so luong|quantity|qty)\s*[:=]?\s*(\d+)\b|"
                    r"\b(?:mua|lay|can|buy|need)\s+(\d+)\s*"
                    r"(?:cai|chiec|bo|chai|lo|san pham|units?|pieces?)\b", text)
    if qty:
        number = int(qty[1] or qty[2])
        if 0 < number <= 1_000_000:
            result["qty"] = number
    return result


def _intent(query: str) -> str:
    text = _fold(query)
    for intent, pattern in (("reset", r"\b(?:reset|bat dau lai)\b"),
                            ("compare", r"\b(?:so sanh|re hon|compare|cheaper)\b"),
                            ("stock", r"\b(?:con hang|ton kho|stock|available)\b"),
                            ("price", r"\b(?:gia|bao nhieu tien|price|how much)\b"),
                            ("purchase", r"\b(?:mua|lay|buy|order)\b")):
        if re.search(pattern, text):
            return intent
    return "other"


def _pending(answer: str) -> str | None:
    if "?" not in answer:
        return None
    question = _fold(answer[answer.rfind("?") + 1:] or answer.split("?")[-2]).split("\n")[-1]
    for slot, pattern in (("budget", r"ngan sach|budget"),
                          ("qty", r"so luong|bao nhieu (?:cai|chiec|chai)|quantity|how many"),
                          ("variant", r"kich thuoc|phien ban|doi xe|size|variant|model"),
                          ("product", r"san pham nao|ten san pham|which product|product name")):
        if re.search(pattern, question):
            return slot
    return None


def _empty(scope=None) -> dict:
    return {"schema_version": SCHEMA_VERSION, "scope": scope or {},
            "active_product_ids": [], "constraints": {}, "pending_slot": None,
            "last_intent": "other", "created_at": None, "expires_at": None}


def build_reply_memory(db: Session, business_id: int, conversation_id: int,
                       query: str, answer: str, product_ids: list[int] | None = None,
                       now: datetime | None = None) -> dict | None:
    """Build JSON state from this reply only; IDs are hints, never evidence.

    None derives IDs from unique full labels; [] deliberately disables them.
    Save as extra_metadata={MEMORY_KEY: state} in send_text_reply at integration.
    """
    scope = _scope(db, business_id, conversation_id)
    state = _empty(scope)
    if scope is None:
        return None
    if not _reply_memory_allowed(db, business_id, scope["customer_id"], lock_consent=True):
        return None
    moment = _utc(now)
    state.update(created_at=moment.isoformat(), expires_at=(moment + MEMORY_TTL).isoformat())
    if _reset(query):
        state["last_intent"] = "reset"
        return state
    ids = _mentioned(_catalog(db, business_id), answer)
    if product_ids is not None:
        trusted = {i for i in product_ids if _positive_id(i)}
        ids = [i for i in ids if i in trusted]
    state.update(active_product_ids=ids, constraints=_constraints(query),
                 pending_slot=_pending(answer), last_intent=_intent(query))
    return state


def load_reply_memory(db: Session, business_id: int, conversation_id: int,
                      now: datetime | None = None) -> dict:
    """Validate only the latest outbound bot/staff row; never search older state.

    A newer failed/pending/metadata-free reply is a barrier. At most one
    customer inbound may follow the saved reply. Catalog facts are read fresh.
    """
    scope = _scope(db, business_id, conversation_id)
    empty = _empty(scope)
    if scope is None or not _reply_memory_allowed(db, business_id, scope["customer_id"]):
        return empty
    reply = db.scalars(select(Message).where(
        Message.conversation_id == conversation_id, Message.direction == "outbound",
        Message.sender_type.in_(("bot", "staff")),
    ).order_by(Message.id.desc()).limit(1).execution_options(populate_existing=True)).first()
    if reply is None or reply.status != "sent" or not isinstance(reply.sent_at, datetime):
        return empty
    following = db.scalars(select(Message).where(
        Message.conversation_id == conversation_id, Message.id > reply.id,
        Message.direction == "inbound", Message.sender_type == "customer",
    ).order_by(Message.id).limit(2)).all()
    if len(following) > 1:
        return empty
    metadata = reply.metadata_ if isinstance(reply.metadata_, dict) else {}
    state = metadata.get(MEMORY_KEY)
    if (not isinstance(state, dict) or type(state.get("schema_version")) is not int
            or state.get("schema_version") != SCHEMA_VERSION or state.get("scope") != scope):
        return empty
    try:
        created = _utc(datetime.fromisoformat(state["created_at"]))
        expires = _utc(datetime.fromisoformat(state["expires_at"]))
    except (KeyError, TypeError, ValueError):
        return empty
    moment = _utc(now)
    if not (created <= _utc(reply.sent_at) <= moment < expires
            and expires - created == MEMORY_TTL):
        return empty
    ids = state.get("active_product_ids")
    constraints = state.get("constraints")
    if (not isinstance(ids, list) or any(not _positive_id(i) for i in ids)
            or not isinstance(constraints, dict)
            or state.get("pending_slot") not in (None, "budget", "qty", "variant", "product")
            or state.get("last_intent") not in ("other", "reset", "compare", "stock", "price", "purchase")):
        return empty
    clean = {}
    budget = constraints.get("budget")
    if (isinstance(budget, dict) and _positive_id(budget.get("amount"))
            and budget["amount"] <= 10**12 and budget.get("currency") == "VND"
            and budget.get("operator") == "lte"):
        clean["budget"] = {"amount": budget["amount"], "currency": "VND", "operator": "lte"}
    if _positive_id(constraints.get("qty")) and constraints["qty"] <= 1_000_000:
        clean["qty"] = constraints["qty"]
    # Re-prove the IDs from the actual reply and today's tenant catalog.
    mentioned = _mentioned(_catalog(db, business_id), reply.content or "")
    return {**empty, "created_at": created.isoformat(), "expires_at": expires.isoformat(),
            "active_product_ids": [i for i in mentioned if i in ids], "constraints": clean,
            "pending_slot": state.get("pending_slot"), "last_intent": state.get("last_intent")}


def purge_reply_memory_for_customer(
    db: Session,
    business_id: int,
    customer_id: int,
    *,
    keys: tuple[str, ...] | None = None,
) -> int:
    """Remove selected persisted context keys from messages and retry jobs."""
    if not _positive_id(business_id) or not _positive_id(customer_id):
        return 0
    from app.services.sales_journey_adapter import JOURNEY_STATE_METADATA_KEY
    from app.models.crm_job import CrmJob

    personal_keys = tuple(dict.fromkeys(keys or (MEMORY_KEY, JOURNEY_STATE_METADATA_KEY)))
    personal_keys = tuple(key for key in personal_keys if key in {MEMORY_KEY, JOURNEY_STATE_METADATA_KEY})
    if not personal_keys:
        return 0
    conversation_ids = set(db.scalars(
        select(Conversation.id).where(
            Conversation.business_id == business_id,
            Conversation.customer_id == customer_id,
        )
    ).all())
    messages = db.scalars(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.business_id == business_id,
            Conversation.customer_id == customer_id,
            Message.direction == "outbound",
        )
        .execution_options(populate_existing=True, yield_per=250)
    )
    purged = 0
    for message in messages:
        metadata = message.metadata_ if isinstance(message.metadata_, dict) else None
        if metadata is None or not any(key in metadata for key in personal_keys):
            continue
        safe_metadata = dict(metadata)
        for key in personal_keys:
            safe_metadata.pop(key, None)
        message.metadata_ = safe_metadata
        purged += 1

    if conversation_ids:
        jobs = db.scalars(select(CrmJob).where(
            CrmJob.business_id == business_id,
            CrmJob.kind == "chatbot.reply_turn",
        ).execution_options(yield_per=250))
        for job in jobs:
            payload = job.payload if isinstance(job.payload, dict) else None
            if payload is None or payload.get("conversation_id") not in conversation_ids:
                continue
            metadata = payload.get("collection_metadata")
            if not isinstance(metadata, dict) or not any(key in metadata for key in personal_keys):
                continue
            safe_payload = dict(payload)
            safe_metadata = dict(metadata)
            for key in personal_keys:
                safe_metadata.pop(key, None)
            safe_payload["collection_metadata"] = safe_metadata
            job.payload = safe_payload
            purged += 1
    return purged


def resolve_memory_products(db: Session, business_id: int, conversation_id: int,
                            current_text: str, now: datetime | None = None) -> list[Product]:
    """Return current catalog rows for conservative anaphoric follow-ups only.

    Candidates may remain plural; the caller must ask rather than pick a SKU.
    Unrecognized/new topic words and explicit reset return []. No persistence.
    """
    if _reset(current_text):
        return []
    text = _fold(current_text)
    patterns = (
        r"\b(?:loai|mau)\s+(?:re hon|dat hon)\b",
        r"\b(?:cai|mon|mau|loai|san pham|hai loai|hai mau)\s+(?:do|nay|ay|vua noi)\b",
        r"\b(?:that one|this one|those|these|it|them|that product|this product)\b",
        r"\b(?:loai nao|mau nao|which one|which is|so sanh|compare)\b",
        r"\b(?:re hon|dat hon|cheaper|more expensive|gia bao nhieu|bao nhieu tien|"
        r"gia the nao|con hang khong|con bao nhieu|how much|what is the price|"
        r"is available|still available|in stock)\b",
    )
    if not any(re.search(pattern, text) for pattern in patterns):
        return []
    for pattern in patterns:
        text = re.sub(pattern, " ", text)
    text = re.sub(r"\b(?:a|an|the|is|are|do|does|please|co|con|khong|thi|va|voi|"
                  r"bao|gia|nhieu|cai|chiec|chai|bo|lo|cho|minh|toi|em|anh|chi|ban|biet|nhe|nha|a|ak)\b", " ", text)
    if re.search(r"\w", text):
        return []
    state = load_reply_memory(db, business_id, conversation_id, now)
    ids = state["active_product_ids"]
    if not ids:
        return []
    return [p for p in _catalog(db, business_id, active_only=True) if p.id in ids]
