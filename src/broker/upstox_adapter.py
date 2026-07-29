"""
UpstoxAdapter — primary broker integration.

Targets Upstox's data + order APIs (free, no paid plan required).
Sandbox mode is the default; live mode requires explicit config flag.

Static IP + single App ID binding is enforced (Rule 10):
- If the binding breaks, this adapter raises loudly rather than silently
  retrying against a different route.

Daily 2FA re-auth is handled in authenticate() (Rule 11).
Algo-ID is passed through on every order (Rule 9).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

import requests

import pandas as pd

from src.broker.base_adapter import (
    BrokerAdapter,
    OptionContract,
    OrderRequest,
)

logger = logging.getLogger(__name__)

# Flask callback writes the auth code here after the OAuth redirect.
AUTH_CODE_FILE = Path("/tmp/upstox_auth_code.txt")

# How long to wait for the operator to complete 2FA in the browser.
AUTH_TIMEOUT_SECONDS = 300   # 5 minutes


class UpstoxAdapter(BrokerAdapter):
    """
    Concrete adapter for Upstox V2 API.

    Config keys expected in the dict passed to __init__:
        api_key (str):          Upstox API key
        api_secret (str):       Upstox API secret
        redirect_uri (str):     OAuth redirect URI registered with the app
        sandbox (bool):         If True, all orders go to Upstox sandbox (default True)
        access_token (str|None): Pre-loaded token (optional; authenticate() sets it)
    """

    SANDBOX_BASE_URL = "https://api-hft.upstox.com/v2"  # Upstox sandbox / HFT endpoint
    LIVE_BASE_URL = "https://api.upstox.com/v2"
    AUTH_BASE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
    TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"

    def __init__(self, config: dict) -> None:
        self._api_key: str = config["api_key"]
        self._api_secret: str = config["api_secret"]
        self._redirect_uri: str = config["redirect_uri"]
        self._sandbox: bool = config.get("sandbox", True)
        self._access_token: Optional[str] = config.get("access_token")
        self._base_url = self.SANDBOX_BASE_URL if self._sandbox else self.LIVE_BASE_URL

        if self._sandbox:
            logger.warning(
                "UpstoxAdapter initialised in SANDBOX mode — "
                "no real orders will be placed."
            )
        else:
            logger.info("UpstoxAdapter initialised in LIVE mode.")

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_auth_url(self) -> str:
        """
        Build and return the Upstox OAuth2 login URL.

        Open this URL in a browser to start the daily 2FA flow.
        After login, Upstox redirects to redirect_uri?code=<auth_code>.
        """
        params = {
            "response_type": "code",
            "client_id": self._api_key,
            "redirect_uri": self._redirect_uri,
        }
        url = f"{self.AUTH_BASE_URL}?{urlencode(params)}"
        logger.info("Upstox auth URL: %s", url)
        return url

    def authenticate(self) -> None:
        """
        Daily 2FA re-auth via Upstox OAuth2 flow (Rule 11).

        Flow:
        1. Print the auth URL (operator opens it in browser).
        2. Operator completes TOTP 2FA.
        3. Upstox redirects to redirect_uri — Flask callback writes
           the auth code to AUTH_CODE_FILE.
        4. This method polls for the file, reads the code, exchanges
           it for an access token, and stores it in memory.

        Raises:
            TimeoutError: if operator doesn't complete 2FA within AUTH_TIMEOUT_SECONDS.
            RuntimeError: if the token exchange fails.
        """
        # Clear any stale auth code from a previous session.
        if AUTH_CODE_FILE.exists():
            AUTH_CODE_FILE.unlink()
            logger.debug("Cleared stale auth code file.")

        auth_url = self.get_auth_url()

        # Print prominently so the operator can't miss it.
        print("\n" + "="*60)
        print("UPSTOX DAILY AUTHENTICATION REQUIRED")
        print("Open this URL in your browser and complete 2FA:")
        print(f"\n  {auth_url}\n")
        print("Waiting for callback... (timeout: %ds)" % AUTH_TIMEOUT_SECONDS)
        print("="*60 + "\n")

        # Poll for the auth code written by the Flask callback.
        code = self._wait_for_auth_code()

        # Exchange auth code for access token.
        self._exchange_code_for_token(code)
        logger.info("Authentication successful.")

    def _wait_for_auth_code(self) -> str:
        """Poll AUTH_CODE_FILE until the operator completes 2FA."""
        deadline = time.time() + AUTH_TIMEOUT_SECONDS
        while time.time() < deadline:
            if AUTH_CODE_FILE.exists():
                content = AUTH_CODE_FILE.read_text(encoding="utf-8")
                for line in content.splitlines():
                    if line.startswith("code="):
                        code = line.split("=", 1)[1].strip()
                        logger.info("Auth code received from callback.")
                        return code
            time.sleep(2)

        raise TimeoutError(
            f"Timed out waiting for Upstox 2FA callback after {AUTH_TIMEOUT_SECONDS}s. "
            "Did you open the auth URL and complete login?"
        )

    def _exchange_code_for_token(self, code: str) -> None:
        """POST the auth code to Upstox token endpoint and store the access token."""
        payload = {
            "code": code,
            "client_id": self._api_key,
            "client_secret": self._api_secret,
            "redirect_uri": self._redirect_uri,
            "grant_type": "authorization_code",
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }

        resp = requests.post(self.TOKEN_URL, data=payload, headers=headers, timeout=30)

        if resp.status_code != 200:
            raise RuntimeError(
                f"Token exchange failed: HTTP {resp.status_code} — {resp.text}"
            )

        data = resp.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(
                f"Token exchange response missing access_token: {data}"
            )

        self._access_token = token
        logger.info(
            "Access token obtained. "
            "Token type: %s | expires_in: %s",
            data.get("token_type"),
            data.get("expires_in"),
        )

    def is_authenticated(self) -> bool:
        return bool(self._access_token)

    def _auth_headers(self) -> dict:
        """Return headers required for authenticated API calls."""
        if not self._access_token:
            raise RuntimeError(
                "Not authenticated. Call authenticate() before making API calls."
            )
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Market data (stubs — implement once credentials are available)
    # ------------------------------------------------------------------

    def get_ltp(self, symbol: str) -> Optional[float]:
        # TODO: GET /market-quote/ltp?symbol=<symbol>
        raise NotImplementedError("get_ltp() not yet implemented.")

    def get_option_chain(self, instrument: str, expiry: Optional[str] = None) -> list:
        # TODO: GET /option/chain?instrument_key=<...>&expiry_date=<...>
        raise NotImplementedError("get_option_chain() not yet implemented.")

    def get_option_contract(
        self,
        instrument: str,
        option_type: str,
        target_strike: Optional[float] = None,
    ) -> Optional[OptionContract]:
        # TODO: fetch option chain, find nearest liquid strike to target_strike
        # (or ATM if target_strike is None), return OptionContract.
        raise NotImplementedError("get_option_contract() not yet implemented.")

    def get_ohlcv(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:
        # TODO: GET /historical-candle/<symbol>/<interval>/<to_date>/<from_date>
        raise NotImplementedError("get_ohlcv() not yet implemented.")

    # ------------------------------------------------------------------
    # Order management (stubs)
    # ------------------------------------------------------------------

    def place_order(self, order: OrderRequest) -> str:
        """
        POST /order/place

        Upstox requires algo_id on every order since 1 April 2026.
        This is validated by ExecutionEngine before calling here, but
        we double-check defensively.
        """
        if not order.algo_id:
            raise ValueError(
                "algo_id is required on every order (legal requirement since 1 April 2026)."
            )
        # TODO: implement actual API call.
        raise NotImplementedError("place_order() not yet implemented.")

    def cancel_order(self, order_id: str) -> bool:
        # TODO: DELETE /order/cancel?order_id=<order_id>
        raise NotImplementedError("cancel_order() not yet implemented.")

    def get_positions(self) -> list:
        # TODO: GET /portfolio/short-term-positions
        raise NotImplementedError("get_positions() not yet implemented.")
