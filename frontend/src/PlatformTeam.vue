<script setup>
import { computed, ref, watch } from 'vue';
import { apiFetch } from './api-client.js';
import { formatDateTime } from './i18n.js';
const props = defineProps({ apiBase: { type: String, default: '/api' }, active: Boolean, adminId: Number });
const data = ref({ items: [], roles: {}, resources: {}, permissions: [], history: [] });
const busy = ref(false), error = ref(''), notice = ref(''), editing = ref(null);
const blank = () => ({ full_name: '', email: '', password: '', role: 'support', permissions: [], is_active: true });
const form = ref(blank());
const effectivePermissions = computed(() => form.value.role === 'custom' ? form.value.permissions : data.value.roles[form.value.role]?.permissions || []);
async function request(path, options) {
  const response = await apiFetch(`${props.apiBase}/platform/team${path}`, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || 'Chưa thể cập nhật đội ngũ quản trị.');
  return body;
}
async function load() {
  busy.value = true; error.value = '';
  try { data.value = await request(''); }
  catch (failure) { error.value = failure.message; }
  finally { busy.value = false; }
}
function edit(item) {
  editing.value = item.user_id;
  form.value = { full_name: item.full_name, email: item.email, password: '', role: item.role, permissions: item.role === 'custom' ? [...item.permissions] : [], is_active: item.is_active };
  notice.value = ''; error.value = '';
}
function cancel() { editing.value = null; form.value = blank(); }
function togglePermission(code, checked) {
  const selected = new Set(form.value.permissions), resource = code.split('.')[0];
  if (checked) { selected.add(code); selected.add(`${resource}.read`); }
  else if (code.endsWith('.read')) { for (const value of selected) if (value.startsWith(`${resource}.`)) selected.delete(value); }
  else selected.delete(code);
  form.value.permissions = [...selected];
}
async function save() {
  if (busy.value) return;
  busy.value = true; error.value = ''; notice.value = '';
  try {
    const body = editing.value ? { role: form.value.role, permissions: form.value.permissions, is_active: form.value.is_active } : { ...form.value };
    await request(editing.value ? `/${editing.value}` : '', { method: editing.value ? 'PATCH' : 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    notice.value = editing.value ? 'Đã cập nhật quyền. Tài khoản được thay đổi cần đăng nhập lại.' : 'Đã tạo tài khoản nội bộ. Chuyển thông tin đăng nhập cho đúng người sử dụng.';
    cancel(); await load();
  } catch (failure) { error.value = failure.message; }
  finally { busy.value = false; form.value.password = ''; }
}
watch(() => props.active, value => { if (value) load(); }, { immediate: true });
</script>

<template>
  <article id="admin-team" class="platform-admin-panel platform-staff" :aria-busy="busy">
    <div class="staff-heading"><div><h3>Đội ngũ quản trị</h3><p>Cấp quyền cho người vận hành nền tảng. Quyền này độc lập với nhân viên của các shop.</p></div><button type="button" class="staff-button" :disabled="busy" @click="load">Tải lại danh sách</button></div>
    <p v-if="error" role="alert" class="settings-notice team-error">{{ error }}</p><p v-if="notice" role="status" class="settings-notice">{{ notice }}</p>
    <ul class="staff-list"><li v-for="item in data.items" :key="item.user_id"><div class="staff-avatar" aria-hidden="true">{{ item.full_name.slice(0,1).toUpperCase() }}</div><div class="staff-person"><strong>{{ item.full_name }} <small v-if="item.user_id === adminId">(Bạn)</small></strong><p>{{ item.email }}</p></div><span class="staff-role">{{ data.roles[item.role]?.label || item.role }}</span><span class="staff-state">{{ item.is_active ? 'Đang hoạt động' : 'Đã khóa quyền admin' }}</span><button type="button" class="staff-button" :disabled="busy || item.user_id === adminId" @click="edit(item)">Phân quyền</button></li></ul>
    <form class="staff-form" @submit.prevent="save"><h4>{{ editing ? 'Điều chỉnh quyền quản trị' : 'Tạo tài khoản nội bộ' }}</h4><fieldset :disabled="busy">
      <div class="staff-fields"><label>Họ và tên<input v-model.trim="form.full_name" required minlength="2" maxlength="255" :disabled="!!editing" autocomplete="off" /></label><label>Email đăng nhập<input v-model.trim="form.email" required type="email" maxlength="255" :disabled="!!editing" autocomplete="off" /></label><label v-if="!editing">Mật khẩu ban đầu<input v-model="form.password" required type="password" minlength="12" maxlength="256" autocomplete="new-password" /><small>Ít nhất 12 ký tự, gồm 3 nhóm chữ thường, chữ hoa, số hoặc ký tự đặc biệt.</small></label><label>Vai trò quản trị<select v-model="form.role"><option v-for="(role, code) in data.roles" :key="code" :value="code">{{ role.label }}</option></select></label></div>
      <p v-if="form.role === 'owner'" class="staff-owner-note">Chủ hệ thống có toàn quyền, bao gồm cấp quyền quản trị, tải và khôi phục dữ liệu.</p>
      <div v-if="form.role !== 'owner'" class="staff-permission-grid"><div class="staff-permission-header"><strong>Phạm vi truy cập</strong><small>{{ form.role === 'custom' ? 'Chọn quyền theo từng mục' : 'Chọn Tùy chỉnh để thay đổi từng quyền' }}</small></div><div v-for="(name, resource) in data.resources" :key="resource" class="staff-permission-row"><strong>{{ name }}</strong><label><input type="checkbox" :checked="effectivePermissions.includes(`${resource}.read`)" :disabled="form.role !== 'custom'" @change="togglePermission(`${resource}.read`, $event.target.checked)" /> Xem</label><label v-if="data.permissions.includes(`${resource}.write`)"><input type="checkbox" :checked="effectivePermissions.includes(`${resource}.write`)" :disabled="form.role !== 'custom'" @change="togglePermission(`${resource}.write`, $event.target.checked)" /> Thao tác</label><template v-if="resource === 'backups'"><label><input type="checkbox" :checked="effectivePermissions.includes('backups.download')" :disabled="form.role !== 'custom'" @change="togglePermission('backups.download', $event.target.checked)" /> Tải bản sao</label><label><input type="checkbox" :checked="effectivePermissions.includes('backups.restore')" :disabled="form.role !== 'custom'" @change="togglePermission('backups.restore', $event.target.checked)" /> Khôi phục</label></template></div></div>
      <label class="staff-active"><input v-model="form.is_active" type="checkbox" /> Cho phép truy cập trang admin</label>
      <div class="staff-actions"><button type="submit" class="staff-button staff-primary">{{ busy ? 'Đang lưu…' : editing ? 'Lưu phân quyền' : 'Tạo tài khoản' }}</button><button v-if="editing" type="button" class="staff-button" @click="cancel">Hủy</button></div>
    </fieldset></form>
    <details v-if="data.history.length" class="staff-history"><summary>Lịch sử phân quyền</summary><ul><li v-for="(event, index) in data.history" :key="index">{{ formatDateTime(event.created_at) }} · {{ event.action === 'created' ? 'Tạo tài khoản' : 'Cập nhật quyền' }} #{{ event.subject_id }} · {{ $t('Người thực hiện') }} #{{ event.actor_id }}</li></ul></details>
  </article>
</template>

<style scoped>
.platform-staff { color:var(--admin-ink); }
.staff-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:16px; }
.staff-heading h3 { margin:0; }.staff-heading p,.staff-person p { color:var(--admin-muted); line-height:1.6; margin:6px 0; font-size:13px; }
.staff-list { list-style:none; padding:0; margin:20px 0; }.staff-list>li { display:flex; flex-wrap:wrap; gap:12px; align-items:center; padding:15px 0; border-top:1px solid var(--admin-line); }
.staff-avatar { display:grid; place-items:center; width:40px; height:40px; background:var(--admin-soft); color:var(--admin-accent); border-radius:50%; }.staff-person { flex:1; min-width:140px; overflow-wrap:anywhere; }.staff-person small { color:var(--admin-muted); }
.staff-role,.staff-state { font-size:12px; }.staff-role { background:var(--admin-soft); border-radius:7px; padding:6px 10px; }.staff-state { color:var(--admin-muted); }
.staff-button { min-height:44px; padding:9px 14px; border:1px solid var(--admin-line); border-radius:8px; background:var(--admin-surface); color:var(--admin-ink); font:inherit; font-size:13px; cursor:pointer; }.staff-primary { background:var(--admin-accent); color:var(--admin-surface); border-color:var(--admin-accent); }.staff-button:disabled { opacity:.5; cursor:not-allowed; }
.staff-form { padding:18px; border:1px solid var(--admin-line); border-radius:12px; margin-top:20px; }.staff-form h4 { margin:0 0 18px; }.staff-form fieldset { border:0; padding:0; min-width:0; }.staff-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }.staff-fields label { display:grid; gap:8px; font-size:13px; }.staff-fields input,.staff-fields select { box-sizing:border-box; width:100%; min-width:0; min-height:44px; padding:10px; border:1px solid var(--admin-line); border-radius:8px; background:var(--admin-surface); color:var(--admin-ink); font:inherit; }.staff-fields small { color:var(--admin-muted); line-height:1.5; }
.staff-permission-grid { margin:20px 0; border:1px solid var(--admin-line); border-radius:10px; overflow:hidden; }.staff-permission-header { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px; padding:14px; background:var(--admin-soft); font-size:13px; }.staff-permission-header small { color:var(--admin-muted); }.staff-permission-row { display:flex; align-items:center; flex-wrap:wrap; gap:12px; padding:9px 14px; border-top:1px solid var(--admin-line); font-size:12px; }.staff-permission-row>strong { min-width:170px; flex:1; font-weight:550; }.staff-permission-row label,.staff-active { display:flex; align-items:center; gap:7px; min-height:44px; cursor:pointer; }.staff-permission-row input,.staff-active input { width:17px; height:17px; accent-color:var(--admin-accent); }.staff-active { font-size:13px; margin:16px 0; }.staff-owner-note { padding:14px; background:var(--admin-soft); font-size:13px; line-height:1.7; }.staff-actions { display:flex; gap:8px; }
.staff-history { margin-top:20px; border-top:1px solid var(--admin-line); }.staff-history summary { cursor:pointer; padding:16px 0; }.staff-history ul { padding-left:18px; color:var(--admin-muted); font-size:12px; line-height:1.8; }
:is(input,select,button,summary):focus-visible { outline:2px solid var(--admin-accent); outline-offset:3px; }
@media(max-width:640px) { .staff-fields { grid-template-columns:1fr; }.staff-permission-row>strong { flex-basis:100%; }.staff-list>li { align-items:flex-start; } }
</style>
