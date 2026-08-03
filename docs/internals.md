# Internals

How this integration talks to freshharvest.com. Nothing here is needed to *use*
it — see the [README](../README.md) for that. This is for anyone changing the
code, or working out why it broke.

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
share a cookie jar.

A refresh is three GETs: `/p/dashboard/details` for the delivery day, next
arrival, both upcoming carts and their totals; `/p/dashboard/manage-subscriptions`
for standing orders; and `/p/dashboard/pause-deliveries` for vacation holds.
Three requests every six hours.

Write actions cost more, because nothing can be constructed offline — every
mutating endpoint is guarded by rotating per-render tokens, so each action
fetches the page that offers it, reads fresh tokens, checks they describe the
intended target, and only then submits.

## Markup notes

Six traps, none guessable from the outside:

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
- **Popups and AJAX replies are fragments, not pages.** They carry no
  navigation, so a "am I still signed in?" check based on a Sign Out control
  reads every one of them as logged out. Skip could not run at all until these
  were fetched with that check disabled.
- **`openPopup` is written both `("x","y")` and `("x", "y")`.** A regex
  requiring no space silently matches nothing on the pages that use the other
  form — which is every basket page.
- **A `<select>`'s `id` is not its POST field.** The subscribe form's frequency
  control is `id='FrequencyID'` but `name='popup-toggle'`. Posting
  `FrequencyID` is accepted and does nothing.

## Consistency guarantees

Two invariants hold against the portal's own arithmetic, and tests assert both:

- `next_delivery_box_price` + `next_delivery_add_ons` == `next_delivery_subtotal`
- `open_order_free_delivery_remaining` reaching `0.00` always coincides with a
  `0.00` delivery fee

## Drift detection

freshharvest.com has no API and no stability contract — this integration reads
HTML and posts to form endpoints, so a redesign can change what a value *means*
without changing its shape. [tools/compat.py](tools/compat.py) records every
assumption and CI asserts them against the live site daily, refreshing this
table and opening an issue on drift.

