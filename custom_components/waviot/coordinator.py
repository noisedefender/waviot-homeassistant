"""Data coordinator for the WAVIoT integration."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WaviotApi, WaviotAuthError, WaviotError, WaviotTwoFactorError
from .const import DOMAIN
from .parsing import WaviotDevice, build_devices

_LOGGER = logging.getLogger(__name__)


class WaviotCoordinator(DataUpdateCoordinator[dict[str, WaviotDevice]]):
    """Polls the personal cabinet for meter readings."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: WaviotApi,
        element_id: int | None,
        poll_interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=poll_interval_minutes),
        )
        self._api = api
        self.element_id = element_id

    async def _async_update_data(self) -> dict[str, WaviotDevice]:
        try:
            if self.element_id is None:
                self.element_id = await self._api.home_element_id()

            info = await self._api.element_info(self.element_id)
            modems = await self._api.modems(self.element_id)
            now = int(time.time())
            balance = await self._api.balance(self.element_id, now - 86400, now)
        except (WaviotAuthError, WaviotTwoFactorError) as err:
            raise ConfigEntryAuthFailed(f"WAVIoT credentials no longer work: {err}") from err
        except WaviotError as err:
            raise UpdateFailed(f"Error reading the WAVIoT cabinet: {err}") from err

        devices = build_devices(info, modems, balance, self.element_id)

        if not devices:
            raise UpdateFailed(
                f"No meters with readable readings found for element {self.element_id}"
            )

        _LOGGER.debug("WAVIoT: %d meter(s) on element %s", len(devices), self.element_id)
        return devices
