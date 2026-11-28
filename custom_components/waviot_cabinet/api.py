"""WAVIoT cabinet (lk.waviot.ru) API client.

The cabinet exposes a documented REST-ish API (https://lk.waviot.ru/api/):

    https://lk.waviot.ru/api.<TYPE>/<METHOD>?<parameters>&key=<API_KEY>

The personal API key is shown on that page only for a logged-in session, so the
client first authenticates at auth.waviot.ru with e-mail/phone + password, then
reads the key from the page. From that point on every request carries the key
and no cookies are needed.
"""

from __future__ import annotations

import json
import re
from typing import Any

import aiohttp

from .const import API_BASE, AUTH_URL, USER_AGENT

API_KEY_RE = re.compile(
    r"(?:Ваш ключ api|Your api key)[:\s]*<b>([0-9a-f]{32})</b>", re.IGNORECASE
)
API_KEY_FALLBACK_RE = re.compile(r"<b>([0-9a-f]{32})</b>")
ELEMENT_ID_RE = re.compile(r"elementId\s*=\s*(\d+)")
MFA_RE = re.compile(r'"MFA"\s*:\s*"?1"?')

# What the cabinet answers when the key in the request is revoked or wrong.
KEY_REJECTED_RE = re.compile(
    r"(incorrect api key|invalid api key|bad key|unauthoriz|not authorized|"
    r"access denied|permission|неправильн\w* ключ|ключ не)",
    re.IGNORECASE,
)


class WaviotError(Exception):
    """Base error for the integration."""


class WaviotAuthError(WaviotError):
    """Login or password rejected, or the API key could not be read."""


class WaviotTwoFactorError(WaviotError):
    """The account requires an SMS confirmation code, which cannot be automated."""


class WaviotApiError(WaviotError):
    """The cabinet returned an error payload or an unexpected response."""


