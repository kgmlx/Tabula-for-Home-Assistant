from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TabulaAuthError, TabulaClient, TabulaError
from .const import CONF_API_KEY, DEFAULT_BASE_URL, DOMAIN

STEP_USER = vol.Schema({vol.Required(CONF_API_KEY): str})


class TabulaConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _validate(self, api_key: str) -> tuple[dict[str, str], dict[str, Any] | None]:
        client = TabulaClient(
            async_get_clientsession(self.hass),
            api_key,
            DEFAULT_BASE_URL,
        )
        try:
            inspected = await client.inspect()
        except TabulaAuthError:
            return {"base": "invalid_auth"}, None
        except TabulaError:
            return {"base": "cannot_connect"}, None

        # company.name can be null on brand-new accounts
        label = inspected.company.name or inspected.api_key.name
        return {}, {
            "company_id": inspected.company.id,
            "company_name": label,
            "api_key_name": inspected.api_key.name,
        }

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors, info = await self._validate(user_input[CONF_API_KEY])
            if not errors and info is not None:
                await self.async_set_unique_id(info["company_id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["company_name"],
                    data={
                      CONF_API_KEY: user_input[CONF_API_KEY],
                        CONF_NAME: info["company_name"],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER,
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors, info = await self._validate(user_input[CONF_API_KEY])
            if not errors and info is not None:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_KEY: user_input[CONF_API_KEY]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=STEP_USER,
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            errors, info = await self._validate(user_input[CONF_API_KEY])
            if not errors and info is not None:
                await self.async_set_unique_id(info["company_id"])
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(),
                    data_updates={
                        CONF_API_KEY: user_input[CONF_API_KEY],
                        CONF_NAME: info["company_name"],
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=STEP_USER,
            errors=errors,
        )
