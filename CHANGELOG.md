# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Config flow taking freshharvest.com portal credentials.
- Session client implementing the two-step login handshake against
  `/s/popup/login` and `/s/submit/login`, including the per-session
  `LoginSecurity` and `SubmitToken` anti-replay fields.
- Update coordinator polling every 6 hours, surfacing auth failures as
  `ConfigEntryAuthFailed` so Home Assistant prompts for re-authentication.
- Sensor platform for next delivery date, order total, order status, and box
  item count.

### Known limitations

- Delivery parsing is unimplemented; the integration cannot yet produce values.
  The portal HTML has not been mapped against a signed-in session.
- The signed-in check is a provisional heuristic and needs confirming against a
  real authenticated response.
