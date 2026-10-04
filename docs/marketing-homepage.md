# Public marketing homepage

Implemented in `frontend/src/MarketingLanding.vue`, wired into the existing anonymous home view in App.vue. Authenticated CRM, backend and database flows are unchanged.

The public-home shell is a vertical scroll container independent of the fixed-height CRM shell. Sections include hero preview, supported channels, team illustration, interactive product tour, customer context, business use cases, onboarding, FAQ, final CTA and footer. CTA arrows were removed. Existing login, signup and service-plan handlers remain the destinations.

Design direction: teal/ivory editorial presentation, varied section rhythm, product-led visuals and restrained motion. HubSpot's public homepage was inspected for section depth and storytelling; no copy, testimonials, customer logos or numerical claims were copied. Preview conversations are explicitly illustrative.

## Illustration provenance

Asset: `frontend/public/images/merchant-team.png`, 1536 × 1024. Generated using the built-in image-generation tool, not external API credentials. It depicts an illustrative shop team, not actual customers.

Prompt specification: original premium natural editorial photography for a Vietnamese multichannel CRM; bright online retail studio; three Vietnamese adults in their late twenties/thirties, a woman at a laptop, a woman packing a stainless bottle and a man with a tablet; jade/ivory colors, warm sunlight, cream walls and sage shelving; no text, logos, watermark or holographic UI; landscape 3:2 composition with room for cropping; illustrative scene, not a testimonial.

## Verification

- Frontend build succeeded; 210 existing frontend tests passed. Build retains a bundle-size warning.
- Codex browser: desktop 1440 px, tablet 768 px and phone 375 px checked; horizontal overflow measured as zero after correcting decorative overflow.
- Scrolled through to footer: approximately 6004 px of desktop content in a 900 px viewport.
- Checked VI/EN, mobile navigation, tour tabs with click and ArrowRight, FAQ expansion, motion pause, login/signup opening and guest service plans. No account creation or purchase was submitted.
- Motion respects prefers-reduced-motion in CSS and has a manual pause control. Reduced-motion OS emulation was not exercised.
- No database, API, customer chat, credentials or Git remote changes were made for this landing-page update.
