-- Smart Merchant Hub - PostgreSQL schema migration for DBeaver
-- Muc tieu: 20 bang nghiep vu trong schema public.
-- Script idempotent: co the chay lai, khong xoa du lieu hien co.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- ================================================================
-- 1. Cau hinh he thong hien co
-- ================================================================

CREATE TABLE IF NOT EXISTS app_settings (
    key VARCHAR(100) PRIMARY KEY,
    value VARCHAR(500) NOT NULL
);

-- ================================================================
-- 2. Tenant, tai khoan va goi dich vu
-- ================================================================

CREATE TABLE IF NOT EXISTS businesses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    slug VARCHAR(120) NOT NULL UNIQUE,
    email VARCHAR(255),
    phone VARCHAR(40),
    address TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    full_name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    password_hash VARCHAR(255),
    role VARCHAR(40) NOT NULL DEFAULT 'business_agent',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_users_business_email UNIQUE (business_id, email)
);

CREATE TABLE IF NOT EXISTS service_plans (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(120) NOT NULL,
    description TEXT,
    price NUMERIC(12, 2) NOT NULL DEFAULT 0,
    billing_cycle VARCHAR(20) NOT NULL DEFAULT 'monthly',
    max_users INTEGER NOT NULL DEFAULT 5,
    max_channels INTEGER NOT NULL DEFAULT 2,
    max_documents INTEGER NOT NULL DEFAULT 20,
    features JSONB,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    plan_id INTEGER NOT NULL REFERENCES service_plans(id) ON DELETE RESTRICT,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    starts_at TIMESTAMP,
    ends_at TIMESTAMP,
    auto_renew BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    amount NUMERIC(12, 2) NOT NULL,
    currency VARCHAR(8) NOT NULL DEFAULT 'VND',
    provider VARCHAR(40) NOT NULL,
    provider_transaction_id VARCHAR(255) UNIQUE,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    paid_at TIMESTAMP,
    raw_response JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- ================================================================
-- 3. Kenh tich hop va webhook event
-- ================================================================

CREATE TABLE IF NOT EXISTS channels (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    channel_type VARCHAR(30) NOT NULL,
    name VARCHAR(255) NOT NULL,
    external_account_id VARCHAR(255) NOT NULL,
    access_token TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    config JSONB,
    connected_at TIMESTAMP,
    disconnected_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_channels_business_type_account
        UNIQUE (business_id, channel_type, external_account_id)
);

CREATE TABLE IF NOT EXISTS channel_events (
    id SERIAL PRIMARY KEY,
    channel_id INTEGER NOT NULL REFERENCES channels(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    external_event_id VARCHAR(255) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'received',
    error_message TEXT,
    received_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP,
    CONSTRAINT uq_channel_events_channel_external
        UNIQUE (channel_id, external_event_id)
);

-- ================================================================
-- 4. CRM: customers, conversations, messages
-- ================================================================

CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    channel VARCHAR(30) NOT NULL,
    external_user_id VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    email VARCHAR(255),
    phone VARCHAR(40),
    address TEXT,
    avatar_url VARCHAR,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_customers_business_channel_user
        UNIQUE (business_id, channel, external_user_id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    channel_id INTEGER REFERENCES channels(id) ON DELETE SET NULL,
    channel VARCHAR(30) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'open',
    priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_message_at TIMESTAMP,
    closed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS conversation_assignments (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    assigned_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    assignment_type VARCHAR(30) NOT NULL DEFAULT 'manual',
    assigned_at TIMESTAMP DEFAULT NOW(),
    unassigned_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    sender_type VARCHAR(20) NOT NULL DEFAULT 'customer',
    sender_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    channel VARCHAR(30) NOT NULL,
    external_user_id VARCHAR(255),
    external_message_id VARCHAR(255) UNIQUE,
    direction VARCHAR(20) NOT NULL DEFAULT 'inbound',
    content TEXT,
    media_type VARCHAR(30),
    media_url TEXT,
    raw_payload JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'received',
    metadata JSONB,
    received_at TIMESTAMP DEFAULT NOW(),
    sent_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tags (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    color VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_tags_business_name UNIQUE (business_id, name)
);

CREATE TABLE IF NOT EXISTS conversation_tags (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_conversation_tags_pair UNIQUE (conversation_id, tag_id)
);

-- ================================================================
-- 5. San pham va don hang
-- ================================================================

CREATE TABLE IF NOT EXISTS products (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    sku VARCHAR(80) NOT NULL,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    price NUMERIC(12, 2) NOT NULL DEFAULT 0,
    stock_quantity INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'active',
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_products_business_sku UNIQUE (business_id, sku)
);

CREATE TABLE IF NOT EXISTS orders (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL REFERENCES businesses(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE RESTRICT,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    order_number VARCHAR(60) NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'draft',
    total_amount NUMERIC(12, 2) NOT NULL DEFAULT 0,
    shipping_address TEXT,
    shipping_phone VARCHAR(40),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_orders_business_number UNIQUE (business_id, order_number)
);

CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
    quantity INTEGER NOT NULL DEFAULT 1,
    unit_price NUMERIC(12, 2) NOT NULL,
    line_total NUMERIC(12, 2) NOT NULL
);

-- ================================================================
-- 6. Kho tri thuc va Chatbot
-- ================================================================

CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    filename VARCHAR(500) NOT NULL,
    file_type VARCHAR(30) NOT NULL,
    file_size INTEGER NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    chunk_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    uploaded_at TIMESTAMP DEFAULT NOW(),
    processed_at TIMESTAMP
);

-- Model local hien tai dung 768 chieu.
-- Neu dung Gemini 3072 chieu, can tao migration rieng cho vector column.
CREATE TABLE IF NOT EXISTS document_chunks (
    id SERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    embedding vector(768),
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chatbot_configs (
    id SERIAL PRIMARY KEY,
    business_id INTEGER NOT NULL UNIQUE REFERENCES businesses(id) ON DELETE CASCADE,
    name VARCHAR(120) NOT NULL DEFAULT 'Tro ly AI',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    handoff_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    system_prompt TEXT,
    top_k INTEGER NOT NULL DEFAULT 5,
    similarity_threshold DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    allowed_channels JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- ================================================================
-- 7. Bo sung cot cho database cu
-- ================================================================

ALTER TABLE customers
    ADD COLUMN IF NOT EXISTS business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS email VARCHAR(255);
ALTER TABLE customers ADD COLUMN IF NOT EXISTS phone VARCHAR(40);
ALTER TABLE customers ADD COLUMN IF NOT EXISTS address TEXT;
ALTER TABLE customers ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW();

ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE;
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS channel_id INTEGER REFERENCES channels(id) ON DELETE SET NULL;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal';
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS assigned_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMP;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS closed_at TIMESTAMP;

ALTER TABLE messages ADD COLUMN IF NOT EXISTS sender_type VARCHAR(20) NOT NULL DEFAULT 'customer';
ALTER TABLE messages
    ADD COLUMN IF NOT EXISTS sender_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'received';
ALTER TABLE messages ADD COLUMN IF NOT EXISTS metadata JSONB;
ALTER TABLE messages ADD COLUMN IF NOT EXISTS sent_at TIMESTAMP;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE;

ALTER TABLE customers DROP CONSTRAINT IF EXISTS uq_customers_channel_user;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_customers_business_channel_user'
    ) THEN
        ALTER TABLE customers
        ADD CONSTRAINT uq_customers_business_channel_user
        UNIQUE (business_id, channel, external_user_id);
    END IF;
END $$;

-- ================================================================
-- 8. Index phuc vu CRM/RAG
-- ================================================================

CREATE INDEX IF NOT EXISTS idx_users_business_id ON users(business_id);
CREATE INDEX IF NOT EXISTS idx_channels_business_id ON channels(business_id);
CREATE INDEX IF NOT EXISTS idx_channel_events_channel_id ON channel_events(channel_id);
CREATE INDEX IF NOT EXISTS idx_customers_business_id ON customers(business_id);
CREATE INDEX IF NOT EXISTS idx_conversations_business_id ON conversations(business_id);
CREATE INDEX IF NOT EXISTS idx_conversations_assigned_user_id ON conversations(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_documents_business_id ON documents(business_id);
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks(document_id);

COMMIT;

-- ================================================================
-- 9. Kiem tra sau khi chay
-- ================================================================

SELECT COUNT(*) AS total_business_tables
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
  AND table_name IN (
      'app_settings', 'businesses', 'users', 'service_plans',
      'subscriptions', 'payments', 'channels', 'channel_events',
      'customers', 'conversations', 'conversation_assignments', 'messages',
      'tags', 'conversation_tags', 'products', 'orders', 'order_items',
      'documents', 'document_chunks', 'chatbot_configs'
  );

SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_type = 'BASE TABLE'
  AND table_name IN (
      'app_settings', 'businesses', 'users', 'service_plans',
      'subscriptions', 'payments', 'channels', 'channel_events',
      'customers', 'conversations', 'conversation_assignments', 'messages',
      'tags', 'conversation_tags', 'products', 'orders', 'order_items',
      'documents', 'document_chunks', 'chatbot_configs'
  )
ORDER BY table_name;
