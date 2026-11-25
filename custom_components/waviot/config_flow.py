"""Config flow for the WAVIoT integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    PasswordSelector,
    TextSelector,
)

from .api import WaviotApi, WaviotAuthError, WaviotError, WaviotTwoFactorError
from .const import (
    API_DOCS_URL,
    CONF_API_KEY,
    CONF_ELEMENT_ID,
    CONF_LOGIN,
    CONF_PASSWORD,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL_MINUTES,
    DOMAIN,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


class WaviotConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create a config entry from the login/password of lk.waviot.ru."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            login = (user_input.get(CONF_LOGIN) or "").strip()
            password = (user_input.get(CONF_PASSWORD) or "").strip()
            api_key = (user_input.get(CONF_API_KEY) or "").strip()
            element_id_raw = (user_input.get(CONF_ELEMENT_ID) or "").strip()

            if not api_key and not password:
                errors["base"] = "missing_credentials"
            else:
                try:
                    async with aiohttp.ClientSession(
                        headers={"User-Agent": USER_AGENT}
                    ) as session:
                        api = WaviotApi(
                            session, login or None, password or None, api_key or None
                        )
                        await api.authenticate()

                        if element_id_raw:
                            element_id = int(element_id_raw)
                        elif api.element_id:
                            element_id = api.element_id
                        else:
                            element_id = await api.home_element_id()

                        info = await api.element_info(element_id)
                        meters = [
                            device
                            for device in (info.get("devices") or {}).values()
                            if device.get("registrators")
                        ]
                        if not meters:
                            errors["base"] = "no_meters"
                except WaviotTwoFactorError:
                    errors["base"] = "two_factor"
                except WaviotAuthError:
                    errors["base"] = "invalid_auth"
                except (ValueError, TypeError):
                    errors[CONF_ELEMENT_ID] = "invalid_element_id"
                except WaviotError as err:
                    _LOGGER.debug("WAVIoT setup failed: %s", err)
                    errors["base"] = "cannot_connect"

            if not errors:
                unique_id = (login or api_key).lower()
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=login or api_key[:8],
                    data={
                        CONF_LOGIN: login,
                        CONF_PASSWORD: password,
                        CONF_API_KEY: api.api_key,
                        CONF_ELEMENT_ID: element_id,
                        CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL_MINUTES,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN): TextSelector(),
                    vol.Optional(CONF_PASSWORD): PasswordSelector(),
                    vol.Optional(CONF_API_KEY): TextSelector(),
                    vol.Optional(CONF_ELEMENT_ID): TextSelector(),
                }
            ),
            errors=errors,
            description_placeholders={"api_docs": API_DOCS_URL},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WaviotOptionsFlow(config_entry)


class WaviotOptionsFlow(OptionsFlow):
    """Adjust how often the cabinet is polled."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=self._config_entry.options.get(
                            CONF_POLL_INTERVAL,
                            self._config_entry.data.get(
                                CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_MINUTES
                            ),
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=1440, step=1, unit_of_measurement="minutes"
                        )
                    ),
                }
            ),
        )
