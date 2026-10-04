<script setup>
import { computed } from 'vue';
import BrandLogo from './BrandLogo.vue';
import { locale } from './i18n.js';
const words = computed(() => locale.value === 'en'
  ? { caption: 'Many channels. One shared workspace.', pause: 'Pause animation', resume: 'Play animation', label: 'Smart Merchant Hub and supported social channels' }
  : { caption: 'Nhiều kênh. Một không gian chung.', pause: 'Dừng chuyển động', resume: 'Bật chuyển động', label: 'Smart Merchant Hub và các kênh mạng xã hội được hỗ trợ' });
const platforms = ['Facebook', 'Instagram', 'Telegram', 'Zalo', 'TikTok', 'Shopee'];
</script>
<template>
  <div class="signup-brand-scene" :aria-label="words.label">
    <div class="signup-brand-network">
      <svg class="signup-network-lines" viewBox="0 0 460 340" aria-hidden="true">
        <ellipse cx="230" cy="170" rx="172" ry="126"/>
        <path d="M230 170L70 80M230 170L390 80M230 170L55 170M230 170L405 170M230 170L90 280M230 170L370 280"/>
      </svg>
      <div class="signup-network-center"><BrandLogo icon/><span>Smart Merchant Hub</span></div>
      <div v-for="(platform, index) in platforms" :key="platform" class="signup-network-platform" :class="'signup-network-position-' + index" :style="{ '--float-delay': index * -.7 + 's' }">
        <img :src="'/brand/platforms/' + platform.toLowerCase() + '.svg'" width="34" height="34" alt=""/>
        <span>{{ platform }}</span>
      </div>
    </div>
    <p>{{ words.caption }}</p>
  </div>
</template>
<style>
.signup-brand-scene{margin-top:24px;text-align:center}
.signup-brand-network{position:relative;width:100%;max-width:460px;height:340px;margin:auto;isolation:isolate}
.signup-network-lines{position:absolute;inset:0;width:100%;height:100%;fill:none;stroke:#94bcb0;stroke-width:1}
.signup-network-lines ellipse{stroke-dasharray:5 9;animation:signup-network-flow 20s linear infinite}
.signup-network-lines path{stroke-opacity:.6}
.signup-network-center{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;width:170px;height:154px;background:#f8fcf8;border:1px solid #c7ded3;border-radius:28px;box-shadow:0 16px 36px #24574712;z-index:2}
.signup-network-center .smh-logo-icon{width:88px;height:72px}
.signup-network-center span{font-size:12px;color:#174c45;font-weight:750;letter-spacing:-.02em}
.signup-network-platform{position:absolute;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;width:84px;height:82px;background:#ffffff;border:1px solid #d8e5dc;border-radius:18px;box-shadow:0 8px 24px #244b3810;animation:signup-platform-float 5s ease-in-out infinite;animation-delay:var(--float-delay);z-index:3}
.signup-network-platform img{width:34px;height:34px;object-fit:contain}
.signup-network-platform span{font-size:10px;font-weight:650;color:#345951}
.signup-network-position-0{left:6%;top:7%}.signup-network-position-1{right:6%;top:7%}
.signup-network-position-2{left:0;top:39%}.signup-network-position-3{right:0;top:39%}
.signup-network-position-4{left:10%;bottom:2%}.signup-network-position-5{right:10%;bottom:2%}
.signup-brand-scene>p{margin:18px 0 4px;color:#42695f;font-size:13px}
.signup-brand-scene>button{background:transparent;border:0;border-bottom:1px solid #b3cfc2;color:#50796c;font-size:11px;padding:8px 10px;min-height:44px;cursor:pointer}
.signup-brand-scene.is-paused *{animation-play-state:paused!important}
.signup-brand-scene button:focus-visible{outline:2px solid #087f78;outline-offset:3px}
@keyframes signup-platform-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-7px)}}
@keyframes signup-network-flow{to{stroke-dashoffset:-280}}
@media(prefers-reduced-motion:reduce){.signup-brand-scene *{animation:none!important}}
</style>
