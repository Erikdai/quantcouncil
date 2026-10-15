"""A-share symbol conventions and shared vendor plumbing (retry, cache).

Every accepted spelling (600519, 600519.SH, sh600519, sh.600519) resolves to the
Yahoo-style canonical form the core uses (600519.SS, 000001.SZ, 430047.BJ). An
explicit suffix wins over the code range: 000001.SS is the SSE Composite index.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import pickle
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from tradingagents.dataflows.errors import VendorUnavailableError

logger = logging.getLogger(__name__)

_A_SHARE_RE = re.compile(
    r"^(?:(?P<prefix>SH|SZ|BJ)\.?)?(?P<code>\d{6})(?:\.(?P<suffix>SH|SS|SZ|BJ))?$",
    re.IGNORECASE,
)

# Indices the agents may use as a benchmark, keyed by canonical symbol.
CN_INDICES: dict[str, tuple[str, str]] = {
    "000300.SS": ("sh000300", "CSI 300 (沪深300)"),
    "000001.SS": ("sh000001", "SSE Composite (上证指数)"),
    "000016.SS": ("sh000016", "SSE 50 (上证50)"),
    "000905.SS": ("sh000905", "CSI 500 (中证500)"),
    "000852.SS": ("sh000852", "CSI 1000 (中证1000)"),
    "000688.SS": ("sh000688", "STAR 50 (科创50)"),
    "399001.SZ": ("sz399001", "SZSE Component (深证成指)"),
    "399006.SZ": ("sz399006", "ChiNext (创业板指)"),
}

DEFAULT_CN_BENCHMARK = "000300.SS"


@dataclass(frozen=True)
class AShare:
    """A parsed A-share symbol: six-digit code and exchange (SH, SZ or BJ)."""

    code: str
    exchange: str

    @property
    def canonical(self) -> str:
        return f"{self.code}.{'SS' if self.exchange == 'SH' else self.exchange}"

    @property
    def prefixed(self) -> str:
        """Sina / Tencent form: ``sh600519``."""
        return f"{self.exchange.lower()}{self.code}"

    @property
    def baostock(self) -> str:
        """BaoStock form: ``sh.600519``."""
        return f"{self.exchange.lower()}.{self.code}"

    @property
    def eastmoney(self) -> str:
        """Eastmoney datacenter form: ``SH600519``."""
        return f"{self.exchange}{self.code}"

    @property
    def board(self) -> str:
        """Listing board, which sets the daily price limit."""
        if self.exchange == "BJ":
            return "bse"
        if self.code.startswith(("688", "689")):
            return "star"
        if self.code.startswith("30"):
            return "chinext"
        return "main"


def exchange_for_code(code: str) -> str:
    """Exchange of a bare six-digit code by the CSRC numbering ranges."""
    if code.startswith("92") or code[0] in "48":
        return "BJ"
    if code[0] in "569":
        return "SH"
    if code[0] in "0123":
        return "SZ"
    raise ValueError(f"{code!r} is not in any A-share code range")


def parse_a_share(symbol: str) -> AShare:
    """Parse any accepted A-share spelling; raises ValueError for anything else."""
    if not isinstance(symbol, str):
        raise ValueError(f"not an A-share symbol: {symbol!r}")
    m = _A_SHARE_RE.match(symbol.strip())
    if not m:
        raise ValueError(f"not an A-share symbol: {symbol!r}")
    code = m.group("code")
    marker = (m.group("suffix") or m.group("prefix") or "").upper()
    exchange = {"SS": "SH", "SH": "SH", "SZ": "SZ", "BJ": "BJ"}.get(marker) or exchange_for_code(code)
    return AShare(code=code, exchange=exchange)


def is_a_share(symbol: str) -> bool:
    """Whether ``symbol`` names a mainland-listed instrument (stock, fund or index)."""
    try:
        parse_a_share(symbol)
        return True
    except ValueError:
        return False


def canonical_symbol(symbol: str) -> str:
    """The canonical (Yahoo-suffix) spelling, e.g. ``600519`` -> ``600519.SS``."""
    return parse_a_share(symbol).canonical


def is_cn_index(symbol: str) -> bool:
    try:
        return canonical_symbol(symbol) in CN_INDICES
    except ValueError:
        return False


def price_limit_pct(symbol: str, is_st: bool = False) -> float:
    """Daily up/down limit as a fraction of the previous close.

    Main board 10% (ST 5%), ChiNext and STAR 20%, Beijing Stock Exchange 30%.
    ChiNext/STAR ST names keep 20% since the 2020 registration reform.
    """
    board = parse_a_share(symbol).board
    if board == "bse":
        return 0.30
    if board in ("star", "chinext"):
        return 0.20
    return 0.05 if is_st else 0.10


def limit_prices(symbol: str, prev_close: float, is_st: bool = False) -> tuple[float, float]:
    """(limit-up, limit-down) prices, rounded to the fen as the exchanges do."""
    pct = price_limit_pct(symbol, is_st)
    return round(prev_close * (1 + pct) + 1e-9, 2), round(prev_close * (1 - pct) + 1e-9, 2)


def ymd(date: str) -> str:
    """``2026-10-14`` -> ``20261014`` (the compact form most akshare calls take)."""
    return date.replace("-", "")


# --- Lazy vendor modules ------------------------------------------------------
# akshare imports in ~2s and pulls a long dependency tail; import it on first use
# so the CLI and every non-China run stay fast.

@functools.lru_cache(maxsize=1)
def akshare():
    import akshare as ak  # noqa: PLC0415

    return ak


# --- Retry --------------------------------------------------------------------

def _transient(exc: BaseException) -> bool:
    """Network-shaped failures worth retrying: socket/HTTP errors and akshare's
    NetworkError / RateLimitError (which do not subclass OSError)."""
    if isinstance(exc, (ConnectionError, TimeoutError, OSError)):
        return True
    return type(exc).__name__ in {"NetworkError", "RateLimitError", "ChunkedEncodingError", "ReadTimeout"}


def call_vendor(name: str, fn: Callable[[], Any], attempts: int = 3, backoff: float = 0.8) -> Any:
    """Call a vendor endpoint, retrying transient failures, then raise VendorUnavailableError.

    China data sites drop connections under load and rate-limit by IP; a short
    exponential backoff rides out most of it. Anything still failing is the
    vendor's problem, not the instrument's, so the router moves to the next
    vendor instead of reporting "no data". Any other exception (an error page,
    a changed payload) fails over at once: retrying rarely helps.
    """
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 — every vendor failure maps to one typed error
            if not _transient(exc):
                raise VendorUnavailableError(f"{name}: unexpected response ({type(exc).__name__}: {exc})") from exc
            last = exc
        if attempt + 1 < attempts:
            time.sleep(backoff * (2 ** attempt))
    raise VendorUnavailableError(f"{name}: {type(last).__name__}: {last}") from last


# --- Cache --------------------------------------------------------------------

class CacheBackend(Protocol):
    def get(self, key: str) -> bytes | None: ...
    def set(self, key: str, value: bytes, ttl: int) -> None: ...


class MemoryCache:
    """Process-local TTL cache, the default when no shared cache is configured."""

    def __init__(self, max_items: int = 512):
        self._data: dict[str, tuple[float, bytes]] = {}
        self._lock = threading.Lock()
        self._max = max_items

    def get(self, key: str) -> bytes | None:
        with self._lock:
            hit = self._data.get(key)
            if hit is None:
                return None
            expires, value = hit
            if expires < time.monotonic():
                self._data.pop(key, None)
                return None
            return value

    def set(self, key: str, value: bytes, ttl: int) -> None:
        with self._lock:
            if len(self._data) >= self._max and key not in self._data:
                # Drop the entry closest to expiry; cheap and good enough here.
                oldest = min(self._data, key=lambda k: self._data[k][0])
                self._data.pop(oldest, None)
            self._data[key] = (time.monotonic() + ttl, value)


_cache_backend: CacheBackend = MemoryCache()


def set_cache_backend(backend: CacheBackend) -> None:
    """Install a shared cache (the platform layer installs Redis here)."""
    global _cache_backend
    _cache_backend = backend


def get_cache_backend() -> CacheBackend:
    return _cache_backend


def cached(ttl: int, namespace: str) -> Callable:
    """Cache a vendor call's result (picklable) for ``ttl`` seconds by its arguments.

    Only successful results are cached; a raised VendorError is not, so a
    transient outage is retried on the next call.
    """

    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            raw = repr((args, sorted(kwargs.items()))).encode()
            key = f"finagent:cn:{namespace}:{hashlib.sha1(raw).hexdigest()}"
            backend = _cache_backend
            try:
                hit = backend.get(key)
            except Exception as exc:  # noqa: BLE001 — a cache outage must not fail the data call
                logger.debug("cache get failed for %s: %s", key, exc)
                hit = None
            if hit is not None:
                return pickle.loads(hit)  # noqa: S301 — values are written by this process family only
            value = fn(*args, **kwargs)
            try:
                backend.set(key, pickle.dumps(value), ttl)
            except Exception as exc:  # noqa: BLE001
                logger.debug("cache set failed for %s: %s", key, exc)
            return value

        wrapper.uncached = fn  # type: ignore[attr-defined]
        return wrapper

    return decorator
