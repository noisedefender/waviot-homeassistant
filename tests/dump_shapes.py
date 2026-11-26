"""Print the raw cabinet payloads for one element, to see how readings are shaped.

    $env:WAVIOT_LOGIN / $env:WAVIOT_PASSWORD   (or WAVIOT_API_KEY)
    python tests/dump_shapes.py
"""

import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))
sys.path.insert(0, os.path.dirname(__file__))

import aiohttp  # noqa: E402

from live_stubs import stub_homeassistant  # noqa: E402

stub_homeassistant()

from waviot.api import WaviotApi, WaviotError  # noqa: E402
from waviot.const import USER_AGENT  # noqa: E402


def brief(payload, depth=3, width=6):
    if isinstance(payload, dict):
        if depth <= 0:
            return "dict"
        return "{" + ", ".join(
            f"{key!r}: {brief(value, depth - 1, width)}"
            for key, value in list(payload.items())[:width]
        ) + "}"
    if isinstance(payload, list):
        return f"[{len(payload)} {brief(payload[0], depth - 1, width) if payload else ''}]"
    return repr(payload)


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
        element_id = int(os.environ.get("WAVIOT_ELEMENT_ID") or api.element_id or await api.home_element_id())
        now = int(time.time())
        print(f"element {element_id}, key {api.api_key[:8]}…")

        info = await api.element_info(element_id)
        print("\n--- get_full_element_info devices ---")
        for device_id, device in (info.get("devices") or {}).items():
            print(f"device {device_id}: {brief(device, depth=2, width=8)}")
            print(f"  registrators: {json.dumps(device.get('registrators'), ensure_ascii=False)[:1200]}")

        modems = await api.modems(element_id)
        print("\n--- get_modems ---")
        print(json.dumps(modems, ensure_ascii=False)[:800])

        for modem in modems:
            modem_id = str(modem.get("id") or "").strip()
            if not modem_id:
                continue
            try:
                values = await api.values(modem_id, now - 259200, now)
                print(f"\n--- get_values {modem_id} ---")
                print(json.dumps(values, ensure_ascii=False)[:1200])
            except WaviotError as err:
                print(f"\nget_values {modem_id} FAILED: {err}")
            try:
                channel = await api.channel_values(modem_id, "electro_ac_p_lsum_tsum", now - 259200, now)
                print(f"--- get_modem_channel_values {modem_id}/tsum ---")
                print(json.dumps(channel, ensure_ascii=False)[:600])
            except WaviotError as err:
                print(f"get_modem_channel_values {modem_id}/tsum FAILED: {err}")

        print("\n--- get_balance_info ---")
        try:
            balance = await api.balance(element_id, now - 86400, now)
            print(json.dumps(balance, ensure_ascii=False)[:1500])
        except WaviotError as err:
            print(f"FAILED: {err}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