class WaviotApi:
    """Small client for the WAVIoT personal cabinet API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        login: str | None = None,
        password: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._session = session
        self._login = login
        self._password = password
        self._api_key = api_key
        self._base_url = base_url or API_BASE
        self._element_id: int | None = None
        self._signed_in = False

    @property
    def api_key(self) -> str | None:
        return self._api_key

    @property
    def element_id(self) -> int | None:
        """Element discovered while logging in, if the start page exposed one."""
        return self._element_id

    @staticmethod
    async def _text(resp: aiohttp.ClientResponse) -> str:
        """The cabinet does not always declare its charset, so decode explicitly."""
        return (await resp.read()).decode("utf-8", errors="replace")

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str, dict[str, str]]:
        """Perform one cabinet request, turning transport failures into WaviotError.

        Without this an unreachable cabinet raises aiohttp.ClientError or
        TimeoutError, which callers do not know how to report.
        """
        try:
            async with self._session.request(
                method, url, params=params, data=data, headers=headers or {}
            ) as resp:
                return resp.status, await self._text(resp), dict(resp.cookies)
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WaviotApiError(f"Could not reach the WAVIoT cabinet: {err}") from err

    async def authenticate(self) -> None:
        """Log in to the cabinet and pick up the personal API key."""
        if self._api_key:
            return

        if not self._login or not self._password:
            raise WaviotAuthError("Neither login/password nor API key was provided")

        status, body, cookies = await self._request(
            "POST",
            AUTH_URL,
            data={"login": self._login, "password": self._password},
            headers={"Referer": f"{self._base_url}/", "User-Agent": USER_AGENT},
        )
        if status >= 400:
            raise WaviotAuthError(f"Authentication failed with HTTP {status}")

        if "sendPin" in body or "use2fa" in body or MFA_RE.search(body):
            raise WaviotTwoFactorError(
                "The account requires an SMS code on every login. Disable two-factor "
                "authentication in the cabinet, or provide the API key directly."
            )

        # An unauthenticated answer still carries a JWT cookie and a small
        # window.USER object; only a real session reports the account ids.
        if "WAVIOT_JWT" not in cookies or '"lk_id"' not in body:
            raise WaviotAuthError("Invalid login or password")

        self._signed_in = True

        # Visiting the cabinet start page first makes the API key page render the
        # key, and also tells us which element (house) this account is about.
        try:
            self._element_id = await self.home_element_id()
        except WaviotApiError:
            self._element_id = None

        self._api_key = await self.fetch_api_key()

    async def fetch_api_key(self) -> str:
        """Read the personal API key from https://lk.waviot.ru/api/."""
        status, body, _ = await self._request("GET", f"{self._base_url}/api/")
        if status >= 400:
            raise WaviotAuthError(f"Could not read the API key (HTTP {status})")

        match = API_KEY_RE.search(body) or API_KEY_FALLBACK_RE.search(body)
        if not match:
            raise WaviotAuthError(
                "API key not found on the cabinet page — the session may not be authorised"
            )
        self._api_key = match.group(1)
        return self._api_key

    async def home_element_id(self) -> int:
        """The element (house) this account is about.

        The cabinet start page names it; with only an API key and no session
        cookies we fall back to the deepest leaf of the element tree.
        """
        if self._signed_in:
            status, body, _ = await self._request("GET", f"{self._base_url}/")
            if status < 400:
                match = ELEMENT_ID_RE.search(body)
                if match:
                    return int(match.group(1))

        if self._api_key:
            tree = (await self.call("api.tree/get_tree/")).get("tree") or {}
            leaf = _deepest_leaf(tree)
            if leaf is not None:
                return leaf

        raise WaviotApiError("Could not determine the home element id")

    async def call(self, method: str, params: dict[str, Any] | None = None) -> dict:
        """Call api.<TYPE>/<METHOD> and return the decoded JSON payload.

        A rejected key is reported as WaviotAuthError, so the coordinator can
        hand the entry to the reauth flow instead of failing every poll.
        """
        request_params = dict(params or {})
        if self._api_key:
            request_params["key"] = self._api_key

        status, body, _ = await self._request("GET", f"{self._base_url}/{method}", params=request_params)
        if status in (401, 403):
            raise WaviotAuthError(f"{method}: the cabinet rejected the API key (HTTP {status})")
        if status >= 400:
            raise WaviotApiError(f"{method} returned HTTP {status}: {body[:200]}")

        try:
            payload = json.loads(body)
        except ValueError as err:
            raise WaviotApiError(f"{method} returned a non-JSON response") from err

        if payload.get("status") == "error":
            message = str(payload.get("message") or "unknown error")
            if KEY_REJECTED_RE.search(message):
                raise WaviotAuthError(f"{method}: {message}")
            raise WaviotApiError(f"{method}: {message}")

        return payload

    async def element_info(self, element_id: int) -> dict:
        """Devices attached to an element, with their registrator channels."""
        return await self.call(
            "api.data/get_full_element_info/", {"id": element_id}
        )

    async def modems(self, element_id: int) -> list[dict]:
        """Radio modems serving the element (battery, signal, last contact time)."""
        payload = await self.call("api.tree/get_modems/", {"id": element_id})
        return payload.get("modems", [])

    async def modem_info(self, modem_id: str) -> dict:
        payload = await self.call("api.modem/info/", {"id": modem_id})
        return payload.get("modem", {})

    async def values(self, modem_id: str, from_ts: int, to_ts: int) -> dict:
        """Registrator readings of one modem: registrator id -> timestamp/value.

        The cabinet accepts both spellings of a modem id, so the lowercase form
        is retried if the one it handed us is rejected.
        """
        for candidate in (modem_id, modem_id.lower()):
            try:
                payload = await self.call(
                    "api.data/get_values/",
                    {"modem_id": candidate, "from": from_ts, "to": to_ts},
                )
            except WaviotApiError:
                if candidate == modem_id.lower():
                    raise
                continue
            return payload.get("registrators") or payload.get("data") or {}
        return {}

    async def channel_values(self, modem_id: str, channel: str, from_ts: int, to_ts: int) -> Any:
        """Readings of one meter channel, for meters get_values does not cover.

        ``api.data/get_modem_channel_values/`` returns ``values`` as a timestamp
        -> value map; some cabinets put that map at the top of the payload.
        """
        for candidate in (modem_id, modem_id.lower()):
            try:
                payload = await self.call(
                    "api.data/get_modem_channel_values/",
                    {"modem_id": candidate, "channel": channel, "from": from_ts, "to": to_ts},
                )
            except WaviotApiError:
                if candidate == modem_id.lower():
                    raise
                continue
            values = payload.get("values", payload)
            return values if isinstance(values, (dict, list)) else {}
        return {}

    async def balance(self, element_id: int, from_ts: int, to_ts: int) -> dict:
        """Consumption difference per channel for a period."""
        payload = await self.call(
            "api.data/get_balance_info/",
            {"elementId": element_id, "from": from_ts, "to": to_ts},
        )
        return payload.get("balance") or payload.get("balances") or {}


def _deepest_leaf(node: dict) -> int | None:
    """Return the id of the deepest element in a tree of nested element dicts."""
    children = {
        key: value
        for key, value in node.items()
        if isinstance(value, dict) and key.isdigit()
    }
    if not children:
        element_id = node.get("id")
        return int(element_id) if element_id is not None else None

    for child in children.values():
        deeper = _deepest_leaf(child)
        if deeper is not None:
            return deeper
    return None
