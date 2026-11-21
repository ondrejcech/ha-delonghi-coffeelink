"""Synchronous Ayla cloud client + machine controller (no Home Assistant imports).

Ayla refresh tokens are single-use: every refresh returns a new one and
invalidates the old. `on_tokens` is called with the new token set before the
access token is used, so callers can persist it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import requests

from . import protocol as p
from .auth import LoginError, login

API_URL = "https://ads-eu.aylanetworks.com/apiv1"
OAUTH_URL = "https://user-field-eu.aylanetworks.com"
API_UA = "datatransport/3.1.2 android/"
TOKEN_UA = "DeLonghiComfort/3 CFNetwork/1568.300.101 Darwin/24.2.0"
TIMEOUT = 15

DEFAULT_APP_ID = "CAFE4A55"

COUNTER_PROPS = (
    "d701_tot_bev_b",
    "d704_tot_bev_espressi",
    "d705_tot_id1_espr",
    "d706_tot_id2_coffee",
    "d707_tot_id3_long",
    "d551_cnt_coffee_fondi",
    "d552_cnt_calc_tot",
    "d556_water_hardness",
)


class AuthError(RuntimeError):
    """Credentials or tokens are no longer valid; user must re-authenticate."""


class CloudError(RuntimeError):
    pass


@dataclass
class Tokens:
    refresh_token: str | None = None
    access_token: str | None = None
    expires_at: float = 0.0

    def as_dict(self) -> dict:
        return {"refresh_token": self.refresh_token, "access_token": self.access_token,
                "expires_at": self.expires_at}


class AylaClient:
    def __init__(
        self,
        tokens: Tokens,
        on_tokens: Callable[[Tokens], None] | None = None,
        email: str | None = None,
        password: str | None = None,
    ):
        self.tokens = tokens
        self.on_tokens = on_tokens
        self.email, self.password = email, password
        self._lock = threading.Lock()
        self._session = requests.Session()

    # ---------------- auth ----------------
    def _store(self, refresh: str, access: str | None, expires_in: int | None) -> None:
        self.tokens = Tokens(refresh, access, time.time() + int(expires_in or 0) if access else 0.0)
        if self.on_tokens:
            self.on_tokens(self.tokens)

    def _refresh(self) -> None:
        r = self._session.post(
            f"{OAUTH_URL}/users/refresh_token.json",
            headers={"User-Agent": TOKEN_UA, "Content-Type": "application/json"},
            json={"user": {"refresh_token": self.tokens.refresh_token}},
            timeout=TIMEOUT,
        )
        if r.status_code == 200:
            b = r.json()
            self._store(b["refresh_token"], b["access_token"], b.get("expires_in", 86400))
            return
        if r.status_code in (401, 403) and self.email and self.password:
            self._relogin()
            return
        if r.status_code in (401, 403):
            raise AuthError(f"Refresh token rejected: {r.text[:200]}")
        raise CloudError(f"Token refresh failed: HTTP {r.status_code}")

    def _relogin(self) -> None:
        try:
            refresh = login(self.email or "", self.password or "")
        except LoginError as e:
            raise AuthError(str(e)) from e
        self._store(refresh, None, None)
        self._refresh_plain()

    def _refresh_plain(self) -> None:
        r = self._session.post(
            f"{OAUTH_URL}/users/refresh_token.json",
            headers={"User-Agent": TOKEN_UA, "Content-Type": "application/json"},
            json={"user": {"refresh_token": self.tokens.refresh_token}},
            timeout=TIMEOUT,
        )
        if r.status_code != 200:
            raise AuthError(f"Fresh refresh token rejected: HTTP {r.status_code}")
        b = r.json()
        self._store(b["refresh_token"], b["access_token"], b.get("expires_in", 86400))

    def access_token(self, force: bool = False) -> str:
        with self._lock:
            if force or not self.tokens.access_token or self.tokens.expires_at < time.time() + 300:
                if not self.tokens.refresh_token:
                    if self.email and self.password:
                        self._relogin()
                    else:
                        raise AuthError("No refresh token")
                else:
                    self._refresh()
            return self.tokens.access_token  # type: ignore[return-value]

    # ---------------- http ----------------
    def _request(self, method: str, path: str, **kw):
        for attempt in (0, 1):
            headers = {
                "User-Agent": API_UA,
                "Authorization": f"auth_token {self.access_token(force=attempt == 1)}",
                "Accept": "application/json",
            }
            try:
                r = self._session.request(method, f"{API_URL}{path}", headers=headers, timeout=TIMEOUT, **kw)
            except requests.RequestException as e:
                raise CloudError(f"{method} {path}: {e}") from e
            if r.status_code == 401 and attempt == 0:
                continue
            if r.status_code == 401:
                raise AuthError("Access token rejected")
            if not r.ok:
                raise CloudError(f"{method} {path}: HTTP {r.status_code} {r.text[:200]}")
            return r.json() if r.content else None
        raise CloudError("unreachable")

    def get(self, path: str):
        return self._request("GET", path)

    def post(self, path: str, payload: dict):
        return self._request("POST", path, json=payload)

    # ---------------- api ----------------
    def devices(self) -> list[dict]:
        return [d["device"] for d in self.get("/devices.json") or []]

    def device(self, dsn: str) -> dict:
        return (self.get(f"/dsns/{dsn}.json") or {}).get("device", {})

    def properties(self, dsn: str, names: list[str] | tuple[str, ...] | None = None) -> dict[str, dict]:
        q = ""
        if names:
            q = "?" + "&".join(f"names[]={n}" for n in names)
        return {x["property"]["name"]: x["property"] for x in self.get(f"/dsns/{dsn}/properties.json{q}") or []}

    def write(self, dsn: str, prop: str, value: str) -> dict:
        return self.post(f"/dsns/{dsn}/properties/{prop}/datapoints.json", {"datapoint": {"value": value}})

    def datapoints(self, dsn: str, prop: str, limit: int = 25) -> list[dict]:
        return [d["datapoint"] for d in self.get(f"/dsns/{dsn}/properties/{prop}/datapoints.json?limit={limit}") or []]


@dataclass
class MachineState:
    online: bool = False
    monitor: p.MonitorState | None = None
    monitor_updated_at: str | None = None
    registered_app: str | None = None
    counters: dict[str, int] = field(default_factory=dict)


class Machine:
    """High-level control of one coffee machine."""

    def __init__(self, client: AylaClient, dsn: str, app_id: str = DEFAULT_APP_ID):
        self.client, self.dsn, self.app_id = client, dsn, app_id.upper()
        self._last_register = 0.0

    # -- registration (keeps the monitor live) --
    def register(self) -> None:
        self.client.write(self.dsn, p.PROP_CONNECTED, p.encode_registration(self.app_id))
        self._last_register = time.time()

    def keepalive(self, registered: str | None, every: float = 240) -> bool:
        """Register when nobody is, or renew our own registration periodically.

        Never takes over while another app (e.g. the phone app) is registered.
        Returns True if a registration was written.
        """
        if registered is None or (registered == self.app_id and time.time() - self._last_register > every):
            self.register()
            return True
        return False

    def _ensure_registered(self, timeout: float = 12) -> str:
        props = self.client.properties(self.dsn, [p.PROP_APP_ID])
        current = p.app_id_from_cloud(props.get(p.PROP_APP_ID, {}).get("value"))
        if current:
            return current
        self.register()
        end = time.time() + timeout
        while time.time() < end:
            time.sleep(1.5)
            props = self.client.properties(self.dsn, [p.PROP_APP_ID])
            current = p.app_id_from_cloud(props.get(p.PROP_APP_ID, {}).get("value"))
            if current:
                return current
        return self.app_id

    # -- commands --
    def send(self, frame_hex: str) -> None:
        app = self._ensure_registered()
        self.client.write(self.dsn, p.PROP_REQUEST, p.encode_request(frame_hex, app))

    def wake(self) -> None:
        self.send(p.FRAME_WAKEUP)

    def standby(self) -> None:
        self.send(p.FRAME_STANDBY)

    def brew(self, recipe: p.Recipe) -> None:
        self.send(recipe.start)

    def stop(self, recipe: p.Recipe) -> None:
        if recipe.stop:
            self.send(recipe.stop)

    # -- state --
    def info(self) -> dict:
        d = self.client.device(self.dsn)
        props = self.client.properties(self.dsn, [p.PROP_FIRMWARE, p.PROP_SERIAL])
        return {
            "online": d.get("connection_status") == "Online",
            "oem_model": d.get("oem_model"),
            "module": d.get("model"),
            "firmware": (props.get(p.PROP_FIRMWARE) or {}).get("value"),
            "serial": p.decode_serial((props.get(p.PROP_SERIAL) or {}).get("value")),
        }

    def poll(self, with_counters: bool = False, with_online: bool = False) -> MachineState:
        names = [p.PROP_MONITOR, p.PROP_APP_ID]
        if with_counters:
            names += list(COUNTER_PROPS)
        props = self.client.properties(self.dsn, names)
        mon = props.get(p.PROP_MONITOR) or {}
        st = MachineState(
            monitor=p.parse_monitor(mon.get("value")),
            monitor_updated_at=mon.get("data_updated_at"),
            registered_app=p.app_id_from_cloud((props.get(p.PROP_APP_ID) or {}).get("value")),
            online=True,
        )
        if with_online:
            st.online = self.client.device(self.dsn).get("connection_status") == "Online"
        for n in COUNTER_PROPS:
            v = (props.get(n) or {}).get("value")
            if isinstance(v, int):
                st.counters[n] = v
        return st

    def learn_recipes(self, limit: int = 50) -> dict[int, p.Recipe]:
        """Brew frames sent by any app (e.g. the official phone app), newest wins."""
        found: dict[int, p.Recipe] = {}
        for dp in sorted(self.client.datapoints(self.dsn, p.PROP_REQUEST, limit), key=lambda d: d["created_at"]):
            r = p.recipe_from_request(dp.get("value"), dp.get("created_at"))
            if r:
                found[r.beverage_id] = r
        return found
