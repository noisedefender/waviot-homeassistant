"""Config flow for the WAVIoT cabinet integration."""

from __future__ import annotations

import logging
from typing import Any, Mapping

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    TextSelector,
)

# PasswordSelector was removed in Home Assistant 2026; the text selector with
# type="password" is the same input field and works on every supported version.
PASSWORD_SELECTOR = TextSelector({"type": "password"})

from .api import WaviotApi, WaviotAuthError, WaviotError, WaviotTwoFactorError
from .const import (
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

    _reauth_login: str = ""

    async def _async_validate_credentials(
        self,
        login: str | None,
        password: str | None,
        api_key: str | None,
        element_id_raw: str | None = None,
    ) -> tuple[str, int, bool]:
        """Authenticate and report the personal key, the element and whether meters exist."""
        async with aiohttp.ClientSession(
            headers={"User-Agent": USER_AGENT}
        ) as session:
            api = WaviotApi(session, login, password, api_key)
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
                if isinstance(device, dict) and device.get("registrators")
            ]
            return str(api.api_key), element_id, bool(meters)

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
                    key, element_id, has_meters = await self._async_validate_credentials(
                        login or None, password or None, api_key or None, element_id_raw or None
                    )
                    if not has_meters:
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
                        CONF_API_KEY: key,
                        CONF_ELEMENT_ID: element_id,
                        CONF_POLL_INTERVAL: DEFAULT_POLL_INTERVAL_MINUTES,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN): TextSelector(),
                    vol.Optional(CONF_PASSWORD): PASSWORD_SELECTOR,
                    vol.Optional(CONF_API_KEY): PASSWORD_SELECTOR,
                    vol.Optional(CONF_ELEMENT_ID): TextSelector(),
                }
            ),
            errors=errors,
        )

    def _reauth_entry(self) -> ConfigEntry:
        """The entry being re-authenticated, on both Home Assistant generations."""
        entry = getattr(self, "config_entry", None)
        if entry is None:
            context = self.context or {}
            entry_id = (
                context["entry_id"] if isinstance(context, Mapping) else context.entry_id
            )
            entry = self.hass.config_entries.async_get_entry(entry_id)
        return entry

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The cabinet stopped accepting the stored credentials."""
        self._reauth_login = entry_data.get(CONF_LOGIN) or ""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            password = (user_input.get(CONF_PASSWORD) or "").strip()
            api_key = (user_input.get(CONF_API_KEY) or "").strip()

            if not password and not api_key:
                errors["base"] = "missing_credentials"
            else:
                try:
                    key, element_id, has_meters = await self._async_validate_credentials(
                        self._reauth_login or None, password or None, api_key or None
                    )
                    if not has_meters:
                        errors["base"] = "no_meters"
                except WaviotTwoFactorError:
                    errors["base"] = "two_factor"
                except WaviotAuthError:
                    errors["base"] = "invalid_auth"
                except WaviotError as err:
                    _LOGGER.debug("WAVIoT reauth failed: %s", err)
                    errors["base"] = "cannot_connect"

            if not errors:
                entry = self._reauth_entry()
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_LOGIN: self._reauth_login,
                        CONF_PASSWORD: password,
                        CONF_API_KEY: key,
                        CONF_ELEMENT_ID: element_id,
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PASSWORD): PASSWORD_SELECTOR,
                    vol.Optional(CONF_API_KEY): PASSWORD_SELECTOR,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return WaviotOptionsFlow(config_entry)


class WaviotOptionsFlow(OptionsFlow):
    """Adjust how often the cabinet is polled."""

    def __init__(self, config_entry: ConfigEntry | None = None) -> None:
        # Older Home Assistant passes the entry to the constructor, newer
        # versions set it on the flow itself.
        self._config_entry = config_entry or getattr(self, "config_entry", None)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._config_entry or self.config_entry  # type: ignore[attr-defined]
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_POLL_INTERVAL,
                        default=entry.options.get(
                            CONF_POLL_INTERVAL,
                            entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_MINUTES),
                        ),
                    ): NumberSelector(
                        NumberSelectorConfig(
                            min=1, max=1440, step=1, unit_of_measurement="minutes"
                        )
                    ),
                }
            ),
        )
