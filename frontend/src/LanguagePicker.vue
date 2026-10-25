<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
defineProps({ value: String, label: String, dark: Boolean });
const emit = defineEmits(['change']);
const root = ref(null);
function close() { if (root.value) root.value.open = false; }
function outside(event) { if (!root.value?.contains(event.target)) close(); }
function choose(value) { emit('change', value); close(); root.value?.querySelector('summary')?.focus(); }
function escape() { close(); root.value?.querySelector('summary')?.focus(); }
onMounted(() => document.addEventListener('pointerdown', outside));
onUnmounted(() => document.removeEventListener('pointerdown', outside));
</script>
<template>
  <details ref="root" class="language-picker" :class="{ dark }" @keydown.esc.stop.prevent="escape" @focusout="event => { if (!event.currentTarget.contains(event.relatedTarget)) close(); }">
    <summary :aria-label="label"><svg aria-hidden="true"><use href="#smh-translate"/></svg></summary>
    <div class="language-options" :aria-label="label">
      <button v-for="option in [{ code:'vi', name:'Tiếng Việt' }, { code:'en', name:'English' }]" :key="option.code" type="button" :aria-pressed="value === option.code" @click="choose(option.code)"><span>{{ option.name }}</span><span aria-hidden="true">{{ value === option.code ? '✓' : '' }}</span></button>
    </div>
  </details>
</template>
<style scoped>
.language-picker { position:relative; flex:none; color:#163d3e; }
summary { display:grid; place-items:center; width:40px; height:40px; border:1px solid #d5e3de; border-radius:13px; background:#f1f5f2; cursor:pointer; list-style:none; }
summary::-webkit-details-marker { display:none; }
summary svg { width:23px; height:23px; fill:none; stroke:currentColor; }
summary:focus-visible,button:focus-visible { outline:2px solid #087e77; outline-offset:3px; }
.language-options { position:absolute; right:0; top:calc(100% + 9px); z-index:50; width:164px; padding:6px; border:1px solid #d5e3de; border-radius:14px; background:#fff; box-shadow:0 10px 28px #173d3a26; }
button { display:flex; align-items:center; justify-content:space-between; width:100%; min-height:44px; padding:10px 12px; border:0; border-radius:9px; background:transparent; color:inherit; font:inherit; font-size:14px; cursor:pointer; }
button[aria-pressed="true"] { background:#e5f3ee; color:#086b62; font-weight:700; }
button:hover { background:#f0f5f2; }
.dark { color:#edf1ee; }
.dark summary,.dark .language-options { background:#222d2e; border-color:#485957; }
.dark button[aria-pressed="true"],.dark button:hover { color:#bce9dc; background:#314b44; }
</style>
