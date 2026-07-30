"""Primitivas headless para cancelacion y deadlines de adaptadores."""

from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Awaitable, TypeVar

T = TypeVar("T")


class OperationError(RuntimeError):
    """Error operacional de una interfaz headless."""


class OperationCancelled(OperationError):
    """La operacion fue cancelada por su consumidor."""


class OperationDeadlineExceeded(OperationError):
    """La operacion no termino antes de su deadline."""


@dataclass(frozen=True)
class OperationContext:
    """Contexto propagable; el deadline usa el reloj monotonic del proceso."""

    deadline: float | None = None
    cancel_event: asyncio.Event | None = None

    @classmethod
    def with_timeout(
        cls,
        timeout: float,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> "OperationContext":
        if timeout <= 0:
            raise ValueError("timeout debe ser positivo")
        return cls(time.monotonic() + timeout, cancel_event)

    def remaining(self) -> float | None:
        if self.deadline is None:
            return None
        return max(0.0, self.deadline - time.monotonic())

    def raise_if_cancelled(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise OperationCancelled("operacion cancelada")
        if self.deadline is not None and self.remaining() == 0:
            raise OperationDeadlineExceeded("deadline agotado")


async def await_operation(
    awaitable: Awaitable[T],
    context: OperationContext | None = None,
    *,
    cancel_work: bool = True,
) -> T:
    """Espera trabajo con deadline y cancelacion sin esconder su causa."""

    ctx = context or OperationContext()
    try:
        ctx.raise_if_cancelled()
    except OperationError:
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise
    work = asyncio.ensure_future(awaitable)
    cancel_waiter: asyncio.Task[bool] | None = None
    if ctx.cancel_event is not None:
        cancel_waiter = asyncio.create_task(ctx.cancel_event.wait())
    waiters = {work}
    if cancel_waiter is not None:
        waiters.add(cancel_waiter)
    try:
        done, _ = await asyncio.wait(
            waiters,
            timeout=ctx.remaining(),
            return_when=asyncio.FIRST_COMPLETED,
        )
        if work in done:
            return await work
        if cancel_work and not work.done():
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
        if cancel_waiter is not None and cancel_waiter in done:
            raise OperationCancelled("operacion cancelada")
        raise OperationDeadlineExceeded("deadline agotado")
    finally:
        if cancel_waiter is not None:
            cancel_waiter.cancel()
            await asyncio.gather(cancel_waiter, return_exceptions=True)
