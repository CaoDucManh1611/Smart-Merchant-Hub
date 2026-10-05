import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const source = fs.readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8');
const style = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const auth = source.slice(source.indexOf('<section v-else class="login-page"'), source.indexOf('<div\n      v-if="appDialog"'));
test('authentication CTAs have no decorative arrows', () => {
  assert.doesNotMatch(auth, /[←→↗]/);
});
test('registration keeps OTP verification inline in the signup form', () => {
  assert.match(auth, /@submit.prevent="handleSignupSubmit"/);
  assert.doesNotMatch(auth, /class="signup-stepper"/);
  assert.match(auth, /class="login-submit signup-full-width signup-submit" type="submit"/);
  assert.match(auth, /signupLoading \? t\(signupStep === 'otp' \? 'Đang tạo shop\.\.\.' : 'Đang gửi mã\.\.\.'\) : t\('Đăng ký'\)/);
  assert.match(auth, /<label class="signup-full-width signup-otp-field">/);
  assert.ok(auth.indexOf('class="signup-full-width signup-otp-field"') < auth.indexOf("t('Tên shop')"));
  assert.match(auth, /class="signup-otp-input" :disabled="signupStep !== 'otp'" :required="signupStep === 'otp'"/);
  assert.match(auth, /signupForm\.otp\.length !== 6/);
  assert.doesNotMatch(auth, /signupForm\.(?:owner_name|shop_name|password)" @input="invalidateSignupOtp"/);
  assert.match(auth, /autocomplete="new-password"/);
  assert.match(auth, /autocomplete="one-time-code"/);
  assert.match(source, /onboarding\/signup\/verify/);
});

test('signup can request email verification as soon as a valid email is entered', () => {
  assert.match(source, /class="signup-otp-button" type="button" :disabled="signupLoading \|\| !validSignupEmail\(signupForm\.email\)"/);
  assert.match(source, /const payload = \{ email: signupForm\.value\.email\.trim\(\)\.toLowerCase\(\) \}/);
  assert.match(source, /owner_name: signupForm\.value\.owner_name\.trim\(\)/);
  assert.match(source, /shop_name: signupForm\.value\.shop_name\.trim\(\)/);
  assert.match(source, /password: signupForm\.value\.password/);
  assert.match(style, /\.signup-card \.signup-submit \{ min-height: 54px; justify-content: center;/);
});
