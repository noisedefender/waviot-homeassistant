"""Live check against the real cabinet: login, key, meters, parsed values.

Credentials come from the environment, nothing is stored in the repository:

    $env:WAVIOT_LOGIN / $env:WAVIOT_PASSWORD   (or WAVIOT_API_KEY)
    python tests/live_smoke.py
"""

import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

import aiohttp  # noqa: E402

from live_stubs import stub_homeassistant  # noqa: E402

stub_homeassistant()

from waviot.api import WaviotApi, WaviotError  # noqa: E402
from waviot.const import USER_AGENT  # noqa: E402
from waviot.parsing import build_devices  # noqa: E402


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
        if not api.api_key:
            print("no api key obtained")
            return 1
        print(f"api key: {api.api_key[:8]}… ({len(api.api_key)} chars)")

        element_id = int(
            os.environ.get("WAVIOT_ELEMENT_ID")
            or api.element_id
            or await api.home_element_id()
        )
        print(f"element: {element_id}")

        info = await api.element_info(element_id)
        modems = await api.modems(element_id)
        now = int(time.time())
        balance = await api.balance(element_id, now - 86400, now)

        devices = build_devices(info, modems, balance, element_id)
        if not devices:
            print("no meters parsed")
            return 1

        for device in devices.values():
            print(f"meter {device.sn} ({device.class_name}, {device.model})")
            print(f"  element: {device.element_name}")
            print(
                f"  battery {device.battery} V, temperature {device.temperature} C, "
                f"rssi {device.rssi} dBm, snr {device.snr}"
            )
            print(f"  last station time: {device.last_station_time}")
            for channel in device.channels.values():
                print(f"  {channel.channel_id}: {channel.value} {channel.unit} ({channel.label})")
            for channel_id, diff in device.consumption.items():
                print(f"  {channel_id} per day: {diff:.3f}")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except WaviotError as err:
        print(f"FAILED: {err}")
        raise SystemExit(1)
