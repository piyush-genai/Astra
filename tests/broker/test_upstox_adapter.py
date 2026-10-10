"""
Unit tests for UpstoxAdapter execution methods.
All HTTP calls are mocked — no real API access required.
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from core.broker.base_adapter import (
    OptionContract,
    OrderRequest,
    OrderSide,
    OrderType,
    ProductType,
)
from core.broker.upstox_adapter import UpstoxAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

INSTRUMENTS_CONFIG = {
    "instruments": {
        "NIFTY": {
            "underlying_symbol": "NSE_INDEX|Nifty 50",
            "strike_step": 50,
            "lot_size": 65,
            "weekly_expiry_weekday": 1,  # Tuesday
        }
    }
}

def _make_adapter(sandbox: bool = True, access_token: str = "test_token") -> UpstoxAdapter:
    return UpstoxAdapter({
        "api_key": "test_key",
        "api_secret": "test_secret",
        "redirect_uri": "http://localhost/callback",
        "analytics_token": "test_analytics",
        "sandbox": sandbox,
        "access_token": access_token,
        "instruments_config": INSTRUMENTS_CONFIG,
    })


# ---------------------------------------------------------------------------
# _next_expiry
# ---------------------------------------------------------------------------

class TestNextExpiry:
    def test_returns_iso_date_string(self):
        adapter = _make_adapter()
        inst_cfg = INSTRUMENTS_CONFIG["instruments"]["NIFTY"]
        expiry = adapter._next_expiry("NIFTY", inst_cfg)
        # Should be parseable as an ISO date
        parsed = date.fromisoformat(expiry)
        assert parsed >= date.today()

    def test_expiry_is_correct_weekday(self):
        adapter = _make_adapter()
        inst_cfg = INSTRUMENTS_CONFIG["instruments"]["NIFTY"]
        expiry = adapter._next_expiry("NIFTY", inst_cfg)
        parsed = date.fromisoformat(expiry)
        # weekly_expiry_weekday=1 means Tuesday (Python weekday 1)
        assert parsed.weekday() == 1, f"Expected Tuesday, got weekday {parsed.weekday()}"

    def test_expiry_within_7_days(self):
        adapter = _make_adapter()
        inst_cfg = INSTRUMENTS_CONFIG["instruments"]["NIFTY"]
        expiry = date.fromisoformat(adapter._next_expiry("NIFTY", inst_cfg))
        assert (expiry - date.today()).days <= 7


# ---------------------------------------------------------------------------
# get_option_contract
# ---------------------------------------------------------------------------

class TestGetOptionContract:
    def test_returns_option_contract_on_success(self):
        adapter = _make_adapter()

        with patch.object(adapter, "get_ltp", return_value=24350.0), \
             patch.object(adapter, "get_option_quote", return_value={
                 "instrument_key": "NSE_FO|12345",
                 "ltp": 145.0,
                 "bid": 144.0,
                 "ask": 146.0,
                 "oi": 50000,
             }):
            contract = adapter.get_option_contract("NIFTY", "CE")

        assert contract is not None
        assert isinstance(contract, OptionContract)
        assert contract.instrument == "NIFTY"
        assert contract.option_type == "CE"
        assert contract.strike == 24350.0  # ATM for 24350 with step 50
        assert contract.symbol == "NSE_FO|12345"
        assert contract.lot_size == 65

    def test_atm_strike_rounds_to_nearest_step(self):
        adapter = _make_adapter()

        with patch.object(adapter, "get_ltp", return_value=24373.0), \
             patch.object(adapter, "get_option_quote", return_value={
                 "instrument_key": "NSE_FO|99",
                 "ltp": 100.0, "bid": 99.0, "ask": 101.0, "oi": 1,
             }):
            contract = adapter.get_option_contract("NIFTY", "CE")

        # 24373 / 50 = 487.46 → rounds to 487 → strike = 24350
        assert contract.strike == 24350.0

    def test_uses_target_strike_when_provided(self):
        adapter = _make_adapter()

        with patch.object(adapter, "get_ltp", return_value=24350.0), \
             patch.object(adapter, "get_option_quote", return_value={
                 "instrument_key": "NSE_FO|777",
                 "ltp": 80.0, "bid": 79.0, "ask": 81.0, "oi": 1,
             }) as mock_quote:
            adapter.get_option_contract("NIFTY", "PE", target_strike=24200.0)

        # Should pass target_strike directly to get_option_quote
        call_args = mock_quote.call_args
        assert call_args[0][1] == 24200.0  # second positional arg is strike

    def test_returns_none_when_ltp_unavailable(self):
        adapter = _make_adapter()

        with patch.object(adapter, "get_ltp", return_value=None):
            contract = adapter.get_option_contract("NIFTY", "CE")

        assert contract is None

    def test_returns_none_when_strike_not_in_chain(self):
        adapter = _make_adapter()

        with patch.object(adapter, "get_ltp", return_value=24350.0), \
             patch.object(adapter, "get_option_quote", return_value=None):
            contract = adapter.get_option_contract("NIFTY", "CE")

        assert contract is None

    def test_returns_none_for_unknown_instrument(self):
        adapter = _make_adapter()

        contract = adapter.get_option_contract("UNKNOWN_INSTRUMENT", "CE")
        assert contract is None


# ---------------------------------------------------------------------------
# place_order
# ---------------------------------------------------------------------------

class TestPlaceOrder:
    def _make_order(self) -> OrderRequest:
        return OrderRequest(
            symbol="NSE_FO|12345",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=65,
            algo_id="ALGO_001",
        )

    def test_returns_order_id_on_success(self):
        adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "success", "data": {"order_id": "ORD_123"}}

        with patch("requests.post", return_value=mock_resp):
            order_id = adapter.place_order(self._make_order())

        assert order_id == "ORD_123"

    def test_raises_on_http_error(self):
        adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="HTTP 500"):
                adapter.place_order(self._make_order())

    def test_raises_on_api_rejection(self):
        adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "error", "message": "Insufficient margin"}

        with patch("requests.post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="rejected"):
                adapter.place_order(self._make_order())

    def test_raises_without_algo_id(self):
        adapter = _make_adapter()
        bad_order = OrderRequest(
            symbol="NSE_FO|12345",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=65,
            algo_id="",  # empty — should raise
        )
        with pytest.raises(ValueError, match="algo_id"):
            adapter.place_order(bad_order)

    def test_payload_includes_algo_tag(self):
        adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "success", "data": {"order_id": "X1"}}

        with patch("requests.post", return_value=mock_resp) as mock_post:
            adapter.place_order(self._make_order())

        payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1]["json"]
        assert payload["tag"] == "ASTRA_ALGO_001"
        assert payload["transaction_type"] == "BUY"
        assert payload["order_type"] == "MARKET"

    def test_raises_when_not_authenticated(self):
        adapter = _make_adapter(access_token="")  # no token
        with pytest.raises(RuntimeError, match="Not authenticated"):
            adapter.place_order(self._make_order())


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------

class TestCancelOrder:
    def test_returns_true_on_success(self):
        adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch("requests.delete", return_value=mock_resp):
            result = adapter.cancel_order("ORD_123")

        assert result is True

    def test_returns_false_when_already_filled(self):
        adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Order already filled"

        with patch("requests.delete", return_value=mock_resp):
            result = adapter.cancel_order("ORD_123")

        assert result is False  # not a hard error — order just filled before cancel

    def test_raises_on_unexpected_server_error(self):
        adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        mock_resp.text = "Service Unavailable"

        with patch("requests.delete", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="503"):
                adapter.cancel_order("ORD_123")


# ---------------------------------------------------------------------------
# get_positions
# ---------------------------------------------------------------------------

class TestGetPositions:
    def test_returns_positions_list(self):
        adapter = _make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "status": "success",
            "data": [
                {"instrument_token": "NSE_FO|12345", "quantity": 65, "average_price": 145.0}
            ],
        }

        with patch("requests.get", return_value=mock_resp):
            positions = adapter.get_positions()

        assert len(positions) == 1
        assert positions[0]["instrument_token"] == "NSE_FO|12345"

    def test_returns_empty_list_on_failure(self):
        adapter = _make_adapter()

        with patch("requests.get", side_effect=ConnectionError("Network error")):
            positions = adapter.get_positions()

        assert positions == []
