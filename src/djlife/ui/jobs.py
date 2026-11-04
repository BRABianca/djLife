"""Infraestrutura de tarefas longas disparadas pela interface web.

Cada tarefa roda em thread daemon e expoe um `snapshot()` serializavel para
polling em `/api/organize/job` e `/api/premium/job`. Compartilhado pelos fluxos
de organizacao e de download.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskJob:
    """Andamento de uma tarefa longa disparada pela interface."""

    task: str
    status: str = "running"
    message: str | None = None
    result: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "status": self.status,
            "message": self.message,
            "result": dict(self.result),
        }


def idle_snapshot(task: str) -> dict[str, Any]:
    return {"task": task, "status": "idle", "message": None, "result": {}}
