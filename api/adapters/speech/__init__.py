"""Speech token adapter: mints and caches browser Speech tokens (spine AD-18, AD-19); Story 6.1.

- ``azure`` -- the production ``SpeechTokenIssuer``, calling Speech's STS with the dedicated speech
  managed identity (never api's own identity, AD-19).
- ``stub`` -- the test-only implementation: a synthetic token, driven by the injectable ``Clock``,
  with an optional scripted failure (AD-18).
"""
