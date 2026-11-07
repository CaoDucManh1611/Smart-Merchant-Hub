# Feature inventory theo router

Mỗi module đều được đưa vào phạm vi. Cột test là gợi ý tên gần nhau, chưa chứng minh độ phủ.

|Router|Số operation theo tag gần nhất|Tệp test ứng viên|
|---|---|---|
|appointments.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|auth.py|Xem api-inventory.json|test_auth_api.py, test_auth_security_controls.py, test_authenticated_tenant_registry_gate.py, test_authenticated_tenant_session.py, test_meta_oauth_tenant_security.py, test_webhook_oauth_security.py|
|chat.py|Xem api-inventory.json|test_chatbot_agent_tools.py, test_chatbot_answer_routing.py, test_chatbot_bandit_runtime.py, test_chatbot_followup.py, test_chatbot_runtime_api.py|
|chatbot.py|Xem api-inventory.json|test_chatbot_agent_tools.py, test_chatbot_answer_routing.py, test_chatbot_bandit_runtime.py, test_chatbot_followup.py, test_chatbot_runtime_api.py|
|commercial.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|conversations.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|customer_avatar.py|Xem api-inventory.json|test_customer_avatar.py|
|customer_collection.py|Xem api-inventory.json|test_customer_collection_flow.py|
|customers.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|documents.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|experimentation.py|Xem api-inventory.json|test_experimentation_api.py, test_experimentation_outcomes.py|
|facebook.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|instagram.py|Xem api-inventory.json|test_instagram_outbound.py, test_instagram_webhook.py|
|inventory.py|Xem api-inventory.json|test_inventory_receiving.py, test_sales_inventory_lifecycle.py|
|leads.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|local_connectors.py|Xem api-inventory.json|test_local_connectors.py|
|media.py|Xem api-inventory.json|test_legacy_meta_media_normalization.py, test_media_capabilities.py, test_media_end_to_end.py, test_media_persistence.py, test_media_proxy.py, test_media_upload_api.py, test_meta_media_contracts.py, test_zalo_media.py|
|meta_oauth.py|Xem api-inventory.json|test_meta_oauth_tenant_security.py|
|monapay_webhooks.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|notifications.py|Xem api-inventory.json|test_notifications_api.py|
|onboarding.py|Xem api-inventory.json|test_onboarding_api.py, test_onboarding_password_policy.py|
|payments.py|Xem api-inventory.json|test_order_payments.py, test_subscription_payments.py|
|platform.py|Xem api-inventory.json|test_platform_api.py, test_platform_backups.py, test_platform_otp_email.py, test_platform_payment_settings.py, test_platform_quality.py, test_platform_quota_ledger.py, test_platform_schema.py, test_platform_staff_permissions.py, test_platform_support_requests.py|
|platform_backups.py|Xem api-inventory.json|test_platform_backups.py|
|platform_knowledge.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|platform_otp_email.py|Xem api-inventory.json|test_platform_otp_email.py|
|platform_payment_settings.py|Xem api-inventory.json|test_platform_payment_settings.py|
|platform_support_requests.py|Xem api-inventory.json|test_platform_support_requests.py|
|platform_team.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|privacy.py|Xem api-inventory.json|test_privacy_api.py, test_sales_journey_privacy.py|
|purchase_orders.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|recommendations.py|Xem api-inventory.json|test_recommendations_api.py|
|reports.py|Xem api-inventory.json|test_p1_02_timeline_reports.py, test_reports_api.py|
|revenue.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|sales.py|Xem api-inventory.json|test_sales_inventory_lifecycle.py, test_sales_journey_engine.py, test_sales_journey_graph_bridge.py, test_sales_journey_integration_contract.py, test_sales_journey_policy.py, test_sales_journey_privacy.py, test_universal_sales_brain.py|
|shopee.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|subscription_payments.py|Xem api-inventory.json|test_subscription_payments.py|
|suppliers.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|support.py|Xem api-inventory.json|test_platform_support_requests.py, test_support_access.py, test_support_access_api_contract.py|
|team.py|Xem api-inventory.json|test_team_api.py|
|telegram.py|Xem api-inventory.json|test_telegram_adapter.py, test_telegram_outbound.py|
|tickets.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|tiktok.py|Xem api-inventory.json|test_tiktok_browser_profile_scan.py, test_tiktok_seller_center_bridge.py, test_tiktok_webhook.py|
|usage.py|Xem api-inventory.json|test_p1_usage_and_tenant_claims.py|
|webhooks.py|Xem api-inventory.json|test_unified_inbox_webhooks.py|
|workflows.py|Xem api-inventory.json|Cần map thủ công/test liên module|
|workspace.py|Xem api-inventory.json|test_crm_workspace_config.py, test_workspace_modules.py|
|zalo.py|Xem api-inventory.json|test_zalo_adapter.py, test_zalo_media.py, test_zalo_outbound.py, test_zalo_webhook.py|
|zalo_personal.py|Xem api-inventory.json|Cần map thủ công/test liên module|
