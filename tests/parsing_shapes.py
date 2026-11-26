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
MODEMS = [
    {
        "id": MODEM_ID,
        "battery": 3.6,
        "temperature": 12,
        "last_rssi": -70,
        "last_station_time": 1700000000,
    }
]
BALANCE = {
    channel: {
        "data": {
            MODEM_ID.lower(): {
                "diff": 3.5,
                "end": 2500.0,
                "last_message_timestamp": 1700000100,
            }
        }
    }
    for channel in ("electro_ac_p_lsum_t1", "electro_ac_p_lsum_tsum", "water_hot_tsum")
}


def parse(registrators: dict) -> dict:
    info = {
        "devices": {
            "42": {
                "id": 42,
                "name": "phobos3split_stm",
                "class_name": "Electro meter",
                "device_sn": "25071542",
                "modem_id": MODEM_ID,
                "device_time": 1700000000,
                "registrators": registrators,
            }
        }
    }
    balance = {
        channel: {"data": {MODEM_ID.lower(): {"diff": 3.5, "end": 2500.0}}}
        for channel in registrators
    }
    return build_devices(info, MODEMS, balance, 1234)


CASES = [
    ("last_value float", {"electro_ac_p_lsum_t1": {"last_value": 1234.5, "unit_id": "кВт·ч", "last_value_timestamp": 1700000000}}, 1234.5),
    ("last_value with comma", {"electro_ac_p_lsum_t1": {"last_value": "1234,5", "unit_id": "кВтч"}}, 1234.5),
    ("value key", {"electro_ac_p_lsum_tsum": {"value": 2500, "unit_id": "kWh", "timestamp": 1700000050}}, 2500.0),
    ("nested values", {"electro_ac_p_lsum_t1": {"unit_id": "кВт·ч", "values": {"value": 600.0, "timestamp": 1700000060}}}, 600.0),
    ("no registrator value, balance end", {"electro_ac_p_lsum_tsum": {"unit_id": "кВт·ч"}}, 2500.0),
    ("water in cubic metres", {"water_hot_tsum": {"last_value": "12,3", "unit_id": "м³"}}, 12.3),
]

failures = []
for label, registrators, expected in CASES:
    devices = parse(registrators)
    if not devices:
        failures.append(f"{label}: no meters parsed")
        continue
    device = next(iter(devices.values()))
    channel = next(iter(device.channels.values()))
    if channel.value != expected:
        failures.append(f"{label}: got {channel.value}, expected {expected}")
    if channel.channel_id not in device.consumption:
        failures.append(f"{label}: daily consumption missing")

instantaneous = parse({"electro_voltage": {"last_value": 231.0, "unit_id": "В"}})
if instantaneous:
    failures.append("instantaneous channels should not become sensors")

if failures:
    print("FAILED:")
    for line in failures:
        print(f"  {line}")
    raise SystemExit(1)

print("OK: 6 payload shapes parsed, instantaneous channels ignored")
