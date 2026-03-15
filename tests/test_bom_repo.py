from pathlib import Path

import pytest

from eurorack_inventory.db.connection import Database
from eurorack_inventory.db.migrations import MigrationRunner
from eurorack_inventory.domain.models import (
    BomSource,
    NormalizedBomItem,
    RawBomItem,
    utc_now_iso,
)
from eurorack_inventory.repositories.bom import BomRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.inventory import InventoryService
from eurorack_inventory.services.storage import StorageService


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "src" / "eurorack_inventory" / "db" / "migrations"


@pytest.fixture()
def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    MigrationRunner(database, MIGRATIONS_DIR).apply()
    yield database
    database.close()


@pytest.fixture()
def bom_repo(db):
    return BomRepository(db)


@pytest.fixture()
def inventory_svc(db):
    part_repo = PartRepository(db)
    storage_repo = StorageRepository(db)
    audit_repo = AuditRepository(db)
    svc = InventoryService(part_repo, storage_repo, audit_repo)
    storage_svc = StorageService(storage_repo, audit_repo)
    storage_svc.ensure_default_unassigned_slot()
    return svc


def _make_source(**overrides) -> BomSource:
    defaults = dict(
        id=None,
        filename="test.csv",
        file_path="/tmp/test.csv",
        file_hash="abc123",
        source_kind="csv",
        parser_key="nlc",
        manufacturer="Nonlinearcircuits",
        module_name="Sloth",
        extracted_at=utc_now_iso(),
        notes=None,
        promoted_project_id=None,
    )
    defaults.update(overrides)
    return BomSource(**defaults)


class TestBomSourceCRUD:
    def test_create_and_get(self, bom_repo):
        source = bom_repo.create_bom_source(_make_source())
        assert source.id is not None
        assert source.module_name == "Sloth"
        assert source.parser_key == "nlc"

        fetched = bom_repo.get_bom_source(source.id)
        assert fetched is not None
        assert fetched.filename == "test.csv"

    def test_list_sources(self, bom_repo):
        bom_repo.create_bom_source(_make_source(module_name="Sloth"))
        bom_repo.create_bom_source(_make_source(module_name="Neuron", file_hash="def456"))
        sources = bom_repo.list_bom_sources()
        assert len(sources) == 2
        names = [s.module_name for s in sources]
        assert "Neuron" in names
        assert "Sloth" in names

    def test_delete_source(self, bom_repo):
        source = bom_repo.create_bom_source(_make_source())
        bom_repo.delete_bom_source(source.id)
        assert bom_repo.get_bom_source(source.id) is None

    def test_find_by_hash_and_module(self, bom_repo):
        bom_repo.create_bom_source(_make_source(file_hash="hash1", module_name="Sloth"))
        bom_repo.create_bom_source(_make_source(file_hash="hash1", module_name="Neuron"))

        found = bom_repo.find_by_hash_and_module("hash1", "Sloth")
        assert found is not None
        assert found.module_name == "Sloth"

        assert bom_repo.find_by_hash_and_module("hash1", "4seq") is None

    def test_count(self, bom_repo):
        assert bom_repo.count_bom_sources() == 0
        bom_repo.create_bom_source(_make_source())
        assert bom_repo.count_bom_sources() == 1

    def test_set_promoted_project_id(self, bom_repo, db):
        # Create a real project for the FK
        db.execute(
            "INSERT INTO modules (fingerprint, name, maker) VALUES (?, ?, ?)",
            ("fp1", "Sloth", "NLC"),
        )
        project_id = int(db.scalar("SELECT id FROM modules WHERE fingerprint = 'fp1'"))

        source = bom_repo.create_bom_source(_make_source())
        assert source.promoted_project_id is None
        bom_repo.set_promoted_project_id(source.id, project_id)
        updated = bom_repo.get_bom_source(source.id)
        assert updated.promoted_project_id == project_id

    def test_duplicate_hash_different_module_allowed(self, bom_repo):
        """Same file_hash with different module names is allowed (combined CSV)."""
        bom_repo.create_bom_source(_make_source(file_hash="same", module_name="A"))
        bom_repo.create_bom_source(_make_source(file_hash="same", module_name="B"))
        assert bom_repo.count_bom_sources() == 2


