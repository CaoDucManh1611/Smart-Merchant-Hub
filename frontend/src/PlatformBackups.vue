<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue';
import { apiFetch } from './api-client.js';
import { locale } from './i18n.js';

const props = defineProps({ apiBase: { type: String, default: '/api' }, active: Boolean, permissions: { type: Array, default: () => ['*'] } });
const data = ref({ items: [], jobs: [], available: false });
const loading = ref(false);
const error = ref('');
const notice = ref('');
const selected = ref(null);
const confirmation = ref('');
const password = ref('');
const confirmationInput = ref(null);
let timer;
const running = computed(() => data.value.jobs.find(job => job.status === 'running'));
const busy = computed(() => loading.value || !!running.value);
const allowed = action => props.permissions.includes('*') || props.permissions.includes(`backups.${action}`);
const endpoint = suffix => `${props.apiBase}/platform/backups${suffix}`;

async function request(suffix, options) {
  const response = await apiFetch(endpoint(suffix), options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || 'Chưa thể thực hiện thao tác. Vui lòng thử lại.');
  return body;
}
function schedule() {
  clearTimeout(timer);
  if (props.active && running.value) timer = setTimeout(() => load(false), 2000);
}
async function load(showLoading = true) {
  if (showLoading) loading.value = true;
  try {
    const previous = running.value?.id;
    data.value = await request('');
    if (previous) {
      const completed = data.value.jobs.find(job => job.id === previous);
      if (completed?.status === 'succeeded') notice.value = completed.kind === 'restore' ? 'Đã khôi phục. Hãy đăng nhập lại để tiếp tục.' : 'Tác vụ đã hoàn tất.';
      if (completed?.status === 'failed') error.value = completed.error;
    }
  } catch (failure) { error.value = failure.message; }
  finally { loading.value = false; schedule(); }
}
async function start(kind, item) {
  if (busy.value) return;
  loading.value = true; error.value = ''; notice.value = '';
  try {
    const suffix = kind === 'create' ? '' : `/${item.id}/${kind}`;
    const body = kind === 'restore' ? { confirmation: confirmation.value, password: password.value } : {};
    const job = await request(suffix, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    data.value.jobs = [job, ...data.value.jobs];
    selected.value = null;
    confirmation.value = ''; password.value = '';
    notice.value = 'Đã bắt đầu tác vụ. Tiến trình được xử lý trên máy chủ.';
  } catch (failure) { error.value = failure.message; }
  finally { password.value = ''; loading.value = false; schedule(); }
}
async function download(item) {
  loading.value = true; error.value = '';
  try {
    const response = await apiFetch(endpoint(`/${item.id}/download`));
    if (!response.ok) throw new Error('Không tải được bản sao lưu.');
    const url = URL.createObjectURL(await response.blob());
    const anchor = document.createElement('a');
    anchor.href = url; anchor.download = `smart-merchant-${item.id}.zip`; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (failure) { error.value = failure.message; }
  finally { loading.value = false; }
}
async function importFile(event) {
  const file = event.target.files?.[0];
  if (!file || busy.value) return;
  loading.value = true; error.value = ''; notice.value = '';
  try {
    const body = new FormData(); body.append('file', file);
    await request('/import', { method: 'POST', body });
    await load(false);
    notice.value = 'Đã nhập bản sao lưu. Chọn Kiểm tra trước khi khôi phục.';
  } catch (failure) { error.value = failure.message; }
  finally { loading.value = false; event.target.value = ''; }
}
async function chooseRestore(item) {
  selected.value = item; confirmation.value = ''; password.value = '';
  await nextTick(); confirmationInput.value?.focus();
}
const date = value => new Intl.DateTimeFormat(locale.value === 'en' ? 'en-US' : 'vi-VN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Bangkok' }).format(new Date(value));
const verified = item => data.value.jobs.find(job => job.kind === 'verify' && job.backup_id === item.id && job.status === 'succeeded');
const size = value => `${(Number(value || 0) / 1024 / 1024).toFixed(1)} MB`;
watch(() => props.active, value => { if (value) load(); else clearTimeout(timer); }, { immediate: true });
onBeforeUnmount(() => clearTimeout(timer));
</script>

<template>
  <article id="admin-backups" class="platform-admin-panel backups-panel" :aria-busy="busy">
    <header class="backup-heading">
      <div><h3>Sao lưu & khôi phục</h3><p>Lưu dữ liệu hệ thống để khôi phục khi cần.</p></div>
      <button type="button" class="backup-icon-button" :disabled="busy" aria-label="Tải lại danh sách" :title="$t('Tải lại danh sách')" @click="load()"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" /></svg></button>
    </header>

    <section class="backup-toolbar" aria-labelledby="backup-create-heading">
      <span class="backup-toolbar-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 4h16v16H4zM8 4v7h8V4M8 20v-5h8v5" /></svg></span>
      <div class="backup-toolbar-copy"><h4 id="backup-create-heading">Lưu bản sao dữ liệu</h4><p>Dữ liệu quản trị, các shop, kho tri thức và tệp tải lên.</p></div>
      <div class="backup-actions">
        <button type="button" class="backup-button backup-primary" :disabled="busy || !data.available || !allowed('write')" @click="start('create')"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>{{ running?.kind === 'create' ? 'Đang tạo bản sao…' : 'Tạo bản sao lưu' }}</button>
        <label class="backup-button backup-import" :class="{ 'is-disabled': busy || !data.available || !allowed('write') }"><input class="backup-file-input" type="file" accept=".zip,application/zip" aria-label="Nhập bản sao đã tải xuống" :disabled="busy || !data.available || !allowed('write')" @change="importFile" /><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 16V4m-4 4 4-4 4 4M4 15v5h16v-5" /></svg>Nhập bản sao</label>
      </div>
    </section>
    <div class="backup-help"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" /><path d="M12 8v.1M12 11v5" /></svg><p>Bản sao không chứa tệp .env và khóa mã hóa. Hãy lưu riêng các thông tin này; chỉ nhập bản sao do hệ thống tạo.</p></div>

    <p v-if="error" role="alert" class="settings-notice team-error">{{ error }}</p>
    <p v-if="notice" role="status" class="settings-notice">{{ notice }}</p>
    <p v-if="!data.available && !loading" class="settings-notice">{{ data.reason || 'Chức năng chưa sẵn sàng.' }}</p>
    <div v-if="running" role="status" aria-live="polite" class="backup-progress"><strong>{{ running.stage }}</strong><p>Máy chủ đang xử lý. Việc nhận thay đổi mới và tác vụ nền sẽ tạm dừng trong thời gian này.</p></div>

    <form v-if="selected" class="backup-restore" @submit.prevent="start('restore', selected)">
      <fieldset :disabled="busy">
        <legend>Khôi phục bản sao ngày {{ date(selected.created_at) }}</legend>
        <p>Dữ liệu hiện tại sẽ được thay bằng bản sao đã chọn. Hệ thống sẽ kiểm chứng trên database tạm và tạo bản sao an toàn trước khi ghi đè. Các phiên đăng nhập sẽ kết thúc.</p>
        <div class="backup-confirm-fields"><label>Nhập KHÔI PHỤC để xác nhận<input ref="confirmationInput" v-model="confirmation" required autocomplete="off" /></label><label>Mật khẩu quản trị hiện tại<input v-model="password" type="password" required autocomplete="current-password" /></label></div>
        <div class="backup-actions"><button type="submit" class="backup-button backup-danger" :disabled="confirmation !== 'KHÔI PHỤC' || !password">Xác nhận khôi phục</button><button type="button" class="backup-button" @click="selected = null; password = ''; confirmation = ''">Hủy</button></div>
      </fieldset>
    </form>

    <div class="backup-library-heading"><h4>Bản sao đã lưu <span>{{ data.items.length }}</span></h4><small>Tải xuống để lưu thêm một bản trên thiết bị khác.</small></div>
    <div v-if="!data.items.length && !loading" class="backup-empty"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16v14H4zM3 3h18v4H3zM9 11h6" /></svg><h4>Chưa có bản sao lưu</h4><p>Chọn “Tạo bản sao lưu” để lưu dữ liệu hiện tại.</p></div>
    <ul v-if="data.items.length" class="backup-list">
      <li v-for="item in data.items" :key="item.id">
        <div class="backup-card-heading">
          <span class="backup-document-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 7h16v14H4zM3 3h18v4H3zM9 11h6" /></svg></span>
          <div class="backup-card-title"><h4>{{ date(item.created_at) }}</h4><span v-if="item.label === 'before_restore'" class="backup-tag">Bản an toàn trước khôi phục</span><p>{{ size(item.size) }} <span aria-hidden="true">·</span> {{ item.database_count }} cơ sở dữ liệu <span aria-hidden="true">·</span> {{ item.file_count }} tệp tải lên</p></div>
          <span class="backup-status" :class="{ 'is-verified': verified(item) }"><svg v-if="verified(item)" viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4 10-10" /></svg>{{ verified(item) ? 'Đã kiểm chứng' : 'Chưa kiểm chứng' }}</span>
        </div>
        <div class="backup-card-footer">
          <details class="backup-details"><summary>Chi tiết bản sao<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4" /></svg></summary><dl><dt>Mã bản sao</dt><dd><code>{{ item.id }}</code></dd><template v-if="verified(item)"><dt>Đã kiểm chứng trên database tạm</dt><dd>{{ date(verified(item).verified_at) }}</dd></template></dl></details>
          <div class="backup-actions"><button type="button" class="backup-button" :disabled="busy || !allowed('download')" @click="download(item)"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5" /></svg>Tải xuống</button><button type="button" class="backup-button" :disabled="busy || !data.available || !allowed('write')" @click="start('verify', item)">Kiểm tra</button><button type="button" class="backup-button backup-danger" :disabled="busy || !data.available || !allowed('restore')" @click="chooseRestore(item)">Khôi phục</button></div>
        </div>
      </li>
    </ul>

    <details v-if="data.jobs.length" class="backup-history"><summary><span>Lịch sử tác vụ <small>{{ data.jobs.length }}</small></span><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4" /></svg></summary><ul><li v-for="job in data.jobs" :key="job.id"><div class="backup-job-heading"><strong>{{ { create: 'Sao lưu', verify: 'Kiểm tra', restore: 'Khôi phục' }[job.kind] }}</strong><span class="backup-job-status" :class="`job-${job.status}`">{{ { running: 'Đang xử lý', succeeded: 'Hoàn tất', failed: 'Thất bại' }[job.status] }}</span></div><small>{{ date(job.created_at) }}</small><p v-if="job.error" role="alert">{{ job.error }}</p><p v-if="job.maintenance_required">Hệ thống vẫn giữ chế độ bảo trì. Cần phục hồi từ bản an toàn {{ job.safety_backup_id }}.</p></li></ul></details>
  </article>
</template>

<style scoped>
.backups-panel { color:var(--admin-ink); }
.backups-panel p { line-height:1.6; overflow-wrap:anywhere; color:var(--admin-muted); }
.backups-panel svg { width:21px; height:21px; fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; flex-shrink:0; }
.backup-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding-bottom:20px; margin-bottom:20px; border-bottom:1px solid var(--admin-line); }
.backup-heading h3 { margin:0; }
.backup-heading p { margin:6px 0 0; font-size:14px; }
.backup-icon-button { display:grid; place-items:center; flex-shrink:0; width:44px; height:44px; padding:0; border:1px solid var(--admin-line); border-radius:10px; background:var(--admin-surface); color:var(--admin-muted); cursor:pointer; }
.backup-toolbar { display:flex; align-items:center; flex-wrap:wrap; gap:16px; padding:20px; border:1px solid var(--admin-line); border-radius:12px; background:var(--admin-soft); }
.backup-toolbar-icon,.backup-document-icon { display:grid; place-items:center; flex-shrink:0; width:44px; height:44px; border:1px solid var(--admin-line); border-radius:10px; background:var(--admin-surface); color:var(--admin-accent); }
.backup-toolbar-copy { flex:1; min-width:180px; }
.backup-toolbar-copy h4 { margin:0; font-size:15px; }
.backup-toolbar-copy p { margin:5px 0 0; font-size:12px; }
.backup-actions { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
.backup-button { position:relative; display:inline-flex; align-items:center; justify-content:center; gap:7px; box-sizing:border-box; min-height:44px; padding:9px 13px; border:1px solid var(--admin-line); border-radius:8px; color:var(--admin-ink); background:var(--admin-surface); font:inherit; font-size:13px; font-weight:550; cursor:pointer; }
.backup-button svg { width:17px; height:17px; }
.backup-primary { background:var(--admin-accent); border-color:var(--admin-accent); color:var(--admin-surface); }
.backup-danger { background:var(--admin-danger-surface); border-color:var(--admin-danger); color:var(--admin-danger); }
.backup-button:hover:not(:disabled):not(.is-disabled),.backup-icon-button:hover:not(:disabled) { filter:brightness(.95); }
.backup-button:disabled,.is-disabled,button:disabled { opacity:.5; cursor:not-allowed; }
.backup-file-input { position:absolute; width:1px; height:1px; padding:0; margin:0; opacity:0; overflow:hidden; }
.backup-import:focus-within { outline:2px solid var(--admin-accent); outline-offset:3px; }
.backup-help { display:flex; align-items:flex-start; gap:8px; margin:12px 0 0; color:var(--admin-muted); }
.backup-help svg { width:16px; height:16px; margin-top:3px; }
.backup-help p { margin:0; font-size:12px; }
.backup-progress { margin:16px 0; padding:16px; background:var(--admin-soft); border:1px solid var(--admin-line); border-left:3px solid var(--admin-accent); border-radius:8px; }
.backup-progress p { margin:5px 0 0; font-size:13px; }
.backup-library-heading { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin:26px 0 14px; }
.backup-library-heading h4 { display:flex; align-items:center; gap:9px; margin:0; font-size:15px; }
.backup-library-heading h4 span,.backup-history summary small { display:inline-grid; place-items:center; min-width:25px; height:25px; padding:0 5px; box-sizing:border-box; border-radius:7px; background:var(--admin-soft); color:var(--admin-muted); font-size:12px; font-weight:500; }
.backup-library-heading small { color:var(--admin-muted); font-size:12px; }
.backup-list,.backup-history ul { list-style:none; padding:0; margin:0; display:grid; gap:12px; }
.backup-list>li { min-width:0; padding:18px; border:1px solid var(--admin-line); border-radius:12px; }
.backup-card-heading { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.backup-document-icon { border:0; background:var(--admin-soft); }
.backup-card-title { flex:1; min-width:160px; }
.backup-card-title h4 { margin:0; font-size:14px; }
.backup-card-title p { margin:6px 0 0; font-size:12px; }
.backup-card-title p span { padding-inline:4px; }
.backup-tag { display:inline-block; margin-top:5px; font-size:12px; color:var(--admin-muted); }
.backup-status { display:inline-flex; align-items:center; gap:5px; padding:5px 9px; border:1px solid var(--admin-line); border-radius:7px; color:var(--admin-muted); font-size:12px; }
.backup-status.is-verified { color:var(--admin-accent); background:var(--admin-soft); }
.backup-status svg { width:15px; height:15px; }
.backup-card-footer { display:flex; align-items:flex-start; flex-wrap:wrap; justify-content:space-between; gap:12px; margin-top:16px; padding-top:12px; border-top:1px solid var(--admin-line); }
.backup-details { flex:1; min-width:180px; }
summary { display:flex; align-items:center; gap:7px; min-height:44px; cursor:pointer; list-style:none; font-size:13px; }
summary::-webkit-details-marker { display:none; }
summary svg { width:16px!important; height:16px!important; }
details[open]>summary>svg { transform:rotate(180deg); }
.backup-details summary { width:fit-content; color:var(--admin-accent); }
.backup-details dl { margin:0; font-size:12px; }
.backup-details dt { margin:9px 0 4px; color:var(--admin-muted); }
.backup-details dd { margin:0; overflow-wrap:anywhere; }
.backup-details code { font-size:11px; }
.backup-empty { padding:28px 20px; border:1px solid var(--admin-line); border-radius:12px; text-align:center; }
.backup-empty>svg { width:30px; height:30px; color:var(--admin-muted); }
.backup-empty h4 { margin:12px 0 0; font-size:15px; }
.backup-empty p { margin:7px 0 0; font-size:13px; }
.backup-restore { margin:20px 0; padding:20px; border:1px solid var(--admin-danger); border-radius:12px; background:var(--admin-danger-surface); }
.backup-restore fieldset { border:0; padding:0; min-width:0; }
.backup-restore legend { font-size:15px; font-weight:650; }
.backup-restore p { margin:10px 0 0; font-size:13px; }
.backup-confirm-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:16px; }
.backup-restore label { display:grid; gap:8px; margin:16px 0; font-size:13px; }
.backup-restore input { box-sizing:border-box; width:100%; min-width:0; padding:12px; background:var(--admin-surface); color:var(--admin-ink); border:1px solid var(--admin-line); border-radius:8px; font:inherit; }
.backup-history { margin-top:20px; padding-top:8px; border-top:1px solid var(--admin-line); }
.backup-history>summary { justify-content:space-between; }
.backup-history>summary>span { display:flex; align-items:center; gap:8px; font-weight:550; }
.backup-history ul { margin-top:8px; }
.backup-history li { padding:12px 14px; border:1px solid var(--admin-line); border-radius:8px; font-size:13px; }
.backup-job-heading { display:flex; align-items:center; gap:12px; justify-content:space-between; }
.backup-history li>small { display:block; margin-top:5px; color:var(--admin-muted); }
.backup-history li p { margin:8px 0 0; }
.backup-job-status { font-size:12px; color:var(--admin-muted); }
.job-succeeded { color:var(--admin-accent); }
.job-failed { color:var(--admin-danger); }
.backups-panel :is(input,button,summary):focus-visible { outline:2px solid var(--admin-accent); outline-offset:3px; }
@media(max-width:720px) { .backup-toolbar>.backup-actions { flex-basis:100%; } .backup-toolbar>.backup-actions>* { flex:1; } }
@media(max-width:540px) { .backup-toolbar { padding:16px; gap:12px; } .backup-card-heading { align-items:flex-start; } .backup-status { margin-left:56px; } .backup-card-footer>.backup-actions { width:100%; } .backup-card-footer>.backup-actions button { flex:1; padding-inline:9px; } .backup-details { flex-basis:100%; } .backup-restore { padding:14px; } .backup-confirm-fields { grid-template-columns:1fr; gap:0; } .backup-confirm-fields label { margin:10px 0; } }
</style>
