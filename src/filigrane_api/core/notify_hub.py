from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SseEnvelope:
    event: str | None = None
    data: dict[str, Any] | None = None
    sse_id: str | None = None


class NotifyHub:
    """In-memory pub/sub hub suitable for single worker deployments."""

    def __init__(self) -> None:
        self._channels: defaultdict[
            int,
            list[asyncio.Queue[SseEnvelope]],
        ] = defaultdict(list)

    def subscribe(
        self, user_id: int
    ) -> tuple[
        asyncio.Queue[SseEnvelope],
        Callable[[], None],
    ]:
        queue: asyncio.Queue[SseEnvelope] = asyncio.Queue(maxsize=200)
        buckets = self._channels[user_id]
        buckets.append(queue)

        def unsubscribe() -> None:
            try:
                buckets.remove(queue)
            except ValueError:
                return

        return queue, unsubscribe

    async def publish(self, user_id: int, envelope: SseEnvelope) -> None:
        for subscriber in list(self._channels[user_id]):
            await subscriber.put(envelope)


async def publish_many(
    hub: NotifyHub,
    user_ids: Iterable[int],
    envelope: SseEnvelope,
) -> None:
    unique_ids = sorted({uid for uid in user_ids})
    await asyncio.gather(*(hub.publish(uid, envelope) for uid in unique_ids))