class TestRawBomItems:
    def test_bulk_insert_and_list(self, bom_repo):
        source = bom_repo.create_bom_source(_make_source())
        items = [
            RawBomItem(id=None, bom_source_id=source.id, line_number=1,
                       raw_description="100K", raw_qty="2"),
            RawBomItem(id=None, bom_source_id=source.id, line_number=2,
                       raw_description="TL072", raw_qty="5", raw_reference="U1,U2"),
        ]
        bom_repo.add_raw_items_bulk(items)
        result = bom_repo.list_raw_items(source.id)
        assert len(result) == 2
        assert result[0].raw_description == "100K"
        assert result[1].raw_reference == "U1,U2"

    def test_cascade_delete(self, bom_repo):
        source = bom_repo.create_bom_source(_make_source())
        bom_repo.add_raw_items_bulk([
            RawBomItem(id=None, bom_source_id=source.id, line_number=1,
                       raw_description="100K", raw_qty="2"),
        ])
        assert len(bom_repo.list_raw_items(source.id)) == 1
        bom_repo.delete_bom_source(source.id)
        assert len(bom_repo.list_raw_items(source.id)) == 0


class TestNormalizedBomItems:
    def _setup(self, bom_repo):
        source = bom_repo.create_bom_source(_make_source())
        bom_repo.add_raw_items_bulk([
            RawBomItem(id=None, bom_source_id=source.id, line_number=1,
                       raw_description="100K", raw_qty="2"),
        ])
        raw_items = bom_repo.list_raw_items(source.id)
        return source, raw_items[0]

    def test_bulk_insert_and_list(self, bom_repo):
        source, raw = self._setup(bom_repo)
        items = [
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw.id,
                component_type="resistor", normalized_value="100K", qty=2,
            ),
        ]
        bom_repo.add_normalized_items_bulk(items)
        result = bom_repo.list_normalized_items(source.id)
        assert len(result) == 1
        assert result[0].normalized_value == "100K"
        assert result[0].match_status == "unmatched"
        assert result[0].is_verified is False

    def test_update_normalized_item(self, bom_repo):
        source, raw = self._setup(bom_repo)
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw.id,
                component_type="resistor", normalized_value="100K", qty=2,
            ),
        ])
        items = bom_repo.list_normalized_items(source.id)
        item = items[0]

        updated = bom_repo.update_normalized_item(
            item.id, normalized_value="100k", qty=3, is_verified=True,
        )
        assert updated.normalized_value == "100k"
        assert updated.qty == 3
        assert updated.is_verified is True

    def test_link_and_unlink_part(self, bom_repo, inventory_svc):
        source, raw = self._setup(bom_repo)
        part = inventory_svc.upsert_part(name="100K Resistor", category="Resistors", qty=10)
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw.id,
                component_type="resistor", normalized_value="100K", qty=2,
            ),
        ])
        item = bom_repo.list_normalized_items(source.id)[0]

        linked = bom_repo.link_to_part(item.id, part_id=part.id, confidence=0.95)
        assert linked.part_id == part.id
        assert linked.match_confidence == 0.95
        assert linked.match_status == "manually_matched"

        unlinked = bom_repo.unlink_part(item.id)
        assert unlinked.part_id is None
        assert unlinked.match_status == "unmatched"

    def test_list_unmatched(self, bom_repo, inventory_svc):
        source, raw = self._setup(bom_repo)
        part = inventory_svc.upsert_part(name="100K Resistor", category="Resistors", qty=10)
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw.id,
                component_type="resistor", normalized_value="100K", qty=2,
            ),
        ])
        item = bom_repo.list_normalized_items(source.id)[0]
        assert len(bom_repo.list_unmatched_items(source.id)) == 1

        bom_repo.link_to_part(item.id, part_id=part.id, confidence=0.9, status="auto_matched")
        assert len(bom_repo.list_unmatched_items(source.id)) == 0

    def test_cascade_delete_normalized(self, bom_repo):
        source, raw = self._setup(bom_repo)
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw.id,
                component_type="resistor", normalized_value="100K", qty=2,
            ),
        ])
        assert len(bom_repo.list_normalized_items(source.id)) == 1
        bom_repo.delete_bom_source(source.id)
        assert len(bom_repo.list_normalized_items(source.id)) == 0

    def test_update_ignores_unknown_fields(self, bom_repo):
        source, raw = self._setup(bom_repo)
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw.id,
                component_type="resistor", normalized_value="100K", qty=2,
            ),
        ])
        item = bom_repo.list_normalized_items(source.id)[0]
        updated = bom_repo.update_normalized_item(item.id, bogus_field="nope")
        assert updated.normalized_value == "100K"


