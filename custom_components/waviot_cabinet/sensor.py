"""Sensor platform for the WAVIoT personal cabinet."""

from __future__ import annotations

from datetime import datetime, UTC

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import get_coordinator
from .const import DOMAIN
from .coordinator import WaviotCoordinator
from .parsing import WaviotChannel, WaviotDevice


def channel_icon(channel_id: str, unit: str) -> str:
    """Icon for a meter channel, picked from what the meter measures."""
    norm = channel_id.lower()
    if norm == "1053":
        return "mdi:fire"
    if norm in ("159", "160"):
        return "mdi:water"
    if norm.startswith("gas"):
        return "mdi:fire"
    if norm.startswith("water"):
        return "mdi:water"
    if norm.startswith("electro") or unit == "kWh":
        return "mdi:flash"
    return "mdi:gauge"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: WaviotCoordinator = get_coordinator(hass, entry)
    known: set[str] = set()

    def entities_for(device: WaviotDevice) -> list[SensorEntity]:
        entities: list[SensorEntity] = []
        for channel in device.channels.values():
            entities.append(WaviotChannelEntity(coordinator, device, channel))
            if channel.channel_id.endswith("tsum"):
                entities.append(
                    WaviotConsumptionEntity(coordinator, device, channel)
                )

        entities.append(WaviotLastReadingEntity(coordinator, device))
        if device.battery is not None:
            entities.append(WaviotBatteryEntity(coordinator, device))
        if device.temperature is not None:
            entities.append(WaviotTemperatureEntity(coordinator, device))
        if device.rssi is not None:
            entities.append(WaviotSignalEntity(coordinator, device))
        return entities

    def add_new_entities() -> None:
        """Add whatever the latest update introduced, including meters added later."""
        fresh: list[SensorEntity] = []
        for device in (coordinator.data or {}).values():
            for entity in entities_for(device):
                if entity.unique_id not in known:
                    known.add(entity.unique_id)
                    fresh.append(entity)
        if fresh:
            async_add_entities(fresh)

    add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(add_new_entities))


class WaviotEntity(CoordinatorEntity[WaviotCoordinator], SensorEntity):
    """Base entity bound to one meter.

    SensorEntity is part of the base list: without it HA creates a plain entity
    that never computes a state or a unit, which is why every sensor read
    "unknown" even though the cabinet returned readings.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: WaviotCoordinator, device: WaviotDevice) -> None:
        super().__init__(coordinator)
        self._sn = device.sn
        self._initial = device
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device.sn)},
            "name": device.name,
            "manufacturer": "WAVIoT",
            "model": device.model,
        }

    @property
    def meter(self) -> WaviotDevice | None:
        """The meter of the latest update.

        Every poll builds new meter objects, so readings are read from the
        coordinator rather than from the object captured at setup.
        """
        return (self.coordinator.data or {}).get(self._sn) or self._initial

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.meter is not None


class WaviotChannelEntity(WaviotEntity):
    """Cumulative meter reading of one channel."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self, coordinator: WaviotCoordinator, device: WaviotDevice, channel: WaviotChannel
    ) -> None:
        super().__init__(coordinator, device)
        self._channel = channel
        self._attr_unique_id = f"{device.sn}_{channel.channel_id}"
        self._attr_name = channel.label
        self._attr_native_unit_of_measurement = channel.unit
        self._attr_icon = channel_icon(channel.channel_id, channel.unit)
        if channel.unit == "kWh":
            self._attr_device_class = SensorDeviceClass.ENERGY

    @property
    def native_value(self) -> float | None:
        meter = self.meter
        current = meter.channels.get(self._channel.channel_id) if meter else None
        return current.value if current else None


class WaviotConsumptionEntity(WaviotEntity):
    """Energy or volume consumed over the last day, taken from the cabinet balance.

    No device class: Home Assistant rejects an ``energy`` sensor with state class
    ``measurement``, and a rolling 24-hour delta is not a cumulative total. The
    unit still says kWh or m³.
    """

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_display_precision = 3

    def __init__(
        self, coordinator: WaviotCoordinator, device: WaviotDevice, channel: WaviotChannel
    ) -> None:
        super().__init__(coordinator, device)
        self._channel_id = channel.channel_id
        self._attr_unique_id = f"{device.sn}_{channel.channel_id}_daily"
        self._attr_name = f"{channel.label} per day"
        self._attr_native_unit_of_measurement = channel.unit
        self._attr_icon = channel_icon(channel.channel_id, channel.unit)

    @property
    def native_value(self) -> float | None:
        meter = self.meter
        return meter.consumption.get(self._channel_id) if meter else None


class WaviotLastReadingEntity(WaviotEntity):
    """When the meter last reported to the cabinet."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: WaviotCoordinator, device: WaviotDevice) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.sn}_last_reading"
        self._attr_name = "Last reading"

    @property
    def native_value(self) -> datetime | None:
        meter = self.meter
        if meter is None:
            return None
        ts = meter.last_station_time or max(
            (c.timestamp for c in meter.channels.values() if c.timestamp),
            default=None,
        )
        if not ts:
            return None
        return datetime.fromtimestamp(ts, UTC)


class WaviotBatteryEntity(WaviotEntity):
    """Voltage of the meter modem battery."""

    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "V"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: WaviotCoordinator, device: WaviotDevice) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.sn}_battery"
        self._attr_name = "Battery voltage"

    @property
    def native_value(self) -> float | None:
        meter = self.meter
        return meter.battery if meter else None


class WaviotTemperatureEntity(WaviotEntity):
    """Temperature reported by the meter modem."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "°C"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: WaviotCoordinator, device: WaviotDevice) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.sn}_temperature"
        self._attr_name = "Modem temperature"

    @property
    def native_value(self) -> float | None:
        meter = self.meter
        return meter.temperature if meter else None


class WaviotSignalEntity(WaviotEntity):
    """Radio signal strength of the meter modem."""

    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "dBm"
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: WaviotCoordinator, device: WaviotDevice) -> None:
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device.sn}_rssi"
        self._attr_name = "Signal strength"

    @property
    def native_value(self) -> int | None:
        meter = self.meter
        return meter.rssi if meter else None
