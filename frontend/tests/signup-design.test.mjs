import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
const auth = source.slice(source.indexOf('<section v-else class="login-page"'), source.indexOf('<div\n      v-if="appDialog"'));
test('authentication CTAs have no decorative arrows', () => {
  assert.doesNotMatch(auth, /[←→↗]/);
});
test('registration preserves verification and only reveals OTP after requesting it', () => {
  assert.match(auth, /@submit.prevent="handleSignupSubmit"/);
  assert.match(auth, /<label v-if="signupStep === 'otp'" class="signup-full-width">/);
  assert.match(auth, /autocomplete="new-password"/);
  assert.match(auth, /autocomplete="one-time-code"/);
  assert.match(source, /onboarding\/signup\/verify/);
});
