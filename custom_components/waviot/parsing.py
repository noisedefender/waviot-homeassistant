"""Pure parsing of cabinet payloads into meter objects (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import UNIT_MAP

# Channels that are not meter totals.
IGNORED_CHANNELS = {"electro_event_log"}
TOTAL_UNITS = {"kWh", "m³"}


@dataclass
class WaviotChannel:
    """One cumulative registrator channel of a meter."""

    channel_id: str
    label: str
    unit: str
    value: float | None
    timestamp: int | None


@dataclass
class WaviotDevice:
    """A meter attached to an element of the cabinet tree."""

    key: str
    name: str
    sn: str
    class_name: str | None
    modem_id: str | None
    model: str | None
    element_id: int
    element_name: str
    battery: float | None
    temperature: float | None
    rssi: int | None
    snr: int | None
    last_station_time: int | None
    channels: dict[str, WaviotChannel] = field(default_factory=dict)
    consumption: dict[str, float] = field(default_factory=dict)


def channel_label(channel_id: str, unit: str) -> str:
    """Human readable name of a cumulative channel."""
    parts = channel_id.rsplit("_t", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return f"Tariff {parts[1]}"
    if channel_id.endswith("tsum"):
        return "Total energy" if unit == "kWh" else "Total volume"
    return channel_id.replace("_", " ").title()


def build_devices(
    element_info: dict, modems: list[dict], balance: dict, element_id: int
) -> dict[str, WaviotDevice]:
    """Turn get_full_element_info/get_modems/get_balance_info into meter objects."""
    modems_by_id: dict[str, dict[str, Any]] = {
        str(modem.get("id", "")).lower(): modem for modem in modems
    }

    devices: dict[str, WaviotDevice] = {}
    for device_id, raw in (element_info.get("devices") or {}).items():
        modem_id = str(raw.get("modem_id") or "").lower()
        modem = modems_by_id.get(modem_id, {})

        channels: dict[str, WaviotChannel] = {}
        for channel_id, reg in (raw.get("registrators") or {}).items():
            if channel_id in IGNORED_CHANNELS:
                continue
            unit = UNIT_MAP.get(str(reg.get("unit_id") or ""))
            if unit not in TOTAL_UNITS:
                continue
            channels[channel_id] = WaviotChannel(
                channel_id=channel_id,
                label=channel_label(channel_id, unit),
                unit=unit,
                value=_as_float(reg.get("last_value")),
                timestamp=reg.get("last_value_timestamp"),
            )

        if not channels:
            continue

        sn = str(raw.get("device_sn") or raw.get("name") or device_id)
        device = WaviotDevice(
            key=sn,
            name=f"WAVIoT {sn}",
            sn=sn,
            class_name=raw.get("class_name"),
            modem_id=modem_id or None,
            model=modem.get("flavor_id") or raw.get("class_name"),
            element_id=element_id,
            element_name=raw.get("tree_name") or str(balance.get("element_name") or ""),
            battery=_as_float(modem.get("battery")),
            temperature=_as_float(modem.get("temperature")),
            rssi=_as_int(modem.get("last_rssi")),
            snr=_as_int(modem.get("last_snr")),
            last_station_time=modem.get("last_station_time") or raw.get("device_time"),
            channels=channels,
        )

        for channel_id in channels:
            channel_balance = (balance.get(channel_id) or {}).get("data") or {}
            diff = _as_float(channel_balance.get(modem_id, {}).get("diff"))
            if diff is not None:
                device.consumption[channel_id] = diff

        devices[sn] = device

    return devices


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
