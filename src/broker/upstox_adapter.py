"""
UpstoxAdapter — primary broker integration.

Architecture:
- Data plane: Analytics Token (read-only, 1-year validity, no daily auth)
    → historical candles, LTP, WebSocket feed, option chain
- Execution plane: Sandbox/Live OAuth token (order placement only)
    → sandbox for paper trading, live for real orders

Static IP + single App ID binding is enforced (Rule 10).
Daily 2FA re-auth is handled in authenticate() (Rule 11) for execution tokens only.
Algo-ID is passed through on every order (Rule 9).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode, quote

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
    Concrete adapter for Upstox V2/V3 API.

    Config keys expected in the dict passed to __init__:
        api_key (str):            Upstox API key (for execution OAuth flow)
        api_secret (str):         Upstox API secret
        redirect_uri (str):       OAuth redirect URI registered with the app
        analytics_token (str):    Long-lived read-only token for market data
        sandbox (bool):           If True, orders go to sandbox (default True)
        access_token (str|None):  Pre-loaded execution token (optional)
    """

    # Data plane — Analytics Token uses live API v3
    DATA_BASE_URL = "https://api.upstox.com/v3"

    # Execution plane — sandbox or live v2
    SANDBOX_BASE_URL = "https://api-sandbox.upstox.com/v2"
    LIVE_BASE_URL = "https://api.upstox.com/v2"
    AUTH_BASE_URL = "https://api.upstox.com/v2/login/authorization/dialog"
    TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"

    def __init__(self, config: dict) -> None:
        self._api_key: str = config["api_key"]
        self._api_secret: str = config["api_secret"]
        self._redirect_uri: str = config["redirect_uri"]
        self._analytics_token: str = config["analytics_token"]
        self._sandbox: bool = config.get("sandbox", True)
        self._access_token: Optional[str] = config.get("access_token")
        self._exec_base_url = self.SANDBOX_BASE_URL if self._sandbox else self.LIVE_BASE_URL

        if self._sandbox:
            logger.warning(
                "UpstoxAdapter initialised in SANDBOX mode — "
                "orders go to simulated book, data comes from live Analytics Token."
            )
        else:
            logger.info("UpstoxAdapter initialised in LIVE mode.")

    # ------------------------------------------------------------------
    # Session management (execution plane only — data plane is always-on)
    # ------------------------------------------------------------------

    def get_auth_url(self) -> str:
        """
        Build and return the Upstox OAuth2 login URL for execution token.
        Data access doesn't need this — Analytics Token is always valid.
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
        Daily 2FA re-auth for EXECUTION token only (Rule 11).
        Data access via Analytics Token doesn't require this.
        """
        if AUTH_CODE_FILE.exists():
            AUTH_CODE_FILE.unlink()
            logger.debug("Cleared stale auth code file.")

        auth_url = self.get_auth_url()

        print("\n" + "="*60)
        print("UPSTOX EXECUTION TOKEN AUTHENTICATION")
        print("(Analytics Token for data is already valid)")
        print("Open this URL in your browser and complete 2FA:")
        print(f"\n  {auth_url}\n")
        print("Waiting for callback... (timeout: %ds)" % AUTH_TIMEOUT_SECONDS)
        print("="*60 + "\n")

        code = self._wait_for_auth_code()
        self._exchange_code_for_token(code)
        logger.info("Execution token authentication successful.")

    def _wait_for_auth_code(self) -> str:
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
            f"Timed out waiting for Upstox 2FA callback after {AUTH_TIMEOUT_SECONDS}s."
        )

    def _exchange_code_for_token(self, code: str) -> None:
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
            "Execution access token obtained. Expires: %s",
            data.get("expires_in"),
        )

    def is_authenticated(self) -> bool:
        """Data plane is always authenticated. Execution plane needs access_token."""
        return bool(self._access_token)

    def _data_headers(self) -> dict:
        """Headers for data plane (Analytics Token)."""
        return {
            "Authorization": f"Bearer {self._analytics_token}",
            "Accept": "application/json",
        }

    def _exec_headers(self) -> dict:
        """Headers for execution plane (OAuth access token)."""
        if not self._access_token:
            raise RuntimeError(
                "Not authenticated for order placement. Call authenticate() first."
            )
        return {
            "Authorization": f"Bearer {self._access_token}",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Market data (Analytics Token — data plane)
    # ------------------------------------------------------------------

    def get_ltp(self, symbol: str) -> Optional[float]:
        """
        Get last traded price for a symbol.

        Args:
            symbol: Upstox instrument key, e.g. "NSE_INDEX|Nifty 50"

        Returns:
            Last traded price as float, or None on failure.
        """
        # Try v2 endpoint first (more widely available)
        url = "https://api.upstox.com/v2/market-quote/ltp"
        params = {"instrument_key": symbol}

        try:
            resp = requests.get(url, headers=self._data_headers(), params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            # Response: {"status": "success", "data": {"NSE_INDEX:Nifty 50": {"last_price": ...}}}
            # Note: response key uses colon (:) not pipe (|)
            response_key = symbol.replace("|", ":")
            return float(data["data"][response_key]["last_price"])
        except Exception as e:
            logger.debug("v2 get_ltp(%s) failed: %s, trying v3...", symbol, e)
            
            # Fallback to v3
            try:
                url_v3 = f"{self.DATA_BASE_URL}/market-quote/ltp"
                resp = requests.get(url_v3, headers=self._data_headers(), params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                response_key = symbol.replace("|", ":")
                return float(data["data"][response_key]["last_price"])
            except Exception as e2:
                logger.error("get_ltp(%s) failed on both v2 and v3: %s", symbol, e2)
                return None

    def get_ohlcv(
        self,
        symbol: str,
        interval: str,
        from_date: str,
        to_date: str,
    ) -> pd.DataFrame:
        """
        Routes to the correct Upstox endpoint automatically:
          - Same-day (from_date == to_date == today): v2 intraday endpoint
            (the only one that returns live candles during the current session)
          - Any other range: v3 historical endpoint
        """
        from datetime import datetime as _dt
        today_str = _dt.now().strftime("%Y-%m-%d")

        if from_date == today_str and to_date == today_str:
            return self._get_intraday_ohlcv(symbol, interval)
        return self._get_historical_ohlcv(symbol, interval, from_date, to_date)

    def _get_intraday_ohlcv(self, symbol: str, interval: str) -> pd.DataFrame:
        """v2 intraday endpoint — returns today's live candles mid-session."""
        valid = {"1minute", "30minute"}
        if interval not in valid:
            raise ValueError(f"Intraday only supports {valid}, got '{interval}'.")

        encoded_symbol = quote(symbol, safe="")
        url = f"https://api.upstox.com/v2/historical-candle/intraday/{encoded_symbol}/{interval}"

        try:
            resp = requests.get(url, headers=self._data_headers(), timeout=30)
            resp.raise_for_status()
            candles = resp.json()["data"]["candles"]
            if not candles:
                logger.warning("Intraday: no candles yet for %s (market may not be open)", symbol)
                return pd.DataFrame()
            return self._candles_to_df(candles, symbol, interval, source="intraday")
        except Exception as e:
            logger.error("_get_intraday_ohlcv(%s, %s) failed: %s", symbol, interval, e)
            return pd.DataFrame()

    def _get_historical_ohlcv(
        self, symbol: str, interval: str, from_date: str, to_date: str
    ) -> pd.DataFrame:
        """v3 historical endpoint — for any date range that is not today."""
        interval_map = {
            "1minute":  ("minutes", "1"),
            "30minute": ("minutes", "30"),
            "day":      ("days", "1"),
            "week":     ("days", "7"),
            "month":    ("months", "1"),
        }
        if interval not in interval_map:
            raise ValueError(
                f"Invalid interval '{interval}'. Valid: {', '.join(interval_map)}"
            )

        granularity, count = interval_map[interval]
        encoded_symbol = quote(symbol, safe="")
        url = (
            f"{self.DATA_BASE_URL}/historical-candle/{encoded_symbol}/"
            f"{granularity}/{count}/{to_date}/{from_date}"
        )

        try:
            resp = requests.get(url, headers=self._data_headers(), timeout=30)
            resp.raise_for_status()
            candles = resp.json()["data"]["candles"]
            if not candles:
                logger.warning(
                    "Historical: no candles for %s %s %s->%s",
                    symbol, interval, from_date, to_date,
                )
                return pd.DataFrame()
            return self._candles_to_df(candles, symbol, interval, source="historical")
        except Exception as e:
            logger.error(
                "_get_historical_ohlcv(%s, %s, %s, %s) failed: %s",
                symbol, interval, from_date, to_date, e,
            )
            return pd.DataFrame()

    @staticmethod
    def _candles_to_df(
        candles: list, symbol: str, interval: str, source: str = ""
    ) -> pd.DataFrame:
        """Convert raw Upstox candle list to a tidy ascending-index DataFrame."""
        df = pd.DataFrame(
            candles,
            columns=["timestamp", "open", "high", "low", "close", "volume", "open_interest"],
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp").sort_index()
        logger.info(
            "[%s] %d candles | %s (%s) | %s -> %s",
            source, len(df), symbol, interval, df.index[0], df.index[-1],
        )
        return df


    def get_option_chain(self, instrument: str, expiry: Optional[str] = None) -> list:
        """
        Fetch option chain for an instrument.
        
        Returns list of option contracts with their instrument keys.
        Used to look up real option LTPs during live/paper trading.
        """
        # For now, we'll implement a simpler approach:
        # Use the instrument master JSON to build lookup table
        raise NotImplementedError("Use get_option_ltp() instead for live premiums.")

    def get_option_quote(
        self,
        instrument: str,
        strike: float,
        option_type: str,  # "CE" or "PE"
        expiry_date: str,  # ISO format "2026-08-13"
    ) -> Optional[dict]:
        """
        Fetch real LTP + bid/ask for a specific option via option chain endpoint.
        
        This is the CORRECT way to get option premiums from Upstox.
        The instrument_key for options is an opaque exchange token (e.g., "NSE_FO|37590"),
        NOT a constructed string. We must query the option chain to get it.
        
        Args:
            instrument: e.g. "NIFTY"
            strike: e.g. 24350
            option_type: "CE" or "PE"
            expiry_date: ISO date string "2026-08-13"
        
        Returns:
            {
                "instrument_key": "NSE_FO|37590",  # Real Upstox token
                "ltp": 126.50,
                "bid": 126.25,
                "ask": 126.75,
                "oi": 1234567,
            }
            or None if not found
        """
        # Map instrument to Upstox underlying key
        underlying_map = {
            "NIFTY": "NSE_INDEX|Nifty 50",
            "BANKNIFTY": "NSE_INDEX|Nifty Bank",
        }
        
        underlying_key = underlying_map.get(instrument)
        if not underlying_key:
            logger.error("Unknown instrument: %s", instrument)
            return None
        
        # Upstox option chain endpoint (v2 - this one works differently than market-quote)
        url = "https://api.upstox.com/v2/option/chain"
        params = {
            "instrument_key": underlying_key,
            "expiry_date": expiry_date,
        }
        
        try:
            resp = requests.get(url, headers=self._data_headers(), params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json().get("data", [])
            
            # Search for matching strike
            for row in data:
                if abs(row["strike_price"] - strike) < 0.01:  # Float comparison tolerance
                    # Get the correct leg (CE or PE)
                    leg = row["call_options"] if option_type == "CE" else row["put_options"]
                    md = leg.get("market_data", {})
                    
                    result = {
                        "instrument_key": leg["instrument_key"],
                        "ltp": md.get("ltp", 0.0),
                        "bid": md.get("bid_price", 0.0),
                        "ask": md.get("ask_price", 0.0),
                        "oi": md.get("oi", 0),
                    }
                    
                    logger.debug(
                        "Option quote: %s %s %.0f %s | LTP=₹%.2f Bid=₹%.2f Ask=₹%.2f",
                        instrument, expiry_date, strike, option_type,
                        result["ltp"], result["bid"], result["ask"]
                    )
                    
                    return result
            
            logger.warning(
                "Strike %.0f not found in option chain for %s %s %s",
                strike, instrument, expiry_date, option_type
            )
            return None
            
        except Exception as e:
            logger.error(
                "Failed to fetch option chain for %s %s: %s",
                instrument, expiry_date, e
            )
            return None

    def get_option_contract(
        self,
        instrument: str,
        option_type: str,
        target_strike: Optional[float] = None,
    ) -> Optional[OptionContract]:
        """
        Resolve best matching option contract.
        Implementation deferred — not needed for backtest (Stage 1).
        """
        raise NotImplementedError("get_option_contract() not yet implemented.")

    # ------------------------------------------------------------------
    # Order management (execution plane — sandbox or live)
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
