# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `actions.py`: the write layer — skip a delivery, donate a box, add/remove cart
  items, subscribe/unsubscribe with a frequency, and add a vacation hold over a
  date range (distinct from skipping: three weeks away is one hold, not three
  skips). Parsers for current subscriptions and scheduled holds.
- `tools/compat.py` plus a daily `compat.yml` workflow: records every assumption
  this integration makes about freshharvest.com and asserts it against the live
  site, refreshing the matrix in README and opening an issue on drift.
- `FreshHarvestClient.async_fetch`, restored as the shared authenticated-fetch
  primitive that both the snapshot read and every write action build on.

### Notes

- Actions default to `dry_run=True` and report exactly what they would submit.
  Nothing has been executed against a live account yet.

## [0.3.0] - 2026-08-03

Prepared for public release as a HACS custom repository.

### Added

- Every cost component is now its own entity rather than an attribute:
  subtotal, box price, add-ons, tax, and delivery fee for the next delivery,
  plus a total and free-delivery-remaining for the open order.
- `binary_sensor.fresh_harvest_order_open`, which turns off when the cutoff
  passes — the last moment to change the box.
- `sensor.fresh_harvest_delivery_day`.
- Parsing for the driver tip, potential Bounty savings, and the free-delivery
  threshold, with the threshold carried across orders because the progress bar
  only renders on carts below it.
- `LICENSE` (MIT), `hacs.json`, and a CI workflow running hassfest, the HACS
  action, and the test suite.
- `tests/test_translations.py`, which cross-checks every entity's
  `translation_key` against both translation files and fails on an orphan or a
  missing name.

### Changed

- Entities share a `FreshHarvestEntity` base and declare a `scope`
  (`account`, `next_order`, `open_order`), so a description states only the
  field it reads instead of repeating None handling.
- `manifest.json` documentation and issue-tracker URLs now point at GitHub;
  they previously pointed at a private forge that no installer could reach.
- Fixture cart identifiers replaced with placeholders.

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
