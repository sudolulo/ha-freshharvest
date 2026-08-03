# ha-freshharvest

Unofficial Home Assistant integration for [Fresh Harvest](https://freshharvest.com/),
the Georgia local-produce delivery subscription.

> **Status: incomplete — does not work yet.** The login handshake is implemented
> and the entity scaffolding is in place, but the portal page parsing is not
> written. See [Why it is unfinished](#why-it-is-unfinished).

## What it is meant to expose

| Entity | Value |
| --- | --- |
| `sensor.fresh_harvest_next_delivery` | Date of the next scheduled delivery |
| `sensor.fresh_harvest_order_total` | Cost of the upcoming order |
| `sensor.fresh_harvest_order_status` | Portal order status |
| `sensor.fresh_harvest_items_in_box` | Item count, with contents in `items` attribute |

## How the site works

Fresh Harvest is not on Shopify, Farmigo, or Local Line — the page metadata
reports `Vy Technology - Custom Code`. It is a server-rendered jQuery site with
no JSON API and no mobile app, so this integration scrapes HTML.

Login is a two-step handshake:

1. `GET /s/popup/login` returns the form plus two hidden anti-replay fields,
   `LoginSecurity` and `SubmitToken`, minted per session.
2. `POST /s/submit/login` with `LoginEmail`, `LoginPassword`, both tokens, and
   an empty `Redirect`.

The tokens are bound to the cookie issued by step 1, so the two requests must
share a cookie jar and cannot be cached or split.

## Why it is unfinished

Signed out, **every** `/p/*` path returns HTTP 200 — including invented ones.
The site has no distinguishable 404, so the account pages cannot be located by
probing, and the delivery markup cannot be guessed. Finishing this requires one
signed-in session to capture the real account, delivery, and box-contents pages.

Concretely, what remains:

- Implement `FreshHarvestClient.async_get_next_delivery()` in
  [api.py](custom_components/freshharvest/api.py).
- Replace the provisional `_looks_authenticated()` heuristic, which currently
  guesses at a "sign out" link, with a real signed-in marker.

## Installation

Copy `custom_components/freshharvest/` into your Home Assistant `config/custom_components/`
directory and restart, then add the integration from **Settings → Devices & Services**.

## Disclaimer

Unofficial and unaffiliated. Polls every 6 hours; please do not lower that —
this is a small business's website, not an API.
