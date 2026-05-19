from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from customer_orchestrator.models import CustomerRequest, RequestKind, WorkflowResponse


@dataclass(slots=True)
class PendingRequest:
    kind: RequestKind
    payload: CustomerRequest
    future: asyncio.Future[WorkflowResponse]


@dataclass(slots=True)
class UserQueue:
    regular: deque[PendingRequest] = field(default_factory=deque)
    id_card: deque[PendingRequest] = field(default_factory=deque)
    active_regular: int = 0
    active_id_card: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class RequestScheduler:
    def __init__(
        self,
        runner: Callable[[RequestKind, CustomerRequest], Awaitable[WorkflowResponse]],
        max_parallel_requests: int = 32,
    ) -> None:
        self._runner = runner
        self._queues: dict[str, UserQueue] = {}
        self._global_gate = asyncio.Semaphore(max_parallel_requests)

    async def submit(self, kind: RequestKind, payload: CustomerRequest) -> WorkflowResponse:
        loop = asyncio.get_running_loop()
        queue = self._queues.setdefault(payload.user_id, UserQueue())
        pending = PendingRequest(kind=kind, payload=payload, future=loop.create_future())

        async with queue.lock:
            if kind == RequestKind.ID_CARD_CHANGE:
                queue.id_card.append(pending)
            else:
                queue.regular.append(pending)
            self._dispatch_locked(payload.user_id, queue)

        return await pending.future

    def _dispatch_locked(self, user_id: str, queue: UserQueue) -> None:
        while queue.regular:
            pending = queue.regular.popleft()
            queue.active_regular += 1
            asyncio.create_task(self._run_regular(user_id, queue, pending))

        if queue.active_regular == 0 and not queue.active_id_card and queue.id_card:
            pending = queue.id_card.popleft()
            queue.active_id_card = True
            asyncio.create_task(self._run_id_card(user_id, queue, pending))

    async def _run_regular(self, user_id: str, queue: UserQueue, pending: PendingRequest) -> None:
        await self._run_pending(user_id, queue, pending, is_id_card=False)

    async def _run_id_card(self, user_id: str, queue: UserQueue, pending: PendingRequest) -> None:
        await self._run_pending(user_id, queue, pending, is_id_card=True)

    async def _run_pending(
        self,
        user_id: str,
        queue: UserQueue,
        pending: PendingRequest,
        *,
        is_id_card: bool,
    ) -> None:
        try:
            async with self._global_gate:
                result = await self._runner(pending.kind, pending.payload)
            if not pending.future.done():
                pending.future.set_result(result)
        except Exception as exc:
            if not pending.future.done():
                pending.future.set_exception(exc)
        finally:
            async with queue.lock:
                if is_id_card:
                    queue.active_id_card = False
                else:
                    queue.active_regular -= 1

                self._dispatch_locked(user_id, queue)
                if (
                    queue.active_regular == 0
                    and not queue.active_id_card
                    and not queue.regular
                    and not queue.id_card
                ):
                    self._queues.pop(user_id, None)
