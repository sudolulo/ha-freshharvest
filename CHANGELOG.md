# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.1] - 2026-08-04

### Fixed

- The produce-box select listed the boxes on offer from inside
  `async_added_to_hass`, one fetch per box popup. That ran during entity setup,
  so on a slower connection those fetches exceeded Home Assistant's
  `SLOW_SETUP_MAX_WAIT`, the platform was cancelled, and the whole config entry
  landed in `setup_error` — every entity `unavailable` despite valid
  credentials. The listing now runs once in the background: the entity comes up
  immediately with the current box as its option and the rest fill in when the
  listing returns. Regression covered in `tests/test_setup_hygiene.py`.
- Every portal request now carries a 30-second timeout. The shared Home
  Assistant session otherwise inherits aiohttp's five-minute default, long
  enough for one hung request to drag a refresh — or a first setup — past Home
  Assistant's own limits and fail it outright. A slow or unreachable site now
  surfaces as a normal retry instead.

## [0.4.0] - 2026-08-03

Control, not just reporting: the box can now be managed from Home Assistant.

### Added

- Skip and restore, donate, add/remove add-ons, subscribe/unsubscribe,
  vacation holds, and produce-box switching — every reversible one verified by
  a live round trip that returned the account to its prior state.
- Entities for each: a produce-box select, a skip switch, a donate button, an
  add-ons to-do list the built-in conversation agent can drive, and sensors for
  subscriptions and vacation holds.
- A `freshharvest_action` event after every write, carrying action/success/
  target/detail so automations can notify on the outcome.
- A four-section dashboard view with the controls in place, exported to
  `examples/dashboard-view.yaml`.

### Notes

- Donating is the one action never executed: it cannot be undone, so it will be
  proven the first time there is a box actually worth giving away.
- Entities are not exposed to the conversation agent by default; that is the
  operator's call.

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
- `todo.fresh_harvest_box`: the order as a to-do list, so Home Assistant's own
  conversation agent can add and remove items with no bespoke voice code.
  Adding resolves the name against the site's search index first.
- `switch.fresh_harvest_skip_next_order` (a switch, not a button, so the state
  is readable and reversible) and `button.fresh_harvest_donate_next_order`
  (a button, because donating cannot be undone).
- `sensor.fresh_harvest_subscriptions` and `sensor.fresh_harvest_vacation_holds`,
  each listing the detail in attributes.
- A `freshharvest_action` event fired after every write action, carrying
  action/success/target/detail so automations can notify on the outcome.

### Fixed

- Subscription parsing matched `.account-item-multi-fields`, which is the
  heading row, so an account with a live subscription reported zero. Cells are
  now picked by semantic class. Regression covered in `tests/test_actions.py`.

- Restore (un-skip) via `POST /s/submit/restore-delivery`, wired to
  `switch.turn_off`. The restore popup only exists once an order is actually
  skipped, which is why it could not be found until one was. Verified end to
  end against a live order: skipped Aug 18, restored it, confirmed the account
  returned to its previous state.

### Fixed

- Subscription parsing matched `.account-item-multi-fields`, which is the
  heading row, so an account with a live subscription reported zero. Cells are
  now picked by semantic class. Regression covered in `tests/test_actions.py`.
- `async_fetch` treated popup bodies and AJAX replies as full pages. Those are
  fragments with no navigation, so the signed-in heuristic read every one as
  logged out, re-authenticated pointlessly and then failed. They now pass
  `is_page=False`. This blocked skip entirely.
- The to-do list mixed produce-box contents with add-ons. Only add-ons can be
  added and removed — the box is chosen, not assembled — so listing produce
  invited deletes with no endpoint behind them. The entity is now
  `todo.fresh_harvest_add_ons`; box contents stay read-only on
  `sensor.*_next_delivery_items`.

- Produce box switching: `POST /s/submit/select-basket`, exposed as
  `select.fresh_harvest_produce_box` with all ten boxes. Switching a box is not
  adding an add-on — you change which box arrives, not what is inside it — so
  it is a select, where add-ons are a to-do list.

### Known gaps

- Entities are deliberately NOT exposed to the conversation agent yet.

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
