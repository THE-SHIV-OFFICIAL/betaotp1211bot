#MADE_BY_SHIV
"""BETA BOT HUB payment gateway (auto-verified UPI).

Docs: https://betapaymentgateway.up.railway.app/#docs
  POST /api/v1/payments/create   -> create order (QR + pay link)
  GET  /api/v1/payments/<id>     -> {"verified": bool, "order": {"status": PENDING|PAID|EXPIRED}}
"""
import os
import json
import aiohttp

PAYGATE_URL = os.getenv("PAYGATE_URL", "https://betapaymentgateway.up.railway.app").rstrip("/")


def _key() -> str:
    """Admin setting > PAYGATE_API_KEY environment secret; never fall back to a source-code key."""
    try:
        from database import cur
        row = cur.execute("SELECT value FROM settings WHERE key='paygate_key'").fetchone()
        if row and row[0]: return row[0].strip()
    except Exception:
        pass
    return (os.getenv("PAYGATE_API_KEY") or "").strip()

PAYGATE_API_KEY = _key()

_TIMEOUT = aiohttp.ClientTimeout(total=20)


_session = None


def get_http_session() -> aiohttp.ClientSession:
    """One shared keep-alive session (no socket leak, faster requests)."""
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(limit=100, keepalive_timeout=60), timeout=_TIMEOUT)
    return _session


async def close_http_session():
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


class PayGateError(Exception):
    pass

async def _request_json(method, url: str, **kwargs) -> dict:
    """Call the gateway and always return parsed JSON.

    The gateway (or Railway edge) sometimes answers with plain text like
    "rate limited" (HTTP 429) or an HTML error page. Parsing that as JSON
    crashes with 'Expecting value: line 1 column 1'. Instead, check the
    status first, retry 429s briefly, and raise a clear PayGateError.
    """
    import asyncio
    last_err = "no response"
    for attempt in range(3):
        async with method(url, **kwargs) as r:
            raw = await r.text()
            if r.status == 429:
                last_err = "gateway rate limited (HTTP 429) - too many requests, try again in a minute"
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status >= 500:
                last_err = f"gateway server error (HTTP {r.status})"
                await asyncio.sleep(2 * (attempt + 1))
                continue
            if r.status != 200:
                raise PayGateError(f"gateway HTTP {r.status}: {raw[:200]}")
            try:
                return json.loads(raw)
            except Exception:
                raise PayGateError(f"gateway returned non-JSON: {raw[:200]}")
    raise PayGateError(last_err)



def _headers():
    k = _key()
    if not k:
        raise PayGateError("PAYGATE_API_KEY is not set")
    return {"Authorization": f"Bearer {k}", "Content-Type": "application/json"}


def is_enabled() -> bool:
    return bool(_key())


async def create_payment(amount: int, note: str = "", customer_email: str = "") -> dict:
    """Returns the order dict: orderId, payAmount, qrImageUrl, upiUri, payUrl, expiresAt ..."""
    body = {"amount": amount, "note": note}
    if customer_email:
        body["customerEmail"] = customer_email
    s = get_http_session()
    data = await _request_json(s.post, f"{PAYGATE_URL}/api/v1/payments/create", json=body, headers=_headers())
    if not data.get("success") or not data.get("order", {}).get("orderId"):
        raise PayGateError(str(data.get("error") or data.get("message") or data))
    return data["order"]


async def get_status(order_id: str) -> tuple[str, bool, dict]:
    """Returns (status, verified, order)."""
    s = get_http_session()
    data = await _request_json(s.get, f"{PAYGATE_URL}/api/v1/payments/{order_id}", headers=_headers())
    order = data.get("order") or {}
    return str(order.get("status", "PENDING")).upper(), bool(data.get("verified")), order
