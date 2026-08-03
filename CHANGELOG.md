# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-08-03

### Added

- `sensor.fresh_harvest_next_delivery_add_ons`, the combined cost of the
  add-ons excluding the produce box.
- `add_ons_total` and `box_price` attributes on the item-count sensor.
- A test asserting `add_ons_total + box_price` equals the portal's own
  subtotal, so a mis-parsed price cannot pass silently.

### Changed

- `add_ons` attribute entries now carry quantity, unit, and extended price
  (`4 Complete Recovery Smoothie 15.2 fl oz — $17.96`) rather than a bare name.
  Templates reading these strings will need updating.
- The test fixture's totals are now internally consistent, so the subtotal
  reconciliation is a real invariant rather than copied numbers.

## [0.1.0] - 2026-08-03

### Added

- Config flow taking freshharvest.com portal credentials.
- Session client implementing the two-step login handshake against
  `/s/popup/login` and `/s/submit/login`, including the per-session
  `LoginSecurity` and `SubmitToken` anti-replay fields, with one automatic
  re-authentication when a session lapses.
- Dashboard parser reading delivery day, next arrival date, both upcoming
  carts, produce-box contents, add-ons, and order totals from a single
  `GET /p/dashboard/details`.
- Update coordinator polling every 6 hours, surfacing auth failures as
  `ConfigEntryAuthFailed` so Home Assistant prompts for re-authentication.
- Five sensors: next delivery date, next delivery total, next delivery item
  count, open order delivery date, and shopping window.
- Parser tests covering totals, contents, the locked/open distinction, money
  parsing, and year rollover on undated cart tabs.
- English translations under `translations/en.json`, which is where custom
  integrations read entity and config-flow strings from.
- Example dashboard view under `examples/dashboard-view.yaml`: a three-section
  tab with a delivery countdown, order tiles, and the full box contents.
