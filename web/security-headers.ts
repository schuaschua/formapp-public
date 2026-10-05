// The api's security headers (api/adapters/rest/middleware.py), repeated so the Playwright check
// against `vite preview` sees what the deployed app sends and fails on anything it would block.
// src/tests/security-headers.test.ts fails if the two drift apart. HSTS is left out: it means
// nothing on http://localhost.
export const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data:",
  "font-src 'self'",
  "connect-src 'self'",
  "form-action 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
].join("; ");

// Mirrors api/adapters/rest/middleware.py: every feature denied except the microphone, which this
// origin may use for the chat's hold-to-talk mic (Story 6.2).
export const PERMISSIONS_POLICY = [
  ...[
    "accelerometer",
    "camera",
    "geolocation",
    "gyroscope",
    "magnetometer",
    "payment",
    "usb",
  ].map((feature) => `${feature}=()`),
  "microphone=(self)",
].join(", ");

export const PREVIEW_SECURITY_HEADERS: Record<string, string> = {
  "Content-Security-Policy": CONTENT_SECURITY_POLICY,
  "Permissions-Policy": PERMISSIONS_POLICY,
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "same-origin",
};
