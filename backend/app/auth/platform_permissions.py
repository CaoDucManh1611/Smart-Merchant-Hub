"""Control-plane permissions, independent from shop roles."""
RESOURCES = {
    'overview': 'Tổng quan', 'shops': 'Danh sách shop', 'approvals': 'Duyệt gói và ghi nhận thanh toán',
    'plans': 'Gói dịch vụ', 'support': 'Yêu cầu hỗ trợ', 'knowledge': 'Kho tư vấn dịch vụ',
    'health': 'Kết nối & cảnh báo', 'isolation': 'Tách dữ liệu shop',
    'otp-email': 'Email xác minh', 'payments': 'Cấu hình thanh toán', 'audit': 'Nhật ký nền tảng',
    'backups': 'Sao lưu & khôi phục',
}
READ_ONLY = {'overview', 'audit'}
PERMISSIONS = {f'{resource}.read' for resource in RESOURCES} | {
    f'{resource}.write' for resource in RESOURCES if resource not in READ_ONLY
} | {'backups.download', 'backups.restore'}
ROLES = {
    'owner': {'label': 'Chủ hệ thống', 'permissions': ['*']},
    'manager': {'label': 'Vận hành', 'permissions': ['overview.read', 'shops.read', 'shops.write', 'approvals.read', 'approvals.write', 'plans.read', 'support.read', 'support.write', 'knowledge.read', 'knowledge.write', 'health.read', 'audit.read']},
    'support': {'label': 'Hỗ trợ', 'permissions': ['shops.read', 'support.read', 'support.write', 'health.read']},
    'content': {'label': 'Nội dung', 'permissions': ['plans.read', 'knowledge.read', 'knowledge.write']},
    'viewer': {'label': 'Chỉ xem', 'permissions': ['overview.read', 'shops.read', 'plans.read', 'knowledge.read', 'health.read', 'audit.read']},
    'custom': {'label': 'Tùy chỉnh', 'permissions': []},
}


def permissions_for(member):
    role = getattr(member, 'platform_role', 'owner')
    if role == 'custom':
        return sorted(set(getattr(member, 'platform_permissions', None) or []) & PERMISSIONS)
    return list(ROLES.get(role, {}).get('permissions', []))


def required_permission(path: str, method: str) -> str | None:
    path = path.rstrip('/')
    if path == '/api/platform/access':
        return None
    if path.startswith('/api/platform/team'):
        return 'team.manage'
    if not path.startswith('/api/platform/'):
        return 'owner.only'
    segment = path.split('/')[3]
    resource = {
        'billing-summary': 'overview', 'shops': 'shops', 'plans': 'plans',
        'subscription-requests': 'approvals', 'support-requests': 'support',
        'support-sessions': 'support', 'knowledge': 'knowledge', 'tenant-schemas': 'isolation',
        'provider-errors': 'health', 'channel-connections': 'health', 'otp-email': 'otp-email',
        'payment-settings': 'payments', 'audit-logs': 'audit', 'backups': 'backups',
    }.get(segment)
    if segment == 'shops' and ('/payments' in path or '/subscription' in path):
        resource = 'approvals'
    if segment == 'shops' and '/provision' in path:
        resource = 'isolation'
    if resource is None:
        return 'owner.only'  # New admin endpoints fail closed until classified.
    if resource == 'backups' and path.endswith('/download'):
        return 'backups.download'
    if resource == 'backups' and path.endswith('/restore'):
        return 'backups.restore'
    return f'{resource}.{"read" if method in {"GET", "HEAD", "OPTIONS"} else "write"}'
