"""Pre-growth reservations for owned logical temporary bytes, not published assets."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import threading


class TemporaryBudgetError(ValueError):
    pass


class TemporaryBudget:
    def __init__(self, limit: int):
        if type(limit) is not int or limit <= 0:
            raise ValueError('Temporary byte limit must be positive')
        self.limit = limit
        self.current_bytes = self.peak_bytes = 0
        self.lock = threading.Lock()

    def change(self, delta: int) -> None:
        with self.lock:
            if self.current_bytes + delta > self.limit:
                raise TemporaryBudgetError(f'Temporary storage budget exceeded ({self.limit} bytes); no file growth allowed')
            self.current_bytes += delta
            self.peak_bytes = max(self.peak_bytes, self.current_bytes)


_BUDGET: ContextVar[TemporaryBudget | None] = ContextVar('framecleave_temp_budget', default=None)


@contextmanager
def temporary_budget(limit: int | TemporaryBudget | None):
    budget = limit if isinstance(limit, TemporaryBudget) else TemporaryBudget(limit) if limit is not None else None
    token = _BUDGET.set(budget)
    try:
        yield budget
    finally:
        _BUDGET.reset(token)


def available_temp(default: int) -> int:
    budget = _BUDGET.get()
    if budget is None:
        return default
    with budget.lock:
        return min(default, budget.limit-budget.current_bytes)


class Reservation:
    def __init__(self, amount: int = 0):
        self.budget = _BUDGET.get()
        self.amount = 0
        self.grow(amount)

    def grow(self, amount: int) -> None:
        if amount > self.amount:
            if self.budget:
                self.budget.change(amount-self.amount)
            self.amount = amount

    def close(self) -> None:
        if self.budget:
            self.budget.change(-self.amount)
        self.amount = 0


@contextmanager
def reserve_temp(amount: int):
    reservation = Reservation(amount)
    try:
        yield reservation
    finally:
        reservation.close()
