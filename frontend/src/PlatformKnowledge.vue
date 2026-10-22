<script setup>
import { computed, ref, watch } from 'vue';
import { apiFetch } from './api-client.js';
import { formatDateTime } from './i18n.js';

const props = defineProps({ apiBase: { type: String, default: '/api' }, active: Boolean, canWrite: { type: Boolean, default: true } });
const items = ref([]), loading = ref(false), error = ref(''), notice = ref('');
const publishedCount = computed(() => items.value.filter(item => item.published).length);
const endpoint = path => `${props.apiBase}/platform/knowledge${path}`;
async function request(path, options) {
  const response = await apiFetch(endpoint(path), options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'Chưa thể cập nhật kho tư vấn.');
  return body;
}
async function load() {
  loading.value = true; error.value = '';
  try { items.value = (await request('')).items; }
  catch (failure) { error.value = failure.message; }
  finally { loading.value = false; }
}
async function upload(event) {
  const file = event.target.files?.[0];
  if (!file || loading.value) return;
  if (file.size > 10 * 1024 * 1024) { error.value = 'Tài liệu tối đa 10 MB.'; event.target.value = ''; return; }
  loading.value = true; error.value = ''; notice.value = '';
  try {
    const body = new FormData(); body.append('file', file);
    const item = await request('/upload', { method: 'POST', body });
    items.value = [item, ...items.value];
    notice.value = 'Đã đọc tài liệu. Xem trước rồi bật “Dùng để tư vấn” để chatbot sử dụng.';
  } catch (failure) { error.value = failure.message; }
  finally { loading.value = false; event.target.value = ''; }
}
async function publish(item, event) {
  const enabled = event.target.checked;
  loading.value = true; error.value = ''; notice.value = '';
  try {
    const result = await request(`/${item.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ published: enabled }) });
    items.value = items.value.map(row => row.id === item.id ? result : row);
    notice.value = enabled ? 'Chatbot có thể dùng tài liệu này từ câu hỏi tiếp theo.' : 'Đã ngừng dùng tài liệu này cho các câu hỏi mới.';
  } catch (failure) { error.value = failure.message; }
  finally { loading.value = false; event.target.checked = items.value.find(row => row.id === item.id)?.published ?? false; }
}
watch(() => props.active, active => { if (active) load(); }, { immediate: true });
</script>

<template>
  <article id="admin-knowledge" class="platform-admin-panel service-knowledge" :aria-busy="loading">
    <header class="knowledge-heading">
      <div><h3>Kho tư vấn gói dịch vụ</h3><p>Quản lý tài liệu giúp chatbot tư vấn đúng thông tin cho khách.</p></div>
      <button type="button" class="knowledge-refresh" :disabled="loading" aria-label="Tải lại danh sách" :title="$t('Tải lại danh sách')" @click="load">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6 7a7 7 0 0 1 12-1l2 3M4 15l2 3a7 7 0 0 0 12-1" /></svg>
      </button>
    </header>

    <section class="knowledge-upload" aria-labelledby="knowledge-upload-heading">
      <span class="knowledge-upload-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 16V4m-4 4 4-4 4 4M4 15v5h16v-5" /></svg></span>
      <div class="knowledge-upload-copy"><h4 id="knowledge-upload-heading">Thêm tài liệu tư vấn</h4><p>PDF, DOCX, TXT, Markdown <span aria-hidden="true">·</span> Tối đa 10 MB</p></div>
      <label class="knowledge-choose" :class="{ 'is-disabled': loading || !canWrite }">
        <input class="knowledge-file-input" type="file" accept=".pdf,.docx,.txt,.md" aria-label="Chọn tài liệu tư vấn gói dịch vụ" :disabled="loading || !canWrite" @change="upload" />
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg><span>Chọn tài liệu</span>
      </label>
    </section>
    <div class="knowledge-upload-note"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v.1M12 11v5" /><circle cx="12" cy="12" r="9" /></svg><p>Chỉ tải nội dung có thể chia sẻ với khách. Tài liệu mới được lưu nháp để bạn kiểm tra trước khi dùng.</p></div>

    <p v-if="error" role="alert" class="settings-notice team-error">{{ error }}</p>
    <p v-if="notice" role="status" class="settings-notice">{{ notice }}</p>
    <p v-if="loading" role="status" class="knowledge-loading">Đang cập nhật kho tư vấn…</p>

    <div class="knowledge-library-heading">
      <h4>Tài liệu trong kho <span class="knowledge-total">{{ items.length }}</span></h4>
      <div v-if="items.length" class="knowledge-counts"><span>{{ publishedCount }} đang dùng</span><span>{{ items.length - publishedCount }} bản nháp</span></div>
    </div>
    <div v-if="!items.length && !loading" class="knowledge-empty">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5" /></svg>
      <h4>Chưa có tài liệu tư vấn</h4>
      <p>Thêm chính sách, hướng dẫn hoặc câu hỏi thường gặp để chatbot tư vấn đầy đủ hơn.</p>
      <small>Chatbot vẫn có thể tra cứu giá và hạn mức gói hiện hành.</small>
    </div>
    <ul v-if="items.length" class="knowledge-list">
      <li v-for="item in items" :key="item.id">
        <div class="knowledge-document-top">
          <span class="knowledge-document-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h5" /></svg></span>
          <div class="knowledge-document-copy"><h4>{{ item.filename }}</h4><p>{{ formatDateTime(item.created_at) }} <span aria-hidden="true">·</span> {{ item.chunk_count }} đoạn nội dung</p></div>
          <span class="knowledge-status" :class="{ 'is-published': item.published }">{{ item.published ? 'Đang dùng để tư vấn' : 'Bản nháp' }}</span>
        </div>
        <div class="knowledge-document-actions">
          <details><summary>Xem trước nội dung<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 10 4 4 4-4" /></svg></summary><pre>{{ item.preview }}</pre><p v-if="item.characters > item.preview.length">Đang xem 2.500 ký tự đầu của tài liệu.</p></details>
          <label class="knowledge-publish"><input type="checkbox" :checked="item.published" :disabled="loading || !canWrite" @change="publish(item, $event)" /> Dùng để tư vấn</label>
        </div>
      </li>
    </ul>
    <p class="knowledge-footer-note">Giá và hạn mức lấy từ danh mục gói hiện hành. Kho tư vấn này tách riêng với dữ liệu của các shop.</p>
  </article>
</template>

<style scoped>
.service-knowledge { color:var(--admin-ink); }
.service-knowledge p { color:var(--admin-muted); line-height:1.6; }
.service-knowledge svg { width:22px; height:22px; fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; flex-shrink:0; }
.knowledge-heading { display:flex; align-items:flex-start; justify-content:space-between; gap:18px; padding-bottom:20px; margin-bottom:20px; border-bottom:1px solid var(--admin-line); }
.knowledge-heading h3 { margin:0; }
.knowledge-heading p { margin:6px 0 0; font-size:14px; }
.knowledge-refresh { display:grid; place-items:center; flex-shrink:0; width:44px; height:44px; padding:0; border:1px solid var(--admin-line); border-radius:10px; background:var(--admin-surface); color:var(--admin-muted); cursor:pointer; }
.knowledge-refresh:hover:not(:disabled) { background:var(--admin-soft); color:var(--admin-accent); }
.knowledge-upload { display:flex; align-items:center; flex-wrap:wrap; gap:16px; padding:22px; border:1px dashed var(--admin-line); border-radius:12px; background:var(--admin-soft); }
.knowledge-upload-icon,.knowledge-document-icon { display:grid; place-items:center; width:46px; height:46px; flex-shrink:0; border:1px solid var(--admin-line); border-radius:11px; color:var(--admin-accent); background:var(--admin-surface); }
.knowledge-upload-copy { flex:1; min-width:160px; }
.knowledge-upload-copy h4 { margin:0; font-size:15px; }
.knowledge-upload-copy p { margin:5px 0 0; font-size:13px; }
.knowledge-upload-copy p span { padding-inline:5px; }
.knowledge-choose { position:relative; display:inline-flex; align-items:center; justify-content:center; gap:7px; min-height:44px; padding:0 16px; border:1px solid var(--admin-accent); border-radius:9px; background:var(--admin-accent); color:var(--admin-surface); font-size:14px; font-weight:650; cursor:pointer; }
.knowledge-choose svg { width:18px; height:18px; }
.knowledge-choose:hover:not(.is-disabled) { filter:brightness(.94); }
.knowledge-file-input { position:absolute; width:1px; height:1px; padding:0; margin:0; opacity:0; overflow:hidden; }
.knowledge-choose:focus-within { outline:2px solid var(--admin-accent); outline-offset:4px; }
.is-disabled,button:disabled { opacity:.55; cursor:wait; }
.knowledge-upload-note { display:flex; align-items:flex-start; gap:8px; padding:12px 2px 0; color:var(--admin-muted); }
.knowledge-upload-note svg { width:16px; height:16px; margin-top:3px; }
.knowledge-upload-note p { margin:0; font-size:12px; }
.knowledge-loading { font-size:13px; }
.knowledge-library-heading { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; margin:25px 0 14px; }
.knowledge-library-heading h4 { display:flex; align-items:center; gap:9px; margin:0; font-size:15px; }
.knowledge-total { display:grid; place-items:center; min-width:25px; height:25px; padding:0 5px; box-sizing:border-box; border-radius:7px; background:var(--admin-soft); color:var(--admin-muted); font-size:12px; font-weight:500; }
.knowledge-counts { display:flex; flex-wrap:wrap; gap:14px; color:var(--admin-muted); font-size:12px; }
.knowledge-empty { padding:27px 20px; border:1px solid var(--admin-line); border-radius:12px; text-align:center; }
.knowledge-empty>svg { width:30px; height:30px; color:var(--admin-muted); margin-bottom:9px; }
.knowledge-empty h4 { margin:0; font-size:15px; font-weight:600; }
.knowledge-empty p { max-width:490px; margin:7px auto; font-size:13px; }
.knowledge-empty small { color:var(--admin-muted); font-size:12px; }
.knowledge-list { list-style:none; padding:0; margin:0; display:grid; gap:12px; }
.knowledge-list>li { min-width:0; padding:17px; border:1px solid var(--admin-line); border-radius:11px; }
.knowledge-document-top { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
.knowledge-document-icon { width:39px; height:43px; border:0; background:var(--admin-soft); border-radius:8px; }
.knowledge-document-copy { min-width:0; flex:1; }
.knowledge-document-copy h4 { margin:0; font-size:14px; overflow-wrap:anywhere; }
.knowledge-document-copy p { margin:5px 0 0; font-size:12px; }
.knowledge-status { padding:4px 9px; border:1px solid var(--admin-line); border-radius:6px; color:var(--admin-muted); font-size:12px; }
.knowledge-status.is-published { background:var(--admin-soft); color:var(--admin-accent); }
.knowledge-document-actions { display:flex; align-items:flex-start; gap:14px; margin-top:12px; border-top:1px solid var(--admin-line); }
.knowledge-document-actions details { flex:1; min-width:0; }
summary { display:flex; align-items:center; gap:7px; width:fit-content; min-height:44px; color:var(--admin-accent); cursor:pointer; font-size:13px; list-style:none; }
summary::-webkit-details-marker { display:none; }
summary svg { width:16px!important; height:16px!important; }
details[open] summary svg { transform:rotate(180deg); }
pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:260px; overflow:auto; padding:14px; margin:0; background:var(--admin-soft); border-radius:8px; font:inherit; font-size:13px; line-height:1.7; }
.knowledge-publish { display:flex; align-items:center; gap:9px; min-height:44px; width:fit-content; flex-shrink:0; color:var(--admin-ink); font-size:13px; cursor:pointer; }
.knowledge-publish input { width:17px; height:17px; accent-color:var(--admin-accent); }
.service-knowledge .knowledge-footer-note { margin:16px 0 0; padding-top:14px; border-top:1px solid var(--admin-line); font-size:12px; }
:is(input,button,summary):focus-visible { outline:2px solid var(--admin-accent); outline-offset:3px; }
@media(max-width:640px) { .knowledge-upload { padding:17px; gap:12px; } .knowledge-choose { width:100%; box-sizing:border-box; } .knowledge-upload-copy { min-width:140px; } .knowledge-document-top { align-items:flex-start; } .knowledge-status { margin-left:51px; } .knowledge-document-actions { flex-direction:column-reverse; gap:0; } .knowledge-document-actions details { width:100%; } }
</style>
