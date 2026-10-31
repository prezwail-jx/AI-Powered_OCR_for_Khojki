"""Conservative shared attempt ledger. Unknown charges never become free retries."""

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from filelock import FileLock

from .config import ProviderConfig
from .schemas import TokenUsage
from .storage import atomic_json

MILLION = Decimal(1000000)


class BudgetError(ValueError):
    pass


def money(value) -> Decimal:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise BudgetError("Invalid monetary amount")
    return amount


def rate_ready(settings: ProviderConfig):
    if settings.pricing is None:
        raise BudgetError("Verified pricing and input-token bound are required before execution")
    if settings.pricing.model != settings.model:
        raise BudgetError("Pricing model does not match request model")
    return settings.pricing


def reservation_cost(settings: ProviderConfig) -> Decimal:
    rates = rate_ready(settings)
    return (rates.max_input_tokens * rates.input_per_million_usd + settings.max_output_tokens * rates.output_per_million_usd) / MILLION


def usage_cost(settings: ProviderConfig, usage: TokenUsage) -> Decimal:
    rates = rate_ready(settings)
    # Conservative cache-miss pricing for all input. Reasoning is a subset of
    # output_tokens, not an extra amount to bill a second time.
    return (usage.input_tokens * rates.input_per_million_usd + usage.output_tokens * rates.output_per_million_usd) / MILLION


class BudgetLedger:
    def __init__(self, path: Path, cap: Decimal):
        self.path = path
        self.cap = money(cap)
        if not 0 < self.cap <= 15:
            raise BudgetError("Budget must be greater than zero and at most USD 15")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(path) + ".lock", timeout=10)

    def _load(self):
        if not self.path.exists():
            return {"version": 1, "cap_usd": str(self.cap), "entries": []}
        try:
            ledger = json.loads(self.path.read_text(encoding="utf-8"))
            if ledger["version"] != 1 or money(ledger["cap_usd"]) != self.cap or not isinstance(ledger["entries"], list):
                raise ValueError("Ledger version or cap mismatch")
            ids = set()
            for entry in ledger["entries"]:
                if entry["id"] in ids or entry["state"] not in ("reserved", "unknown", "usage_estimate"):
                    raise ValueError("Ledger entries invalid")
                ids.add(entry["id"])
                money(entry["accounted_usd"])
                money(entry["reserved_usd"])
            return ledger
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise BudgetError("Invalid ledger or changed budget cap; review before execution") from exc

    def reserve(self, key, provider, settings: ProviderConfig):
        amount = reservation_cost(settings)
        with self.lock:
            ledger = self._load()
            if any(entry.get("bound_exceeded") for entry in ledger["entries"]):
                raise BudgetError("A previous token bound was exceeded; reconcile before further calls")
            accounted = sum((money(entry["accounted_usd"]) for entry in ledger["entries"]), Decimal(0))
            if accounted + amount > self.cap:
                raise BudgetError("Insufficient remaining budget for another complete attempt")
            entry = {"id": uuid.uuid4().hex, "request_key": key, "provider": provider, "model": settings.model,
                     "created_at": datetime.now(timezone.utc).isoformat(), "state": "reserved",
                     "reserved_usd": str(amount), "accounted_usd": str(amount),
                     "pricing": settings.pricing.model_dump(mode="json")}
            ledger["entries"].append(entry)
            atomic_json(self.path, ledger)
            return entry["id"], amount

    def settle(self, reservation_id, usage: TokenUsage | None, settings: ProviderConfig):
        with self.lock:
            ledger = self._load()
            entry = next((entry for entry in ledger["entries"] if entry["id"] == reservation_id), None)
            if entry is None or entry["state"] != "reserved":
                raise BudgetError("Reservation absent or already finalized")
            if usage is None:
                entry["state"] = "unknown"
            else:
                amount = usage_cost(settings, usage)
                entry.update({"state": "usage_estimate", "accounted_usd": str(amount), "usage": usage.model_dump(),
                              "bound_exceeded": usage.input_tokens > settings.pricing.max_input_tokens or usage.output_tokens > settings.max_output_tokens})
            atomic_json(self.path, ledger)
            return entry.copy()

    def summary(self):
        with self.lock:
            ledger = self._load()
        accounted = sum((money(entry["accounted_usd"]) for entry in ledger["entries"]), Decimal(0))
        return {"cap_usd": str(self.cap), "accounted_usd": str(accounted), "remaining_usd": str(self.cap - accounted),
                "attempts": len(ledger["entries"]),
                "unknown_or_reserved_attempts": sum(entry["state"] != "usage_estimate" for entry in ledger["entries"])}
