const actionLabels = {
  platform_plan_created: "Đã tạo gói dịch vụ",
  platform_plan_updated: "Đã cập nhật gói dịch vụ",
  platform_plan_deleted: "Đã xóa gói dịch vụ",
  platform_subscription_approved: "Đã duyệt đăng ký gói dịch vụ",
  platform_subscription_rejected: "Đã từ chối đăng ký gói dịch vụ",
  platform_subscription_updated: "Đã cập nhật đăng ký gói dịch vụ",
  platform_payment_recorded: "Đã ghi nhận thanh toán",
  platform_payment_updated: "Đã cập nhật thanh toán",
  platform_status_changed: "Đã thay đổi trạng thái cửa hàng",
  platform_privacy_export_queued: "Đã tiếp nhận yêu cầu xuất dữ liệu",
  platform_privacy_anonymize_queued: "Đã tiếp nhận yêu cầu ẩn danh dữ liệu",
  platform_privacy_delete_queued: "Đã tiếp nhận yêu cầu xóa dữ liệu",
  platform_tenant_schema_registered: "Đã đăng ký khu vực dữ liệu cửa hàng",
  platform_tenant_schema_staged: "Đã chuẩn bị khu vực dữ liệu cửa hàng",
};

const resourceLabels = {
  service_plan: "Gói dịch vụ",
  subscription: "Đăng ký gói dịch vụ",
  subscription_payment: "Thanh toán gói dịch vụ",
  business: "Cửa hàng",
  data_lifecycle_request: "Yêu cầu xử lý dữ liệu",
  tenant_schema_registry: "Khu vực dữ liệu cửa hàng",
  platform: "Nền tảng",
};

export function platformAuditActionLabel(action) {
  return actionLabels[action] || "Hoạt động quản trị khác";
}

export function platformAuditResourceLabel(type) {
  return resourceLabels[type] || "Đối tượng quản trị";
}
