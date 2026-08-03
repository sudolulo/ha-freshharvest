# ha-freshharvest

[![Validate](https://github.com/sudolulo/ha-freshharvest/actions/workflows/validate.yml/badge.svg?branch=main)](https://github.com/sudolulo/ha-freshharvest/actions) [![Upstream compatibility](https://github.com/sudolulo/ha-freshharvest/actions/workflows/compat.yml/badge.svg?branch=main)](https://github.com/sudolulo/ha-freshharvest/actions/workflows/compat.yml) [![HACS: custom](https://img.shields.io/badge/HACS-custom-41BDF5?logo=homeassistant&logoColor=white)](https://hacs.xyz/docs/faq/custom_repositories) [![Home Assistant 2025.2+](https://img.shields.io/badge/Home%20Assistant-2025.2%2B-41BDF5?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/) [![License: MIT](https://img.shields.io/badge/License-MIT-blue)](LICENSE) [![GitHub Sponsors](https://img.shields.io/badge/GitHub%20Sponsors-%E2%9D%A4-EA4AAA?logo=githubsponsors&logoColor=white)](https://github.com/sponsors/sudolulo) [![Ko-fi](https://img.shields.io/badge/Ko--fi-support-FF5E5B?logo=kofi&logoColor=white)](https://ko-fi.com/sudolulo)

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

Three things arrive in a delivery and only one is a list you edit:

| | What it is | Entity |
| --- | --- | --- |
| **Produce box** | Chosen, not assembled. Ten options. | `select.fresh_harvest_produce_box` |
| **Box contents** | Fresh Harvest fills it; read-only. | `produce` attr of `..._next_delivery_items` |
| **Add-ons** | Yours to add and remove. | `todo.fresh_harvest_add_ons` |

### Controls

| Entity | Notes |
| --- | --- |
| `select.fresh_harvest_produce_box` | Switches the **next delivery only**, not the standing order |
| `switch.fresh_harvest_skip_next_order` | Skip, and turn back off to restore |
| `button.fresh_harvest_donate_next_order` | Donates the box. **Not reversible** |
| `todo.fresh_harvest_add_ons` | Add/remove items; names resolve via the site's search index |

Home Assistant's built-in conversation agent can drive the to-do list through
`HassListAddItem`, so no bespoke voice work is needed.

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

### The order you can still change

| Entity | Example |
| --- | --- |
| `binary_sensor.fresh_harvest_order_open` | `on` |
| `sensor.fresh_harvest_open_order_delivery` | `2026-08-11` |
| `sensor.fresh_harvest_open_order_total` | `38.99` |
| `sensor.fresh_harvest_open_order_free_delivery_remaining` | `11.58` |
| `sensor.fresh_harvest_shopping_window` | `Shop tomorrow` |

`binary_sensor.fresh_harvest_order_open` is the one to automate on: it turns off
when the cutoff passes, the last moment to change the box.

### The account

| Entity | Example |
| --- | --- |
| `sensor.fresh_harvest_delivery_day` | `Tuesdays` |
| `sensor.fresh_harvest_subscriptions` | `1`, with each standing order in attributes |
| `sensor.fresh_harvest_vacation_holds` | `0`, with ranges in attributes |

## Events

Every write action fires `freshharvest_action` with `action`, `success`,
`target` and `detail`, so an automation can notify on an add succeeding or a
skip failing.

## Dashboard

[examples/dashboard-view.yaml](examples/dashboard-view.yaml) is a ready-made tab
— a countdown heading ("Arriving tomorrow"), tiles for the cost breakdown, the
full box contents rendered from the attributes, and the still-changeable order.
Paste it under `views:` in the raw configuration editor.

## Requirements

Home Assistant 2025.2 or newer. Developed and running against 2026.7.

## Troubleshooting

**Everything shows `unavailable`.** The session expired and could not be
renewed — usually a changed password. Reload the integration, or remove and
re-add it.

**A count reads `0` when you know it should not.** Fresh Harvest changed their
site. That is drift, not your configuration; please open an issue.

**Adding an item fails.** The item is not orderable for the open delivery. The
site only offers an add control for things it can actually deliver, so this is
the same answer you would get on the website.

**The box shows the wrong contents.** Contents are assigned a few days before
delivery; an order that has not been filled yet legitimately has none.

## Contributing

Implementation notes, the endpoints this uses, and the markup traps worth
knowing are in [docs/internals.md](docs/internals.md).

```
pip install beautifulsoup4 pytest yarl
pytest tests/
```

## Disclaimer

Unofficial and unaffiliated — not endorsed by or supported by Fresh Harvest.
Please do not lower the six-hour poll interval: this is a small business's
website, not an API.
