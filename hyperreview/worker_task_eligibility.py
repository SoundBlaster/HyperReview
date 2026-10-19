"""Policy for a bounded retry of a local intake task."""

from dataclasses import dataclass
from typing import final

from specification_core import Specification, TraceRecorder


@dataclass(frozen=True, slots=True)
class WorkerTaskContext:
    state: str
    attempts: int
    retry_after: int
    now: int


@final
class WorkerTaskEligibility(Specification[WorkerTaskContext]):
    """Completed or exhausted intake tasks never repeat automatically."""

    __slots__ = ()

    def __init__(self):
        super().__init__("worker_intake_task_eligibility")
        self._seal()

    def _evaluate(self, candidate: WorkerTaskContext, recorder: TraceRecorder | None) -> bool:
        del recorder
        return (candidate.state in ("queued", "failed")
                and candidate.attempts < 2 and candidate.retry_after <= candidate.now)
