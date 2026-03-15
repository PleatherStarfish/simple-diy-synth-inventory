from __future__ import annotations

from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.projects import ProjectRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository


class DashboardService:
    def __init__(
        self,
        part_repo: PartRepository,
        storage_repo: StorageRepository,
        project_repo: ProjectRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.part_repo = part_repo
        self.storage_repo = storage_repo
        self.project_repo = project_repo
        self.audit_repo = audit_repo

    def snapshot(self) -> dict:
        return {
            "parts": self.part_repo.count_parts(),
            "containers": self.storage_repo.count_containers(),
            "slots": self.storage_repo.count_slots(),
            "projects": self.project_repo.count_projects(),
            "recent_events": self.audit_repo.list_recent(limit=10),
        }
