"""Check that a wrong password is reported as invalid_auth, not as a 2FA prompt."""

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "custom_components"))

import aiohttp

from live_stubs import stub_homeassistant  # noqa: E402

stub_homeassistant()

from waviot.api import WaviotApi, WaviotAuthError, WaviotTwoFactorError  # noqa: E402


async def main() -> int:
    login = os.environ.get("WAVIOT_LOGIN", "someone@example.com")

    async with aiohttp.ClientSession() as session:
        api = WaviotApi(session, login, "definitely-not-the-password")
        try:
            await api.authenticate()
            print("unexpected success")
            return 1
        except WaviotTwoFactorError as err:
            print(f"FAILED, reported as 2FA: {err}")
            return 1
        except WaviotAuthError as err:
            print(f"OK, reported as invalid_auth: {err}")
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
