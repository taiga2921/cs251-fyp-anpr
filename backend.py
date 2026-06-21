"""Backend client placeholder for M1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FlushQueueResult:
    """Result of a backend queue flush attempt."""

    success: bool
    message: str
    processed: int = 0


class BackendClient:
    """Placeholder backend client with no network side effects in M1."""

    def flush_queue(self) -> FlushQueueResult:
        """Report that backend queue flushing is not implemented yet."""
        return FlushQueueResult(
            success=True,
            message=(
                "Backend queue flushing is not implemented in M2. "
                "No queue items were processed."
            ),
            processed=0,
        )
