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

# Containers the cabinet wraps readings in.
NESTED_KEYS = ("values", "data", "registrators", "channel", "packets", "history")

# Values older than this are not usable for the daily consumption fallback.
CONSUMPTION_WINDOW = DAY_SECONDS

# Timestamps above this are milliseconds rather than seconds.
_MS_THRESHOLD = 1_000_000_000_000

# Water and gas channels are addressed by numeric channel ids, not by name.
CHANNEL_NAMES = {
    "159": "Hot water",
    "160": "Cold water",
    "1053": "Gas",
    "heat_power": "Heat energy",
}


def channel_label(channel_id: str, unit: str) -> str:
    """Human readable name of a cumulative channel."""
    norm = channel_id.lower()
    if norm in CHANNEL_NAMES:
        return CHANNEL_NAMES[norm]
    parts = channel_id.rsplit("_t", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return f"Tariff {parts[1]}"
    if channel_id.endswith("tsum"):
        return "Total energy" if unit == "kWh" else "Total volume"
    return channel_id.replace("_", " ").title()


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
        # get_values sometimes nests the registrators one level under the modem id.
        nested = modem_values.get(modem_id)
        if isinstance(nested, dict):
            modem_values = nested

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

    The cabinet hands readings in three shapes: a ``{"<unix timestamp>": value}``
    map, a list of ``{"timestamp": .., "value": ..}`` entries, or a plain number.
    Any of them may be nested under ``values``/``data``/``registrators``.
    """
    if isinstance(payload, str):
        value = _as_float(payload)
        return [(0, value)] if value is not None else []

    if isinstance(payload, (int, float)):
        value = _as_float(payload)
        return [(0, value)] if value is not None else []

    if isinstance(payload, (list, tuple)):
        pairs = [pair for pair in (_entry_pair(item) for item in payload) if pair]
        pairs.sort(key=lambda pair: pair[0])
        return pairs

    if isinstance(payload, dict):
        for key in NESTED_KEYS:
            nested = payload.get(key)
            if isinstance(nested, (list, tuple, dict)) and nested:
                series = _series(nested)
                if series:
                    return series

        pairs: list[tuple[int, float]] = []
        for key, raw in payload.items():
            timestamp = _as_int(key)
            if timestamp is None:
                continue
            value = _as_float(raw)
            if value is None:
                continue
            pairs.append((_seconds(timestamp), value))
        pairs.sort(key=lambda pair: pair[0])
        return pairs

    return []


def _entry_pair(item: Any) -> tuple[int, float] | None:
    """One reading expressed as an entry: {"timestamp": .., "value": ..} or a pair."""
    if isinstance(item, dict):
        timestamp = None
        for key in TIMESTAMP_KEYS:
            timestamp = _as_int(item.get(key))
            if timestamp is not None:
                break
        value = None
        for key in VALUE_KEYS:
            if key in item:
                value = _as_float(item[key])
                if value is not None:
                    break
        if value is None:
            series = _series(item)
            return series[-1] if series else None
        return (_seconds(timestamp or 0), value)

    if isinstance(item, (list, tuple)) and len(item) >= 2:
        timestamp = _as_int(item[0])
        value = _as_float(item[1])
        if timestamp is not None and value is not None:
            return (_seconds(timestamp), value)
    return None


def _seconds(timestamp: int) -> int:
    """Timestamps above this are milliseconds rather than seconds."""
    return timestamp // 1000 if timestamp > _MS_THRESHOLD else timestamp


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
    candidates: list[Any] = []
    if isinstance(channel_balance, dict):
        data = channel_balance.get("data")
        if isinstance(data, dict):
            for key, entry in data.items():
                if _norm(key) == modem_id and isinstance(entry, dict):
                    return entry
            candidates = list(data.values())
        elif isinstance(data, list):
            candidates = data
        else:
            candidates = [channel_balance]
    elif isinstance(channel_balance, list):
        candidates = list(channel_balance)

    for entry in candidates:
        if isinstance(entry, dict) and _norm(entry.get("modem_id")) == modem_id:
            return entry

    if len(candidates) == 1 and isinstance(candidates[0], dict):
        return candidates[0]
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
    """Reading value and its timestamp from one registrator entry.

    Handles a plain number, a timestamp -> value map, a list of reading entries
    and the metadata-only entries get_full_element_info returns for meters whose
    readings live in get_values.
    """
    if not isinstance(reg, dict):
        series = _series(reg)
        return (series[-1][1], series[-1][0]) if series else (_as_float(reg), None)

    value = None
    timestamp = None
    for key in VALUE_KEYS:
        if key in reg:
            value = _as_float(reg[key])
            if value is not None:
                break

    for key in TIMESTAMP_KEYS:
        if key in reg:
            timestamp = _as_int(reg[key])
            if timestamp is not None:
                break

    for key in NESTED_KEYS:
        nested = reg.get(key)
        if isinstance(nested, dict):
            timestamp = _as_int(nested.get("timestamp")) or timestamp
            for name in VALUE_KEYS:
                if name in nested and value is None:
                    value = _as_float(nested[name])
                    if value is not None:
                        break

    if value is None:
        # No value key: the entry is a timestamp -> value map or a list of
        # readings, e.g. {"unit_id": "кВт·ч", "1700000000": 12.3}.
        series = _series(reg)
        if series:
            timestamp, value = series[-1]

    return value, _seconds(timestamp or 0) if timestamp else None
