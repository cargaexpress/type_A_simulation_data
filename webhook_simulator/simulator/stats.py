"""Counters for one simulator run."""

from collections import Counter
from dataclasses import dataclass, field


@dataclass(slots=True)
class RunStats:
    sent: int = 0  # messages sent (or printed, in dry-run)
    delivered: int = 0  # 2xx responses
    failed: int = 0  # network errors or non-2xx responses
    unique_events: int = 0
    duplicates: int = 0
    out_of_order: int = 0
    per_carrier: Counter = field(default_factory=Counter)
    per_status: Counter = field(default_factory=Counter)

    def as_dict(self) -> dict:
        return {
            "sent": self.sent,
            "delivered": self.delivered,
            "failed": self.failed,
            "unique_events": self.unique_events,
            "duplicates": self.duplicates,
            "out_of_order": self.out_of_order,
            "per_carrier": dict(sorted(self.per_carrier.items())),
            "distinct_statuses": len(self.per_status),
        }
