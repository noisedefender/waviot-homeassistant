"""Run the integration's sensor platform end-to-end against the live cabinet.

    $env:WAVIOT_LOGIN / $env:WAVIOT_PASSWORD   (or WAVIOT_API_KEY)
    python tests/live_sensor.py

Home Assistant is stubbed with the pieces the platform actually touches: the
coordinator, the entity base class and the entity registry callback. This shows
what HA would display for each sensor, not just what the parser returns.
"""

import asyncio
import os
import sys
import types
from typing import Generic

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp  # noqa: E402

from live_stubs import stub_homeassistant  # noqa: E402

stub_homeassistant()

from waviot.api import WaviotApi  # noqa: E402
from waviot.const import DOMAIN, USER_AGENT  # noqa: E402
from waviot.coordinator import WaviotCoordinator  # noqa: E402


class _Entity:
    """Stand-in for CoordinatorEntity with the attributes HA reads."""

    _attr_has_entity_name = True

    def __class_getitem__(cls, item):
        return cls

    def __init__(self, coordinator=None):
        self.coordinator = coordinator

    @property
    def unique_id(self):
        return getattr(self, "_attr_unique_id", None)

    @property
    def name(self):
        return getattr(self, "_attr_name", None)

    @property
    def available(self):
        return True


sensor_mod = types.ModuleType("homeassistant.components.sensor")


class SensorDeviceClass:
    ENERGY = "energy"
    TIMESTAMP = "timestamp"
    VOLTAGE = "voltage"
    TEMPERATURE = "temperature"
    SIGNAL_STRENGTH = "signal_strength"


class SensorStateClass:
    TOTAL_INCREASING = "total_increasing"
    MEASUREMENT = "measurement"


sensor_mod.SensorDeviceClass = SensorDeviceClass
sensor_mod.SensorEntity = _Entity
sensor_mod.SensorStateClass = SensorStateClass
sys.modules["homeassistant.components.sensor"] = sensor_mod
sys.modules["homeassistant.components"] = types.ModuleType("homeassistant.components")
sys.modules["homeassistant.helpers.entity_platform"] = types.ModuleType(
    "homeassistant.helpers.entity_platform"
)
sys.modules["homeassistant.helpers.entity_platform"].AddEntitiesCallback = object

update_mod = sys.modules["homeassistant.helpers.update_coordinator"]
update_mod.CoordinatorEntity = _Entity


class FakeEntry:
    entry_id = "live"

    def __init__(self, data):
        self.data = data
        self.options = {}

    def async_on_unload(self, _):
        pass


async def main() -> int:
    login = os.environ.get("WAVIOT_LOGIN")
    password = os.environ.get("WAVIOT_PASSWORD")
    api_key = os.environ.get("WAVIOT_API_KEY")
    if not (login and password) and not api_key:
        print("Set WAVIOT_LOGIN/WAVIOT_PASSWORD or WAVIOT_API_KEY")
        return 2

    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        api = WaviotApi(session, login, password, api_key)
        await api.authenticate()
        element_id = int(
            os.environ.get("WAVIOT_ELEMENT_ID") or api.element_id or await api.home_element_id()
        )

        class FakeHass:
            def __init__(self):
                self.data = {}

        hass = FakeHass()
        hass.data[DOMAIN] = {}
        entry = FakeEntry({"element_id": element_id})
        coordinator = WaviotCoordinator(hass, api, element_id, 15)
        coordinator.data = await coordinator._async_update_data()
        hass.data[DOMAIN][entry.entry_id] = coordinator

        import waviot.sensor as sensor  # noqa: E402

        added = []
        await sensor.async_setup_entry(hass, entry, lambda entities: added.extend(entities))

        print(f"element {element_id}: {len(added)} sensor entities")
        for entity in added:
            print(
                f"  {entity._attr_name}: {entity.native_value!r} "
                f"unit={getattr(entity, '_attr_native_unit_of_measurement', None)!r} "
                f"class={getattr(entity, '_attr_device_class', None)} "
                f"available={entity.available}"
            )
        unknown = [e for e in added if e.native_value is None]
        if unknown:
            print(f"FAILED: {len(unknown)} entity(s) with no value")
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
