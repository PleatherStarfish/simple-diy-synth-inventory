"""Tests for AssignmentDialog part-selection UI."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.domain.enums import StorageClass
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.assignment import AssignmentScope, AssignmentService
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.settings import SettingsRepository
from eurorack_inventory.services.storage import StorageService

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"


@pytest.fixture()
def services(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    MigrationRunner(db, MIGRATIONS_DIR).apply()
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    part_repo = PartRepository(db)
    storage_svc = StorageService(storage_repo, audit_repo)
    inventory_svc = InventoryService(part_repo, storage_repo, audit_repo)
    settings_repo = SettingsRepository(db)
    assignment_svc = AssignmentService(part_repo, storage_repo, audit_repo, settings_repo)
    storage_svc.ensure_default_unassigned_slot()
    yield {
        "assignment_svc": assignment_svc,
        "storage_svc": storage_svc,
        "inventory_svc": inventory_svc,
        "part_repo": part_repo,
        "storage_repo": storage_repo,
        "db": db,
    }
    db.close()


def _skip_if_no_qt():
    """Skip test if Qt display is unavailable."""
    try:
        from PySide6.QtWidgets import QApplication
        if QApplication.instance() is None:
            QApplication([])
    except Exception:
        pytest.skip("Qt display unavailable")


class TestAssignmentDialogPartSelection:
    def test_dialog_seeds_from_preselection(self, services):
        _skip_if_no_qt()
        from eurorack_inventory.ui.assignment_dialog import AssignmentDialog

        svc = services
        svc["storage_svc"].configure_grid_box(name="Box 1", rows=2, cols=2)
        p1 = svc["inventory_svc"].upsert_part(name="100R 0805", category="Resistors", qty=10)
        p2 = svc["inventory_svc"].upsert_part(name="220R 0805", category="Resistors", qty=10)

        dialog = AssignmentDialog(
            assignment_service=svc["assignment_svc"],
            categories=["Resistors"],
            selected_part_ids=[p1.id],
            part_repo=svc["part_repo"],
            storage_repo=svc["storage_repo"],
        )

        # The "Selected parts" radio should be enabled
        assert dialog._radio_selected.isEnabled()

        # The part table should exist and p1 should be checked/selected
        assert hasattr(dialog, "_part_table")
        selected_ids = dialog._get_selected_part_ids()
        assert p1.id in selected_ids

    def test_dialog_allows_selection_without_preselection(self, services):
        _skip_if_no_qt()
        from eurorack_inventory.ui.assignment_dialog import AssignmentDialog

        svc = services
        svc["storage_svc"].configure_grid_box(name="Box 1", rows=2, cols=2)
        p1 = svc["inventory_svc"].upsert_part(name="100R 0805", category="Resistors", qty=10)
        p2 = svc["inventory_svc"].upsert_part(name="220R 0805", category="Resistors", qty=10)

        dialog = AssignmentDialog(
            assignment_service=svc["assignment_svc"],
            categories=["Resistors"],
            selected_part_ids=[],
            part_repo=svc["part_repo"],
            storage_repo=svc["storage_repo"],
        )

        # "Selected parts" radio should still be enabled (dialog has its own picker)
        assert dialog._radio_selected.isEnabled()

        # Part table should exist with parts available for selection
        assert hasattr(dialog, "_part_table")

    def test_build_scope_uses_dialog_selection(self, services):
        _skip_if_no_qt()
        from eurorack_inventory.ui.assignment_dialog import AssignmentDialog

        svc = services
        svc["storage_svc"].configure_grid_box(name="Box 1", rows=2, cols=2)
        p1 = svc["inventory_svc"].upsert_part(name="100R 0805", category="Resistors", qty=10)
        p2 = svc["inventory_svc"].upsert_part(name="220R 0805", category="Resistors", qty=10)

        dialog = AssignmentDialog(
            assignment_service=svc["assignment_svc"],
            categories=["Resistors"],
            selected_part_ids=[p1.id, p2.id],
            part_repo=svc["part_repo"],
            storage_repo=svc["storage_repo"],
        )

        # Select the "Selected parts" radio
        dialog._radio_selected.setChecked(True)

        scope = dialog._build_scope()
        assert scope.all_parts is False
        assert scope.part_ids is not None
        assert set(scope.part_ids) == {p1.id, p2.id}
