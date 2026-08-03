# ha-freshharvest

Unofficial Home Assistant integration for [Fresh Harvest](https://freshharvest.com/),
the Georgia local-produce delivery subscription.

Reports what is arriving, what is in the box, what it costs — broken down per
line so you can automate on any single part — and how long you have left to
change the next order.

## Installation

### HACS (custom repository)

This is not in the HACS default list. Add it yourself:

1. HACS → ⋮ → **Custom repositories**
2. Repository `https://github.com/sudolulo/ha-freshharvest`, category **Integration**
3. Install **Fresh Harvest**, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Fresh Harvest**

### Manual

Copy `custom_components/freshharvest/` into your Home Assistant
`config/custom_components/` directory and restart, then add the integration as
above.

Credentials are your normal freshharvest.com email and password.

## Entities

The next delivery and the *open* order are usually two different deliveries.
Once an order passes its cutoff it locks for packing, and the cart you can still
edit is the following week's — so both are exposed separately.

### The order arriving next

| Entity | Example |
| --- | --- |
| `sensor.fresh_harvest_next_delivery` | `2026-08-04` |
| `sensor.fresh_harvest_next_delivery_total` | `66.16` |
| `sensor.fresh_harvest_next_delivery_subtotal` | `58.42` |
| `sensor.fresh_harvest_next_delivery_box_price` | `33.00` |
| `sensor.fresh_harvest_next_delivery_add_ons` | `25.42` |
| `sensor.fresh_harvest_next_delivery_tax` | `1.75` |
| `sensor.fresh_harvest_next_delivery_fee` | `5.99` |
| `sensor.fresh_harvest_next_delivery_items` | `11` |

`next_delivery_items` carries the contents as attributes: `produce`, `add_ons`
(each with quantity, unit and extended price), `produce_count`, `add_ons_count`
and `box`. The totals sensor carries `driver_tip` and `bounty_savings`, which
are optional or promotional rather than charges.

### The order you can still change

| Entity | Example |
| --- | --- |
| `binary_sensor.fresh_harvest_order_open` | `on` |
| `sensor.fresh_harvest_open_order_delivery` | `2026-08-11` |
| `sensor.fresh_harvest_open_order_total` | `38.99` |
| `sensor.fresh_harvest_open_order_free_delivery_remaining` | `11.58` |
| `sensor.fresh_harvest_shopping_window` | `Shop tomorrow` |

`binary_sensor.fresh_harvest_order_open` is the one to automate on: it turns off
when the cutoff passes, which is the last moment to add anything to the box.
`shopping_window` reads `closed` when nothing is changeable — distinct from
unknown.

### The account

| Entity | Example |
| --- | --- |
| `sensor.fresh_harvest_delivery_day` | `Tuesdays` |

## Consistency guarantees

Two invariants hold against the portal's own arithmetic, and tests assert both:

- `next_delivery_box_price` + `next_delivery_add_ons` == `next_delivery_subtotal`
- `open_order_free_delivery_remaining` reaching `0.00` always coincides with a
  `0.00` delivery fee

## How it works

Fresh Harvest is not on Shopify, Farmigo, or Local Line — the page metadata
reports `Vy Technology - Custom Code`. It is a server-rendered jQuery site with
no JSON API and no mobile app, so this integration signs in and parses HTML.

Login is a two-step handshake:

1. `GET /s/popup/login` returns the form plus two hidden anti-replay fields,
   `LoginSecurity` and `SubmitToken`, minted per session.
2. `POST /s/submit/login` with `LoginEmail`, `LoginPassword`, both tokens, and
   an empty `Redirect`, yielding an `fh_session_authenticated` cookie.

The tokens are bound to the cookie issued by step 1, so both requests must
share a cookie jar. Everything then comes from a single
`GET /p/dashboard/details`, which carries the delivery day, next arrival date,
both upcoming carts, their contents, and their totals. One request per refresh,
every six hours.

## Markup notes

Three traps, none guessable from the outside:

- **HTTP status means nothing.** Every `/p/*` path returns 200, including
  invented ones. Signed-in state is detected by the presence of a Sign Out
  control, not by a status code.
- **`cart-contents-skipped` does not mean the order was skipped.** It marks the
  locked cart — the one past its cutoff and arriving next. Treating it as
  "skipped" reports the wrong delivery as cancelled. The reliable signal for
  "can still be changed" is a non-empty `.cart-customize-wrapper`.
- **The free-delivery bar only renders on carts below the threshold.** An order
  that already qualifies has no bar at all, so the threshold is read once from
  whichever cart shows it and applied to every order.

## Dashboard

[examples/dashboard-view.yaml](examples/dashboard-view.yaml) is a ready-made tab
— a countdown heading ("Arriving tomorrow"), tiles for the cost breakdown, the
full box contents rendered from the attributes, and the still-changeable order.
Paste it under `views:` in the raw configuration editor.

## Tests

```
pip install beautifulsoup4 pytest
pytest tests/
```

The fixture is synthetic but mirrors the real markup, with placeholder cart IDs
and self-consistent totals; the live page carries the account holder's name,
address and phone number, so it is never committed.

## Compatibility

Requires Home Assistant 2025.2 or newer. Developed and running against 2026.7.

## Disclaimer

Unofficial and unaffiliated — not endorsed by or supported by Fresh Harvest.
Please do not lower the six-hour poll interval: this is a small business's
website, not an API.
