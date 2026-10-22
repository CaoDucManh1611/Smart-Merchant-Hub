export const ADMIN_SECTIONS = Object.freeze([
  { id: 'team', title: 'Đội ngũ & phân quyền', description: 'Quản lý tài khoản nội bộ và quyền truy cập từng mục của trang admin.', icon: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8 M18 8h4 M20 6v4 M18 15h4v6h-4z' },
  { id: 'knowledge', title: 'Kho tư vấn dịch vụ', description: 'Quản lý tài liệu công khai để chatbot tư vấn gói dịch vụ cho khách.', icon: 'M4 3h12l4 4v14H4z M16 3v5h4 M8 12h8 M8 16h6' },
  { id: 'support', title: 'Yêu cầu hỗ trợ', description: 'Tiếp nhận và phản hồi yêu cầu hỗ trợ kết nối của shop.', icon: 'M4 4h16v13H9l-5 4z M8 8h8 M8 12h5' },
  { id: 'overview', title: 'Tổng quan', description: 'Quản lý tenant, gói dịch vụ, module, kết nối và sức khỏe toàn bộ hệ thống.', icon: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z' },
  { id: 'approvals', title: 'Yêu cầu chờ duyệt', description: 'Duyệt gói để kích hoạt quyền sử dụng và bắt đầu chuẩn bị không gian dữ liệu riêng của shop.', icon: 'M9 3h6v4H9z M8 5H5v16h14V5h-3 M8 14l3 3 5-6' },
  { id: 'shops', title: 'Danh sách shop', description: 'Quản lý trạng thái và hạn mức; dữ liệu vận hành vẫn nằm trong workspace riêng.', icon: 'M3 10l2-7h14l2 7 M3 10h18 M5 10v11h14V10 M9 21v-7h6v7' },
  { id: 'plans', title: 'Gói dịch vụ', description: 'Gói quyết định hạn mức và các module được cấp cho từng tenant.', icon: 'M3 7l9-4 9 4-9 4z M3 12l9 4 9-4 M3 17l9 4 9-4' },
  { id: 'isolation', title: 'Tách kho dữ liệu theo shop', description: 'Quản lý tách kho dữ liệu theo shop, điều khiển trạng thái thử nghiệm mà không mở dữ liệu CRM sang tenant khác.', icon: 'M4 3h6v6H4z M14 15h6v6h-6z M7 9v9h7 M14 3h6v6h-6z M10 6h4' },
  { id: 'health', title: 'Kết nối & cảnh báo', description: 'Theo dõi trạng thái và cảnh báo kết nối của các kênh bán hàng.', icon: 'M3 12h4l3-7 4 14 3-7h4' },
  { id: 'otp-email', title: 'Email gửi OTP', description: 'Cấu hình một lần. Mã xác minh được tự động gửi đến email mà khách nhập khi đăng ký.', icon: 'M3 5h18v14H3z M3 5l9 7 9-7' },
  { id: 'audit', title: 'Nhật ký nền tảng', description: 'Ghi lại thao tác quản trị tenant, gói dịch vụ, thanh toán và tách dữ liệu.', icon: 'M6 3h12v18H6z M9 8h6 M9 12h6 M9 16h4' },
  { id: 'payments', title: 'Cấu hình thanh toán', description: 'Cấu hình ngân hàng nhận phí nền tảng bằng VietQR; admin đối soát tiền thực nhận.', icon: 'M3 5h18v14H3z M3 10h18 M7 15h4' },
  { id: 'backups', title: 'Sao lưu & khôi phục', description: 'Tạo, kiểm chứng và khôi phục bản sao dữ liệu quản trị, các shop và tệp tải lên.', icon: 'M4 4h16v16H4z M8 4v7h8V4 M8 20v-6h8v6' },
]);

export function adminSectionFromHash(hash) {
  return ADMIN_SECTIONS.find(section => `#admin-${section.id}` === hash)?.id || 'overview';
}

export function adminSectionHash(id) {
  return `#admin-${ADMIN_SECTIONS.find(section => section.id === id)?.id || 'overview'}`;
}

export function newestShopsFirst(shops) {
  // Shop IDs are assigned on creation; the list API does not expose created_at.
  return [...shops].sort((a, b) => Number(b.id) - Number(a.id));
}

export function subscriptionRegistrationDate(value, locale = 'vi') {
  if (!value) return locale === 'en' ? 'Not registered yet' : 'Chưa đăng ký';
  // Backend naive timestamps represent UTC, not the browser's local timezone.
  const date = new Date(/[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return '—';
  return new Intl.DateTimeFormat(locale === 'en' ? 'en-GB' : 'vi-VN', {
    timeZone: 'Asia/Ho_Chi_Minh', weekday: 'short', day: '2-digit', month: '2-digit',
    year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(date);
}
