"""Check how a revoked API key and an unreachable cabinet are reported.

    python tests/key_rejection.py

No credentials needed: the key is deliberately wrong and the host deliberately
unresolvable. What matters is which error class comes out, because that decides
whether Home Assistant starts the reauth flow or retries every poll forever.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

import aiohttp

from live_stubs import stub_homeassistant  # noqa: E402

stub_homeassistant()

from waviot_cabinet.api import WaviotApi, WaviotApiError, WaviotAuthError  # noqa: E402
from waviot_cabinet.const import USER_AGENT  # noqa: E402

REVOKED_KEY = "0" * 32
UNRESOLVABLE = "https://lk.invalid-host-for-tests.invalid"


async def main() -> int:
    failures = []

    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        api = WaviotApi(session, api_key=REVOKED_KEY)
        try:
            await api.call("api.tree/get_tree/")
            failures.append("a revoked key was accepted")
        except WaviotAuthError as err:
            print(f"OK, revoked key raises WaviotAuthError: {err}")
        except WaviotApiError as err:
            failures.append(
                f"revoked key raises WaviotApiError, so reauth would never start: {err}"
            )

    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        api = WaviotApi(session, api_key=REVOKED_KEY, base_url=UNRESOLVABLE)
        try:
            await api.call("api.tree/get_tree/")
            failures.append("the unreachable cabinet was accepted")
        except WaviotApiError as err:
            print(f"OK, unreachable cabinet raises WaviotApiError: {err}")
        except (aiohttp.ClientError, TimeoutError) as err:
            failures.append(f"transport error escaped the client: {err}")

    if failures:
        print("FAILED:")
        for line in failures:
            print(f"  {line}")
        return 1

    print("OK: auth failures and transport failures are both reported as WaviotError")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
