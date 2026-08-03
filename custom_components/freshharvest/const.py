"""Constants for the Fresh Harvest integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "freshharvest"

# The portal is a small business's site, not an API. Poll gently: delivery
# schedules change on the order of days, and the customization cutoff is the
# only time-sensitive value.
UPDATE_INTERVAL = timedelta(hours=6)
