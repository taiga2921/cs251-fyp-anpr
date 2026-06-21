"""Backend client placeholder for M2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FlushQueueResult:
    """Result of a backend queue flush attempt."""

    success: bool
    message: str
    processed: int = 0


class BackendClient:
    """Placeholder backend client with no network side effects."""

    def flush_queue(self) -> FlushQueueResult:
        """Report that backend integration is not implemented yet."""
        return FlushQueueResult(
            success=True,
            message=(
                "Backend queue flushing is not implemented. "
                "Backend integration begins in a later milestone. "
                "No queue items were processed."
            ),
            processed=0,
        )
