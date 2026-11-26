"""Data coordinator for the WAVIoT integration."""

from __future__ import annotations

import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import WaviotApi, WaviotAuthError, WaviotError, WaviotTwoFactorError
from .const import DAY_SECONDS, DOMAIN, READING_WINDOW_SECONDS
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
            balance = await self._api.balance(
                self.element_id, now - DAY_SECONDS, now
            )

            readings: dict[str, dict] = {}
            modem_ids = {str(modem.get("id") or "").strip() for modem in modems}
            for raw in (info.get("devices") or {}).values():
                if isinstance(raw, dict):
                    modem_ids.add(str(raw.get("modem_id") or "").strip())
            for modem_id in sorted(modem_ids - {""}):
                try:
                    readings[modem_id] = await self._api.values(
                        modem_id, now - READING_WINDOW_SECONDS, now
                    )
                except WaviotError as err:
                    _LOGGER.debug("WAVIoT: no readings for modem %s: %s", modem_id, err)
        except (WaviotAuthError, WaviotTwoFactorError) as err:
            raise ConfigEntryAuthFailed(f"WAVIoT credentials no longer work: {err}") from err
        except WaviotError as err:
            raise UpdateFailed(f"Error reading the WAVIoT cabinet: {err}") from err

        devices = build_devices(info, modems, balance, self.element_id, readings, now)

        # Meters whose readings are not in get_values: ask for each channel directly.
        missing = [
            (device.modem_id, channel.channel_id)
            for device in devices.values()
            for channel in device.channels.values()
            if channel.value is None and device.modem_id
        ]
        for modem_id, channel_id in missing[:20]:
            try:
                series = await self._api.channel_values(
                    modem_id, channel_id, now - READING_WINDOW_SECONDS, now
                )
            except WaviotError as err:
                _LOGGER.debug("WAVIoT: no channel values for %s/%s: %s", modem_id, channel_id, err)
                continue
            if series:
                readings.setdefault(modem_id, {})[channel_id] = series
        if missing:
            devices = build_devices(info, modems, balance, self.element_id, readings, now)

        _LOGGER.debug(
            "WAVIoT payload shapes: element=%s registrators=%s values=%s balance=%s",
            self.element_id,
            _shape(info.get("devices")),
            _shape(readings),
            _shape(balance),
        )

        if not devices:
            raise UpdateFailed(
                f"No meters with readable readings found for element {self.element_id}"
            )

        if all(
            channel.value is None
            for device in devices.values()
            for channel in device.channels.values()
        ):
            _LOGGER.warning(
                "WAVIoT: element %s has %d meter(s) but the cabinet returned no "
                "readings for them. Payload shapes: registrators=%s values=%s balance=%s",
                self.element_id,
                len(devices),
                _shape(info.get("devices")),
                _shape(readings),
                _shape(balance),
            )

        _LOGGER.debug("WAVIoT: %d meter(s) on element %s", len(devices), self.element_id)
        return devices


def _shape(payload: Any, depth: int = 2) -> str:
    """Compact description of a cabinet payload, for debug logging."""
    if isinstance(payload, dict):
        if depth <= 0:
            return "dict"
        return "{" + ", ".join(
            f"{key}: {_shape(value, depth - 1)}" for key, value in list(payload.items())[:6]
        ) + "}"
    if isinstance(payload, list):
        return f"[{len(payload)} {_shape(payload[0], depth - 1) if payload else ''}]"
    return type(payload).__name__
