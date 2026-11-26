"""Pure parsing of cabinet payloads into meter objects (no Home Assistant imports)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import DAY_SECONDS, UNIT_MAP

# Channels that are not meter totals.
IGNORED_CHANNELS = {"electro_event_log"}
TOTAL_UNITS = {"kWh", "m³"}

# The cabinet nests a channel reading under different keys depending on the
# meter class, so all known spellings are tried.
VALUE_KEYS = ("last_value", "value", "val", "last", "current_value", "end")
TIMESTAMP_KEYS = ("last_value_timestamp", "timestamp", "time", "ts", "event_time")

# Values older than this are not usable for the daily consumption fallback.
CONSUMPTION_WINDOW = DAY_SECONDS

# Timestamps above this are milliseconds rather than seconds.
_MS_THRESHOLD = 1_000_000_000_000


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
    element_info: dict,
    modems: list[dict],
    balance: dict,
    element_id: int,
    registrator_values: dict[str, dict] | None = None,
    now: int | None = None,
) -> dict[str, WaviotDevice]:
    """Turn get_full_element_info/get_modems/get_balance_info into meter objects.

    ``registrator_values`` carries get_values payloads keyed by modem id; it is
    the shape the cabinet really uses for readings (timestamp -> value), so it
    is used whenever the element info carries no value of its own.
    """
    modems_by_id: dict[str, dict[str, Any]] = {
        _norm(modem.get("id")): modem for modem in modems
    }
    values_by_modem: dict[str, dict[str, Any]] = {
        _norm(modem_id): _lower_keys(registrators)
        for modem_id, registrators in (registrator_values or {}).items()
    }
    balance_by_channel: dict[str, Any] = _lower_keys(balance)

    devices: dict[str, WaviotDevice] = {}
    for device_id, raw in (element_info.get("devices") or {}).items():
        modem_id = _norm(raw.get("modem_id"))
        modem = modems_by_id.get(modem_id, {})
        modem_values = values_by_modem.get(modem_id, {})

        channels: dict[str, WaviotChannel] = {}
        for channel_id, reg in (raw.get("registrators") or {}).items():
            if channel_id in IGNORED_CHANNELS:
                continue
            unit = _as_unit(reg.get("unit_id") if isinstance(reg, dict) else None)
            if unit not in TOTAL_UNITS:
                continue
            value, timestamp = _read_channel(reg)
            if value is None:
                series = _series(modem_values.get(_norm(channel_id)))
                if series:
                    timestamp, value = series[-1]
            channels[channel_id] = WaviotChannel(
                channel_id=channel_id,
                label=channel_label(channel_id, unit),
                unit=unit,
                value=value,
                timestamp=timestamp,
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

        for channel_id, channel in channels.items():
            entry = _balance_entry(balance_by_channel.get(_norm(channel_id)), modem_id)
            diff = _as_float(entry.get("diff"))
            if diff is not None:
                device.consumption[channel_id] = diff
            else:
                # No balance row: derive the day from the reading series instead.
                derived = _consumption_from_series(
                    _series(modem_values.get(_norm(channel_id))), now
                )
                if derived is not None:
                    device.consumption[channel_id] = derived
            if channel.value is None:
                # Some meter classes only expose the reading through the balance.
                channel.value = _as_float(entry.get("end"))
                channel.timestamp = channel.timestamp or _as_int(
                    entry.get("last_message_timestamp")
                )

        devices[sn] = device

    return devices


def _norm(value: Any) -> str:
    """Modem ids, channel ids and balance keys, case-insensitive."""
    return str(value or "").strip().lower()


def _lower_keys(mapping: Any) -> dict[str, Any]:
    return {
        _norm(key): value
        for key, value in (mapping or {}).items()
        if isinstance(key, str)
    }


def _series(payload: Any) -> list[tuple[int, float]]:
    """timestamp -> value pairs of one registrator, oldest first.

    get_values and get_modem_channel_values return readings as
    ``{"<unix timestamp>": <value>}``, sometimes nested under ``values``.
    """
    if isinstance(payload, dict):
        nested = payload.get("values") or payload.get("data")
        if isinstance(nested, dict):
            payload = nested

        pairs: list[tuple[int, float]] = []
        for key, raw in payload.items():
            timestamp = _as_int(key)
            if timestamp is None:
                continue
            value = _as_float(raw)
            if value is None:
                continue
            if timestamp > _MS_THRESHOLD:
                timestamp //= 1000
            pairs.append((timestamp, value))
        pairs.sort(key=lambda pair: pair[0])
        return pairs

    value = _as_float(payload)
    return [(0, value)] if value is not None else []


def _consumption_from_series(
    series: list[tuple[int, float]], now: int | None
) -> float | None:
    """Difference between the newest reading and the newest one a day earlier."""
    if len(series) < 2 or now is None:
        return None
    latest_ts, latest_value = series[-1]
    cutoff = latest_ts - CONSUMPTION_WINDOW
    earlier = [value for ts, value in series if ts <= cutoff]
    if not earlier or latest_value < earlier[-1]:
        return None
    return latest_value - earlier[-1]


def _balance_entry(channel_balance: Any, modem_id: str) -> dict:
    """The balance row of one modem, whatever casing the cabinet used for its id."""
    data = channel_balance.get("data") if isinstance(channel_balance, dict) else None
    if not isinstance(data, dict):
        return {}

    for key, entry in data.items():
        if _norm(key) == modem_id and isinstance(entry, dict):
            return entry

    for entry in data.values():
        if isinstance(entry, dict) and _norm(entry.get("modem_id")) == modem_id:
            return entry

    if len(data) == 1:
        only = next(iter(data.values()))
        return only if isinstance(only, dict) else {}
    return {}


def _as_float(value: Any) -> float | None:
    """Number as the cabinet sends it: float, or a string with a comma decimal."""
    if isinstance(value, str):
        value = value.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _as_unit(raw: Any) -> str | None:
    """Cabinet unit spelling ("кВт·ч", "кВтч", "м³") mapped to a HA unit."""
    if raw is None:
        return None
    text = str(raw).replace("\u00a0", " ").strip()
    for candidate in (text, text.replace(" ", "")):
        if candidate in UNIT_MAP:
            return UNIT_MAP[candidate]
    return None


def _read_channel(reg: Any) -> tuple[float | None, int | None]:
    """Reading value and its timestamp from one registrator entry."""
    if not isinstance(reg, dict):
        return _as_float(reg), None

    value = None
    timestamp = None
    for key in VALUE_KEYS:
        if key in reg:
            value = _as_float(reg[key])
            if value is not None:
                break

    nested = reg.get("values") or reg.get("data")
    if isinstance(nested, dict):
        timestamp = _as_int(nested.get("timestamp")) or timestamp
        for key in VALUE_KEYS:
            if key in nested:
                value = _as_float(nested[key]) if value is None else value
                if value is not None:
                    break

    for key in TIMESTAMP_KEYS:
        if key in reg:
            timestamp = _as_int(reg[key])
            if timestamp is not None:
                break

    if value is None:
        # The entry is a timestamp -> value map, e.g. {"unit_id": "кВт·ч", "1700000000": 12.3}.
        series = _series(reg)
        if series:
            timestamp, value = series[-1]

    return value, timestamp
