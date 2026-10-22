<script setup>
defineProps({ icon: Boolean });
</script>
<template>
  <img class="smh-logo" :class="{ 'smh-logo-icon': icon }" :src="icon ? '/brand/logo-mark.svg' : '/brand/logo-full.svg'" alt="Smart Merchant Hub" decoding="async" />
</template>
<style>
.smh-logo { display:block; width:240px; max-width:100%; height:auto; object-fit:contain; flex-shrink:0; }
.smh-logo-icon { width:40px; height:36px; }
.crm-app .empty-chat .empty-chat-mark { width:88px!important; height:76px!important; background:transparent!important; border:0!important; box-shadow:none!important; border-radius:0!important; }
.crm-app .empty-chat .empty-chat-mark .smh-logo-icon { display:block; width:80px!important; height:66px!important; max-width:100%; object-fit:contain!important; border-radius:0!important; padding:0!important; background:transparent!important; }
.smh-brand .smh-logo { width:225px; }.smh-brand small { margin-top:5px; }
.smh-window-top .smh-logo-icon { width:19px;height:18px; }
.crm-app .crm-brand-mark,.crm-app .login-brand-mark,.crm-app .platform-workspace-mark { background:transparent!important;border:0!important;box-shadow:none!important; }
.crm-app .brand-mini { background:transparent!important;border:0!important; }.brand-mini .smh-logo-icon { width:26px;height:24px; }
.service-brand-lockup { display:flex;align-items:center;justify-content:center;gap:10px;margin:0 auto 18px;color:#16413e; }
.service-brand-lockup .smh-logo-icon { width:40px;height:36px; }
.service-brand-lockup strong { font-size:17px;font-weight:750;letter-spacing:-.02em; }
.crm-app .service-page-layout { max-width:1320px;margin-inline:auto;padding:28px 32px 48px; }
.crm-app .service-page-hero { text-align:center;display:block;border:0;margin-bottom:25px;position:relative; }
.service-page-hero .service-brand-lockup { margin-bottom:25px; }.crm-app.crm-dark .service-brand-lockup { color:#d8ffff; }.crm-app .service-page-hero h1 { font-size:32px; }.crm-app .service-page-hero > button { position:absolute;right:0;top:0; }
.crm-app .service-page-hero :is(h1,p) { margin-inline:auto; }.crm-app:not(.platform-admin-workspace) .main > .service-page-layout { max-width:1320px;margin-inline:auto; }
.login-card > .smh-logo,.signup-card > .smh-logo { width:210px;margin-bottom:24px; }
.crm-app .service-mode-switch { position:relative;display:flex;width:min(100%,410px);max-width:100%;padding:4px;margin:0 auto 32px;border-radius:999px;background:#e4ebe7;gap:0; }
.crm-app .service-mode-option { position:relative;z-index:1;display:flex;flex:1 1 0;align-items:center;justify-content:center;min-width:0;min-height:48px;padding:10px 14px;border:0;border-radius:999px;box-shadow:none;background:transparent;font-size:13px;text-align:center; }
.crm-app .service-mode-option.selected { background:transparent;color:#174e49;box-shadow:none; }
.crm-app .service-page-grid.guest-pricing { display:none; }.crm-app .service-page-grid:not(.guest-pricing) { grid-template-columns:minmax(0,1fr);max-width:900px;margin-inline:auto; }.service-page-grid:not(.guest-pricing) .service-benefits-card { display:none; }
@media(max-width:600px) { .smh-brand .smh-logo { width:210px; }.crm-app .service-page-layout { padding:24px 16px; }.crm-app .service-page-hero > button { position:static;margin-top:20px; }.crm-app .service-mode-option { padding:10px 8px;font-size:12px; }.crm-app .service-page-hero h1 { font-size:27px; } }
body.crm-dark .smh-logo:not(.smh-logo-icon) { background:#f6faf7; border-radius:6px; padding:5px; }
</style>