class TestShoppingList:
    def test_basic_shopping_list(self, bom_repo, inventory_svc):
        source = bom_repo.create_bom_source(_make_source())
        bom_repo.add_raw_items_bulk([
            RawBomItem(id=None, bom_source_id=source.id, line_number=1,
                       raw_description="100K", raw_qty="5"),
            RawBomItem(id=None, bom_source_id=source.id, line_number=2,
                       raw_description="TL072", raw_qty="3"),
        ])
        raw_items = bom_repo.list_raw_items(source.id)

        # One matched, one unmatched
        part = inventory_svc.upsert_part(name="100K Resistor", category="Resistors", qty=2)
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw_items[0].id,
                component_type="resistor", normalized_value="100K", qty=5,
                part_id=part.id, match_status="manually_matched", is_verified=True,
            ),
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw_items[1].id,
                component_type="ic", normalized_value="TL072", qty=3,
            ),
        ])

        shopping = bom_repo.get_shopping_list([source.id])
        assert len(shopping) == 2

        resistor = next(s for s in shopping if s["normalized_value"] == "100K")
        assert resistor["qty_needed"] == 5
        assert resistor["qty_available"] == 2
        assert resistor["qty_to_buy"] == 3

        ic = next(s for s in shopping if s["normalized_value"] == "TL072")
        assert ic["qty_needed"] == 3
        assert ic["qty_available"] == 0
        assert ic["qty_to_buy"] == 3

    def test_skipped_items_excluded(self, bom_repo):
        source = bom_repo.create_bom_source(_make_source())
        bom_repo.add_raw_items_bulk([
            RawBomItem(id=None, bom_source_id=source.id, line_number=1,
                       raw_description="Optional part", raw_qty="1"),
        ])
        raw = bom_repo.list_raw_items(source.id)[0]
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=source.id, raw_item_id=raw.id,
                component_type="other", normalized_value="Optional", qty=1,
                match_status="skipped", is_verified=True,
            ),
        ])
        shopping = bom_repo.get_shopping_list([source.id])
        assert len(shopping) == 0

    def test_aggregation_across_boms(self, bom_repo, inventory_svc):
        """Same part across two BOMs aggregates qty_needed."""
        part = inventory_svc.upsert_part(name="100K Resistor", category="Resistors", qty=10)

        s1 = bom_repo.create_bom_source(_make_source(module_name="Sloth", file_hash="h1"))
        bom_repo.add_raw_items_bulk([
            RawBomItem(id=None, bom_source_id=s1.id, line_number=1,
                       raw_description="100K", raw_qty="5"),
        ])
        raw1 = bom_repo.list_raw_items(s1.id)[0]
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=s1.id, raw_item_id=raw1.id,
                component_type="resistor", normalized_value="100K", qty=5,
                part_id=part.id, match_status="manually_matched", is_verified=True,
            ),
        ])

        s2 = bom_repo.create_bom_source(_make_source(module_name="Neuron", file_hash="h2"))
        bom_repo.add_raw_items_bulk([
            RawBomItem(id=None, bom_source_id=s2.id, line_number=1,
                       raw_description="100K", raw_qty="8"),
        ])
        raw2 = bom_repo.list_raw_items(s2.id)[0]
        bom_repo.add_normalized_items_bulk([
            NormalizedBomItem(
                id=None, bom_source_id=s2.id, raw_item_id=raw2.id,
                component_type="resistor", normalized_value="100K", qty=8,
                part_id=part.id, match_status="manually_matched", is_verified=True,
            ),
        ])

        shopping = bom_repo.get_shopping_list([s1.id, s2.id])
        assert len(shopping) == 1
        assert shopping[0]["qty_needed"] == 13
        assert shopping[0]["qty_available"] == 10
        assert shopping[0]["qty_to_buy"] == 3
        assert set(shopping[0]["bom_source_names"]) == {"Sloth", "Neuron"}

    def test_empty_source_ids(self, bom_repo):
        assert bom_repo.get_shopping_list([]) == []
