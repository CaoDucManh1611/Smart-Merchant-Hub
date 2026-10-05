import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appSource = await readFile(new URL("../src/App.vue", import.meta.url), "utf8");
const tokenSource = await readFile(new URL("../src/auth-context.js", import.meta.url), "utf8");
const styleSource = await readFile(new URL("../src/style.css", import.meta.url), "utf8");

test("password recovery opens its own screen and returns to sign in after reset", () => {
  const loginScreen = appSource.slice(appSource.indexOf('<div v-if="authView === \'login\'"'), appSource.indexOf('<div v-else-if="authView === \'forgot\'"'));
  const recoveryScreen = appSource.slice(appSource.indexOf('<div v-else-if="authView === \'forgot\'"'), appSource.indexOf('<div v-else class="login-card signup-card"'));
  assert.match(loginScreen, /v-model="loginRememberMe" type="checkbox"/);
  assert.match(loginScreen, /@click="openPasswordReset"/);
  assert.doesNotMatch(loginScreen, /password-reset-form|password-reset-panel/);
  assert.match(appSource, /function openPasswordReset\(\)[\s\S]*?authView\.value = "forgot"/);
  assert.match(recoveryScreen, /data-testid="password-reset-page"/);
  assert.match(recoveryScreen, /@submit\.prevent="requestPasswordReset"/);
  assert.match(recoveryScreen, /@submit\.prevent="completePasswordReset"/);
  assert.match(recoveryScreen, /@click="openLogin"/);
  assert.match(appSource, /passwordResetNotice\.value = t\("Mật khẩu đã được đổi\. Bạn có thể đăng nhập bằng mật khẩu mới\."\);\s*authView\.value = "login"/);
  assert.match(appSource, /Quên mật khẩu\?/);
  assert.match(appSource, /\/auth\/password-reset\/request/);
  assert.match(appSource, /\/auth\/password-reset\/complete/);
  assert.match(styleSource, /\.crm-app\.auth-locked \.login-form \.login-options-row input\[type="checkbox"\][^{]*\{[^}]*width: 17px !important;[^}]*height: 17px !important;/);
  assert.match(styleSource, /\.login-form \.login-options-row label\.login-remember \{[^}]*white-space: nowrap;/);
  assert.match(tokenSource, /window\.sessionStorage/);
  assert.match(tokenSource, /otherStorage\?\.removeItem/);
});

test("remembering sign-in keeps only one active browser token", async () => {
  class MemoryStorage {
    values = new Map();
    getItem(key) { return this.values.get(key) || null; }
    setItem(key, value) { this.values.set(key, value); }
    removeItem(key) { this.values.delete(key); }
  }
  const previousWindow = globalThis.window;
  const localStorage = new MemoryStorage();
  const sessionStorage = new MemoryStorage();
  globalThis.window = { localStorage, sessionStorage };
  try {
    const { AUTH_TOKEN_KEY, clearAuthToken, readAuthToken, storeAuthToken } = await import("../src/auth-context.js?remember-test");
    storeAuthToken("temporary-session", sessionStorage);
    assert.equal(readAuthToken(), "temporary-session");
    storeAuthToken("remembered-session", localStorage);
    assert.equal(readAuthToken(), "remembered-session");
    assert.equal(sessionStorage.getItem(AUTH_TOKEN_KEY), null);
    clearAuthToken();
    assert.equal(readAuthToken(), "");
  } finally {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  }
});
