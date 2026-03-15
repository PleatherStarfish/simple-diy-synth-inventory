from __future__ import annotations

from eurorack_inventory.domain.models import BomLine, Build, BuildUpdate, Project
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.projects import ProjectRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.services.common import make_project_fingerprint


class ProjectService:
    def __init__(
        self,
        project_repo: ProjectRepository,
        part_repo: PartRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self.project_repo = project_repo
        self.part_repo = part_repo
        self.audit_repo = audit_repo

    def upsert_project(
        self,
        *,
        name: str,
        maker: str = "Nonlinearcircuits",
        revision: str | None = None,
        source_url: str | None = None,
        notes: str | None = None,
    ) -> Project:
        project = Project(
            id=None,
            fingerprint=make_project_fingerprint(name=name, maker=maker, revision=revision),
            name=name,
            maker=maker,
            revision=revision,
            source_url=source_url,
            notes=notes,
        )
        saved = self.project_repo.upsert_project(project)
        self.audit_repo.add_event(
            event_type="project.upserted",
            entity_type="project",
            entity_id=saved.id,
            message=f"Upserted project {saved.name}",
            payload={"maker": saved.maker, "revision": saved.revision},
        )
        return saved

    def add_bom_line(
        self,
        *,
        project_id: int,
        part_id: int,
        qty_required: int,
        reference_note: str | None = None,
        is_optional: bool = False,
    ) -> BomLine:
        bom = self.project_repo.add_bom_line(
            BomLine(
                id=None,
                project_id=project_id,
                part_id=part_id,
                qty_required=qty_required,
                reference_note=reference_note,
                is_optional=is_optional,
            )
        )
        self.audit_repo.add_event(
            event_type="bom.added",
            entity_type="project",
            entity_id=project_id,
            message=f"Added BOM line part_id={part_id}",
            payload={"qty_required": qty_required, "is_optional": is_optional},
        )
        return bom

    def create_build(
        self,
        *,
        project_id: int,
        nickname: str | None = None,
        status: str = "planned",
        notes: str | None = None,
    ) -> Build:
        build = self.project_repo.create_build(
            Build(id=None, project_id=project_id, nickname=nickname, status=status, notes=notes)
        )
        self.audit_repo.add_event(
            event_type="build.created",
            entity_type="build",
            entity_id=build.id,
            message=f"Created build for project_id={project_id}",
            payload={"status": status},
        )
        return build

    def add_build_update(
        self,
        *,
        build_id: int,
        status: str | None,
        note: str,
    ) -> BuildUpdate:
        update = self.project_repo.add_build_update(
            BuildUpdate(id=None, build_id=build_id, created_at=None, status=status, note=note)
        )
        self.audit_repo.add_event(
            event_type="build.updated",
            entity_type="build",
            entity_id=build_id,
            message="Added build update",
            payload={"status": status},
        )
        return update

    def rename_project(self, project_id: int, new_name: str) -> None:
        """Rename a project."""
        project = self.project_repo.get_project(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")
        old_name = project.name
        self.project_repo.rename_project(project_id, new_name)
        self.audit_repo.add_event(
            event_type="project.renamed",
            entity_type="project",
            entity_id=project_id,
            message=f"Renamed project '{old_name}' to '{new_name}'",
        )

    def list_projects(self) -> list[Project]:
        return self.project_repo.list_projects()

    def list_builds(self, project_id: int) -> list[Build]:
        return self.project_repo.list_builds(project_id)

    def get_project_availability(self, project_id: int) -> list[dict]:
        bom_lines = self.project_repo.list_bom_lines(project_id)
        summaries = {summary.part_id: summary for summary in self.part_repo.list_inventory_summaries()}
        results: list[dict] = []
        for line in bom_lines:
            summary = summaries.get(line.part_id)
            total_qty = summary.total_qty if summary else 0
            results.append(
                {
                    "part_id": line.part_id,
                    "qty_required": line.qty_required,
                    "qty_available": total_qty,
                    "enough_stock": total_qty >= line.qty_required,
                    "reference_note": line.reference_note,
                    "is_optional": line.is_optional,
                }
            )
        return results

    def counts(self) -> dict[str, int]:
        return {
            "projects": self.project_repo.count_projects(),
        }
