"""Email/password login for the De'Longhi Coffee Link cloud.

Flow: SAP Gigya (CDC) OIDC login -> IdP access token -> Ayla `token_sign_in`
-> Ayla refresh token. Endpoints and public app identifiers are the ones the
official De'Longhi app uses.
"""
from __future__ import annotations

import base64
import json
import re
import time
from urllib.parse import parse_qs, urlparse

import requests

GIGYA_API_KEY = "3_e5qn7USZK-QtsIso1wCelqUKAK_IVEsYshRIssQ-X-k55haiZXmKWDHDRul2e5Y2"
GIGYA_CLIENT_ID = "1S8q1WJEs-emOB43Z0-66WnL"
GIGYA_CLIENT_SECRET = "lmnceiD0B-4KPNN5ZS6WuWU70j9V5BCuSlz2OPsvHkyLryhMkJkPvKsivfTq3RfNYj8GpCELtOBvhaDIzKcBtg"
GIGYA_SDK_BUILD = "16650"
AYLA_APP_ID = "DeLonghiComfort2-mw-id"
AYLA_APP_SECRET = "DeLonghiComfort2-Yg4miiqiNcf0Or-EhJwRh7ACfBY"
AYLA_OAUTH_URL = "https://user-field-eu.aylanetworks.com"

OIDC_BASE = f"https://fidm.eu1.gigya.com/oidc/op/v1.0/{GIGYA_API_KEY}"
CONSENT_HOST = "https://aylaopenid.delonghigroup.com"
REDIRECT_URI = "https://google.it"
SCOPE = "openid email profile UID comfort en alexa"
BROWSER_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148"
)
TOKEN_UA = "DeLonghiComfort/3 CFNetwork/1568.300.101 Darwin/24.2.0"
TIMEOUT = 20

_SIG_RE = re.compile(r"consentObj2Sig\s*=\s*['\"]([^'\"]+)['\"]")


class LoginError(RuntimeError):
    """Raised with a step name; never includes credentials."""


def _qs(url: str, key: str) -> str | None:
    return parse_qs(urlparse(url).query).get(key, [None])[0]


def _gigya(resp: requests.Response, step: str) -> dict:
    try:
        data = resp.json()
    except ValueError as e:
        raise LoginError(f"{step}: non-JSON response (HTTP {resp.status_code})") from e
    if data.get("errorCode", 0) != 0:
        raise LoginError(f"{step}: {data.get('errorCode')} {data.get('errorMessage')} {data.get('errorDetails', '')}")
    return data


def login(email: str, password: str, lang: str = "en") -> str:
    """Return a fresh Ayla refresh token."""
    s = requests.Session()
    s.headers["User-Agent"] = BROWSER_UA
    common = {
        "APIKey": GIGYA_API_KEY,
        "sdk": "js_latest",
        "sdkBuild": GIGYA_SDK_BUILD,
        "pageURL": f"{CONSENT_HOST}/",
        "format": "json",
    }

    # 1. Start OIDC authorization -> context
    r = s.get(
        f"{OIDC_BASE}/authorize",
        params={
            "client_id": GIGYA_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "nonce": str(int(time.time())),
        },
        allow_redirects=False,
        timeout=TIMEOUT,
    )
    context = _qs(r.headers.get("Location", ""), "context")
    if not context:
        raise LoginError(f"authorize: no context (HTTP {r.status_code})")

    # 2. Device IDs
    ids = _gigya(s.get("https://socialize.eu1.gigya.com/socialize.getIDs",
                       params={**common, "includeTicket": "true"}, timeout=TIMEOUT), "getIDs")

    # 3. Credentials login
    risk = json.dumps({
        "b0": 4494, "b1": [0, 2, 2, 0], "b2": 2, "b3": [], "b4": 2, "b5": 1, "b6": BROWSER_UA,
        "b7": [], "b8": time.strftime("%H:%M:%S"), "b9": 0, "b10": {"state": "denied"},
        "b11": False, "b13": [5, "440|956|24", False, True],
    })
    acc = _gigya(s.post("https://accounts.eu1.gigya.com/accounts.login", data={
        **common,
        "loginID": email,
        "password": password,
        "sessionExpiration": 7884009,
        "targetEnv": "jssdk",
        "include": "profile,data",
        "includeUserInfo": "true",
        "loginMode": "standard",
        "lang": lang,
        "riskContext": risk,
        "source": "showScreenSet",
        "authMode": "cookie",
        "gmid": ids.get("gmid"),
        "ucid": ids.get("ucid"),
    }, timeout=TIMEOUT), "accounts.login")
    login_token = (acc.get("sessionInfo") or {}).get("login_token")
    if not login_token:
        raise LoginError("accounts.login: no session returned (2FA or captcha required?)")

    # 4. Signed user info for consent
    ui = _gigya(s.post("https://socialize.eu1.gigya.com/socialize.getUserInfo", data={
        **common, "enabledProviders": "*", "login_token": login_token, "authMode": "cookie",
        "gmid": ids.get("gmid"), "ucid": ids.get("ucid"),
    }, timeout=TIMEOUT), "getUserInfo")

    # 5. Consent page carries the consent signature
    page = s.get(f"{CONSENT_HOST}/OIDCConsentPage.php", params={
        "lang": lang, "context": context, "clientID": GIGYA_CLIENT_ID, "scope": SCOPE.replace(" ", "+"),
        "UID": ui["UID"], "UIDSignature": ui["UIDSignature"], "signatureTimestamp": ui["signatureTimestamp"],
    }, timeout=TIMEOUT).text
    m = _SIG_RE.search(page)
    if not m:
        raise LoginError("consent: signature not found in consent page (page format changed?)")
    consent = json.dumps(
        {"scope": SCOPE, "clientID": GIGYA_CLIENT_ID, "context": context, "UID": ui["UID"], "consent": True},
        separators=(",", ":"),
    )

    # 6. Continue authorization -> code
    r = s.get(f"{OIDC_BASE}/authorize/continue", params={
        "context": context, "login_token": login_token, "consent": consent, "sig": m.group(1),
        "gmidTicket": ids.get("gmidTicket"),
    }, allow_redirects=False, timeout=TIMEOUT)
    code = _qs(r.headers.get("Location", ""), "code")
    if not code:
        err = _qs(r.headers.get("Location", ""), "error_description") or _qs(r.headers.get("Location", ""), "error")
        raise LoginError(f"authorize/continue: no code (HTTP {r.status_code}, {err})")

    # 7. Code -> IdP token
    basic = base64.b64encode(f"{GIGYA_CLIENT_ID}:{GIGYA_CLIENT_SECRET}".encode()).decode()
    r = s.post(f"{OIDC_BASE}/token", headers={"User-Agent": TOKEN_UA, "Authorization": f"Basic {basic}"},
               data={"code": code, "grant_type": "authorization_code", "redirect_uri": REDIRECT_URI},
               timeout=TIMEOUT)
    idp = r.json().get("access_token") if r.ok else None
    if not idp:
        raise LoginError(f"token: HTTP {r.status_code} {r.text[:200]}")

    # 8. IdP token -> Ayla refresh token
    r = s.post(f"{AYLA_OAUTH_URL}/api/v1/token_sign_in", headers={"User-Agent": TOKEN_UA},
               data={"app_id": AYLA_APP_ID, "app_secret": AYLA_APP_SECRET, "token": idp}, timeout=TIMEOUT)
    rt = r.json().get("refresh_token") if r.ok else None
    if not rt:
        raise LoginError(f"token_sign_in: HTTP {r.status_code} {r.text[:200]}")
    return rt
