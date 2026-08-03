# ha-freshharvest

Unofficial Home Assistant integration for [Fresh Harvest](https://freshharvest.com/),
the Georgia local-produce delivery subscription.

## Entities

| Entity | Example | Notes |
| --- | --- | --- |
| `sensor.fresh_harvest_next_delivery` | `2026-08-04` | Attributes: `delivery_day`, `box` |
| `sensor.fresh_harvest_next_delivery_total` | `109.06` | Attributes: `subtotal`, `tax`, `delivery_fee` |
| `sensor.fresh_harvest_next_delivery_items` | `14` | Attributes: `box`, `produce`, `add_ons` |
| `sensor.fresh_harvest_open_order_delivery` | `2026-08-11` | The order you can still change |
| `sensor.fresh_harvest_shopping_window` | `Shop tomorrow` | `closed` when nothing is customizable |

The next delivery and the *open* order are usually two different deliveries.
Once an order passes its cutoff it locks for packing, and the cart you can still
edit is the following week's.

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
share a cookie jar. Everything the integration needs then comes from a single
`GET /p/dashboard/details`, which carries the delivery day, next arrival date,
both upcoming carts, their contents, and their totals.

## Markup notes

Two traps are worth recording, since neither is guessable from the outside:

- **HTTP status means nothing.** Every `/p/*` path returns 200, including
  invented ones. Signed-in state is detected by the presence of a Sign Out
  control, not by a status code.
- **`cart-contents-skipped` does not mean the order was skipped.** It marks the
  locked cart — the one past its cutoff and arriving next. Treating it as
  "skipped" reports the wrong delivery as cancelled. The reliable signal for
  "can still be changed" is a non-empty `.cart-customize-wrapper`.

## Installation

Copy `custom_components/freshharvest/` into your Home Assistant
`config/custom_components/` directory and restart Home Assistant, then add the
integration from **Settings → Devices & Services**. Credentials are your normal
freshharvest.com email and password.

## Tests

```
pip install beautifulsoup4 pytest
pytest tests/
```

The fixture is synthetic but mirrors the real markup; the live page carries the
account holder's name, address, and phone number, so it is not committed.

## Disclaimer

Unofficial and unaffiliated. Polls once every 6 hours; please do not lower that
— this is a small business's website, not an API.
