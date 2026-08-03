"""Config flow for Fresh Harvest."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import FreshHarvestAuthError, FreshHarvestClient, FreshHarvestError
from .const import DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str}
)


class FreshHarvestConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the portal-credentials flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input[CONF_EMAIL]
            await self.async_set_unique_id(email.lower())
            self._abort_if_unique_id_configured()

            # cookie_jar must persist across requests for the token handshake.
            session = async_create_clientsession(self.hass)
            client = FreshHarvestClient(session, email, user_input[CONF_PASSWORD])
            try:
                await client.async_login()
            except FreshHarvestAuthError:
                errors["base"] = "invalid_auth"
            except FreshHarvestError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=email, data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )
