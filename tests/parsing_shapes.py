"""Parse meter readings from every payload shape the cabinet is known to use.

    python tests/parsing_shapes.py

No network, no Home Assistant: only the pure parsing layer is exercised.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

from live_stubs import stub_homeassistant  # noqa: E402

stub_homeassistant()

from waviot.parsing import build_devices  # noqa: E402

MODEM_ID = "70B3B9"
NOW = 1700003600
MODEMS = [
    {
        "id": MODEM_ID,
        "battery": 3.6,
        "temperature": 12,
        "last_rssi": -70,
        "last_station_time": NOW,
    }
]


def parse(
    registrators: dict,
    balance_modem_key: str = MODEM_ID.lower(),
    registrator_values: dict | None = None,
) -> dict:
    info = {
        "devices": {
            "42": {
                "id": 42,
                "name": "phobos3split_stm",
                "class_name": "Electro meter",
                "device_sn": "25071542",
                "modem_id": MODEM_ID,
                "device_time": NOW,
                "registrators": registrators,
            }
        }
    }
    balance = {
        channel: {"data": {balance_modem_key: {"diff": 3.5, "end": 2500.0}}}
        for channel in registrators
    }
    return build_devices(info, MODEMS, balance, 1234, registrator_values, NOW)


CASES = [
    ("last_value float", {"electro_ac_p_lsum_t1": {"last_value": 1234.5, "unit_id": "кВт·ч", "last_value_timestamp": NOW}}, 1234.5, None),
    ("last_value with comma", {"electro_ac_p_lsum_t1": {"last_value": "1234,5", "unit_id": "кВтч"}}, 1234.5, None),
    ("value key", {"electro_ac_p_lsum_tsum": {"value": 2500, "unit_id": "kWh", "timestamp": NOW}}, 2500.0, None),
    ("nested values object", {"electro_ac_p_lsum_t1": {"unit_id": "кВт·ч", "values": {"value": 600.0, "timestamp": NOW}}}, 600.0, None),
    # The shape lk.waviot.ru actually returns: timestamps as keys.
    ("timestamp map at registrator level", {"electro_ac_p_lsum_t1": {"unit_id": "кВт·ч", "1700000000": 120.0, "1700003600": 123.5}}, 123.5, None),
    ("timestamp map nested under values", {"electro_ac_p_lsum_tsum": {"unit_id": "кВт·ч", "values": {"1700000000": 2496.5, "1700003600": 2500.0}}}, 2500.0, None),
    ("timestamps in milliseconds", {"electro_ac_p_lsum_t2": {"unit_id": "кВт·ч", "1700000000000": 40.0, "1700003600000": 42.0}}, 42.0, None),
    ("unit only, readings from get_values", {"electro_ac_p_lsum_t1": {"unit_id": "кВт·ч"}}, 123.5, {"70B3B9": {"electro_ac_p_lsum_t1": {"1700000000": 120.0, "1700003600": 123.5}}}),
    ("no registrator value, balance end", {"electro_ac_p_lsum_tsum": {"unit_id": "кВт·ч"}}, 2500.0, None),
    ("water in cubic metres", {"water_hot_tsum": {"last_value": "12,3", "unit_id": "м³"}}, 12.3, None),
    ("balance keyed by uppercase modem id", {"electro_ac_p_lsum_t1": {"unit_id": "кВт·ч"}}, 2500.0, None),
]

failures = []
for label, registrators, expected, values in CASES:
    key = MODEM_ID if label.startswith("balance keyed") else MODEM_ID.lower()
    devices = parse(registrators, key, values)
    if not devices:
        failures.append(f"{label}: no meters parsed")
        continue
    device = next(iter(devices.values()))
    channel = next(iter(device.channels.values()))
    if channel.value != expected:
        failures.append(f"{label}: got {channel.value}, expected {expected}")
    if channel.channel_id not in device.consumption:
        failures.append(f"{label}: daily consumption missing")

# Daily consumption derived from readings when the cabinet has no balance row.
def parse_without_balance(registrators: dict, registrator_values: dict) -> dict:
    info = {
        "devices": {
            "42": {
                "id": 42,
                "name": "phobos3split_stm",
                "class_name": "Electro meter",
                "device_sn": "25071542",
                "modem_id": MODEM_ID,
                "registrators": registrators,
            }
        }
    }
    return build_devices(info, MODEMS, {}, 1234, registrator_values, NOW)


readings = {
    MODEM_ID: {"electro_ac_p_lsum_t1": {"1699917200": 110.0, "1700000000": 120.0, "1700003600": 123.5}}
}
devices = parse_without_balance({"electro_ac_p_lsum_t1": {"unit_id": "кВт·ч"}}, readings)
device = next(iter(devices.values()))
if device.consumption.get("electro_ac_p_lsum_t1") != 13.5:
    failures.append(
        f"consumption from readings: got {device.consumption}, expected 13.5"
    )
if device.channels["electro_ac_p_lsum_t1"].timestamp != NOW:
    failures.append(
        f"reading timestamp: got {device.channels['electro_ac_p_lsum_t1'].timestamp}, expected {NOW}"
    )

instantaneous = parse({"electro_voltage": {"last_value": 231.0, "unit_id": "В"}})
if instantaneous:
    failures.append("instantaneous channels should not become sensors")

reset = parse_without_balance(
    {"electro_ac_p_lsum_t1": {"unit_id": "кВт·ч"}},
    {MODEM_ID: {"electro_ac_p_lsum_t1": {"1699917200": 500.0, "1700003600": 12.0}}},
)
if "electro_ac_p_lsum_t1" in next(iter(reset.values())).consumption:
    failures.append("a meter total reset must not produce a negative daily consumption")

if failures:
    print("FAILED:")
    for line in failures:
        print(f"  {line}")
    raise SystemExit(1)

print("OK: 11 payload shapes parsed, instantaneous channels ignored, reset guarded")
