from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field

from eurorack_inventory.domain.enums import (
    CellLength,
    CellSize,
    ContainerType,
    SlotType,
    StorageClass,
)
from eurorack_inventory.domain.models import Part, StorageSlot, utc_now_iso
from eurorack_inventory.repositories.audit import AuditRepository
from eurorack_inventory.repositories.parts import PartRepository
from eurorack_inventory.repositories.storage import StorageRepository
from eurorack_inventory.services.classifier import classify_part
from eurorack_inventory.services.settings import ClassifierSettings, SettingsRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AssignmentScope:
    all_parts: bool = True
    part_ids: list[int] | None = None
    categories: list[str] | None = None


@dataclass(slots=True)
class StorageEstimate:
    small_short_cells_needed: int = 0
    large_cells_needed: int = 0
    long_cells_needed: int = 0
    binder_cards_needed: int = 0


@dataclass(frozen=True)
class AssignmentPlan:
    assignments: tuple[tuple[int, int], ...]  # (part_id, slot_id)
    unassigned_part_ids: tuple[int, ...]
    estimate: StorageEstimate


@dataclass(slots=True)
class AssignmentResult:
    assigned_count: int = 0
    assignments: list[tuple[int, int]] = field(default_factory=list)
    unassigned_count: int = 0
    estimate: StorageEstimate = field(default_factory=StorageEstimate)


def _slot_to_storage_class(slot: StorageSlot) -> StorageClass | None:
    """Map a storage slot to its StorageClass based on type and metadata."""
    if slot.slot_type == SlotType.CARD.value:
        return StorageClass.BINDER_CARD

    if slot.slot_type == SlotType.GRID_REGION.value:
        cell_size = slot.metadata.get("cell_size", CellSize.SMALL.value)
        cell_length = slot.metadata.get("cell_length", CellLength.SHORT.value)

        if cell_size == CellSize.LARGE.value:
            return StorageClass.LARGE_CELL
        if cell_length == CellLength.LONG.value:
            return StorageClass.LONG_CELL
        return StorageClass.SMALL_SHORT_CELL

    return None


class AssignmentService:
    def __init__(
        self,
        part_repo: PartRepository,
        storage_repo: StorageRepository,
        audit_repo: AuditRepository,
        settings_repo: SettingsRepository | None = None,
    ) -> None:
        self.part_repo = part_repo
        self.storage_repo = storage_repo
        self.audit_repo = audit_repo
        self.settings_repo = settings_repo

    # ------------------------------------------------------------------
    # Pure planner — read-only, no side effects
    # ------------------------------------------------------------------

    def plan(
        self,
        mode: str,
        scope: AssignmentScope,
    ) -> AssignmentPlan:
        """Compute an assignment plan without modifying the database."""
        unassigned_slot_id = self._get_unassigned_slot_id()

        cls_settings: ClassifierSettings | None = None
        if self.settings_repo is not None:
            cls_settings = self.settings_repo.get_classifier_settings()

        # 1. Gather parts (read-only — no resets)
        parts = self._gather_parts_for_plan(mode, scope, unassigned_slot_id)
        if not parts:
            return AssignmentPlan(
                assignments=(),
                unassigned_part_ids=(),
                estimate=StorageEstimate(),
            )

        # 2. Classify
        classified: dict[StorageClass, list[Part]] = defaultdict(list)
        for part in parts:
            sc = classify_part(part, cls_settings)
            classified[sc].append(part)

        # 3. Sort within each class
        for sc in classified:
            classified[sc].sort(key=lambda p: (p.category or "", p.name or ""))

        # 4. Map available slots
        # For scoped full_rebuild, slots occupied by in-scope parts are reusable
        in_scope_slot_ids: set[int] = set()
        if mode == "full_rebuild":
            for part in parts:
                if part.slot_id is not None and part.slot_id != unassigned_slot_id:
                    in_scope_slot_ids.add(part.slot_id)
        available = self._gather_available_slots(unassigned_slot_id, in_scope_slot_ids)

        # 5. Pack
        assignments: list[tuple[int, int]] = []
        unassigned_parts: list[Part] = []

        for sc in StorageClass:
            sc_parts = classified.get(sc, [])
            sc_slots = available.get(sc, [])
            assigned_here, leftover = self._pack(sc_parts, sc_slots)
            assignments.extend(assigned_here)
            unassigned_parts.extend(leftover)

        # 6. Estimate for unassigned
        estimate = self._estimate(unassigned_parts, cls_settings)

        return AssignmentPlan(
            assignments=tuple(assignments),
            unassigned_part_ids=tuple(p.id for p in unassigned_parts),
            estimate=estimate,
        )

    # ------------------------------------------------------------------
    # Transactional application
    # ------------------------------------------------------------------

    def apply_plan(
        self,
        plan: AssignmentPlan,
        mode: str,
        scope: AssignmentScope,
    ) -> int:
        """Apply a plan transactionally. Returns the assignment run ID."""
        db = self.part_repo.db

        # Build snapshot of current slot_ids for all parts in the plan
        all_part_ids = [pid for pid, _ in plan.assignments] + list(plan.unassigned_part_ids)
        snapshot: list[list[int | None]] = []
        for pid in all_part_ids:
            p = self.part_repo.get_part_by_id(pid)
            if p is not None:
                snapshot.append([p.id, p.slot_id])

        unassigned_slot_id = self._get_unassigned_slot_id()

        # For full_rebuild: clear existing slot_ids first
        if mode == "full_rebuild":
            clear_ids = [pid for pid in all_part_ids if pid is not None]
            if clear_ids:
                self.part_repo.bulk_clear_slot_ids(clear_ids)

        # Apply assignments
        if plan.assignments:
            self.part_repo.bulk_update_slot_ids(list(plan.assignments))

        # Persist the run
        now = utc_now_iso()
        scope_dict = {
            "all_parts": scope.all_parts,
            "part_ids": scope.part_ids,
            "categories": scope.categories,
        }
        cursor = db.execute(
            """
            INSERT INTO assignment_runs
                (created_at, mode, scope_json, plan_json, snapshot_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                now,
                mode,
                json.dumps(scope_dict, ensure_ascii=False),
                json.dumps(
                    [[pid, sid] for pid, sid in plan.assignments],
                    ensure_ascii=False,
                ),
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )
        run_id = int(cursor.lastrowid)
        db.conn.commit()

        # Audit (outside transaction — non-critical)
        self.audit_repo.add_event(
            event_type="assignment.completed",
            entity_type="assignment_run",
            entity_id=run_id,
            message=(
                f"Assignment run ({mode}): {len(plan.assignments)} assigned, "
                f"{len(plan.unassigned_part_ids)} unassigned"
            ),
            payload={
                "run_id": run_id,
                "mode": mode,
                "assigned_count": len(plan.assignments),
                "unassigned_count": len(plan.unassigned_part_ids),
                "estimate": {
                    "small_short_cells": plan.estimate.small_short_cells_needed,
                    "large_cells": plan.estimate.large_cells_needed,
                    "long_cells": plan.estimate.long_cells_needed,
                    "binder_cards": plan.estimate.binder_cards_needed,
                },
            },
        )

        return run_id

    # ------------------------------------------------------------------
    # Undo
    # ------------------------------------------------------------------

    def undo_run(self, run_id: int) -> tuple[int, list[str]]:
        """Undo an assignment run by restoring the snapshot.

        Returns (restored_count, conflict_warnings).
        Conflicts occur when a part's current slot_id differs from what the
        plan assigned (i.e. the user moved it manually since the run).
        """
        db = self.part_repo.db
        row = db.query_one(
            "SELECT * FROM assignment_runs WHERE id = ? AND undone_at IS NULL",
            (run_id,),
        )
        if row is None:
            return 0, []

        snapshot: list[list[int | None]] = json.loads(row["snapshot_json"])
        plan_assignments: list[list[int | None]] = json.loads(row["plan_json"])

        # Build plan map: part_id → slot_id that the plan assigned
        plan_map: dict[int, int] = {pid: sid for pid, sid in plan_assignments}

        restore_ops: list[tuple[int, int | None]] = []
        conflicts: list[str] = []

        for part_id, original_slot_id in snapshot:
            if part_id is None:
                continue
            current = self.part_repo.get_part_by_id(part_id)
            if current is None:
                continue

            planned_slot = plan_map.get(part_id)
            if planned_slot is not None and current.slot_id != planned_slot:
                conflicts.append(
                    f"Part '{current.name}' (id={part_id}): expected slot {planned_slot}, "
                    f"found slot {current.slot_id} (moved since assignment)"
                )
                continue

            restore_ops.append((part_id, original_slot_id))

        now = utc_now_iso()
        for part_id, original_slot_id in restore_ops:
            db.execute(
                "UPDATE parts SET slot_id = ?, updated_at = ? WHERE id = ?",
                (original_slot_id, now, part_id),
            )
        db.execute(
            "UPDATE assignment_runs SET undone_at = ? WHERE id = ?",
            (now, run_id),
        )
        db.conn.commit()

        self.audit_repo.add_event(
            event_type="assignment.undone",
            entity_type="assignment_run",
            entity_id=run_id,
            message=(
                f"Assignment run {run_id} undone: {len(restore_ops)} restored, "
                f"{len(conflicts)} conflicts"
            ),
        )

        return len(restore_ops), conflicts

    def get_latest_run(self) -> dict | None:
        """Return the latest non-undone assignment run, or None."""
        row = self.part_repo.db.query_one(
            "SELECT * FROM assignment_runs WHERE undone_at IS NULL "
            "ORDER BY id DESC LIMIT 1"
        )
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Convenience: plan + apply in one call (backwards compatible)
    # ------------------------------------------------------------------

    def assign(
        self,
        mode: str,
        scope: AssignmentScope,
    ) -> AssignmentResult:
        """Assign parts to storage slots (plan + apply)."""
        assignment_plan = self.plan(mode, scope)

        if not assignment_plan.assignments and not assignment_plan.unassigned_part_ids:
            return AssignmentResult()

        self.apply_plan(assignment_plan, mode, scope)

        return AssignmentResult(
            assigned_count=len(assignment_plan.assignments),
            assignments=list(assignment_plan.assignments),
            unassigned_count=len(assignment_plan.unassigned_part_ids),
            estimate=assignment_plan.estimate,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_unassigned_slot_id(self) -> int | None:
        """Get the Unassigned/Main slot ID."""
        container = self.storage_repo.get_container_by_name("Unassigned")
        if container is None:
            return None
        slot = self.storage_repo.get_slot_by_label(container.id, "Main")
        return slot.id if slot else None

    def _gather_parts_for_plan(
        self,
        mode: str,
        scope: AssignmentScope,
        unassigned_slot_id: int | None,
    ) -> list[Part]:
        """Get the list of parts for planning (read-only, no DB writes)."""
        all_parts = self.part_repo.list_parts()

        # Apply scope filter
        if not scope.all_parts:
            if scope.part_ids is not None:
                id_set = set(scope.part_ids)
                all_parts = [p for p in all_parts if p.id in id_set]
            elif scope.categories is not None:
                cat_set = {c.lower() for c in scope.categories}
                all_parts = [
                    p for p in all_parts
                    if (p.category or "").lower() in cat_set
                ]
            else:
                # all_parts=False but no filter specified → no parts
                all_parts = []

        if mode == "full_rebuild":
            # Return all matching parts — actual reset happens in apply_plan()
            return all_parts

        # Incremental: only unassigned parts
        return [
            p for p in all_parts
            if p.slot_id is None or p.slot_id == unassigned_slot_id
        ]

    def _gather_available_slots(
        self,
        unassigned_slot_id: int | None,
        reusable_slot_ids: set[int] | None = None,
    ) -> dict[StorageClass, list[StorageSlot]]:
        """Build a mapping of StorageClass to available (empty) slots.

        For scoped full_rebuild, *reusable_slot_ids* contains slot IDs currently
        occupied by in-scope parts.  These slots are treated as available because
        apply_plan() will clear them before reassignment.
        """
        occupied = self.part_repo.list_occupied_slot_ids()
        if reusable_slot_ids:
            occupied = occupied - reusable_slot_ids
        containers = self.storage_repo.list_containers()

        result: dict[StorageClass, list[StorageSlot]] = defaultdict(list)

        for container in containers:
            if container.name == "Unassigned":
                continue

            slots = self.storage_repo.list_slots_for_container(container.id)
            for slot in slots:
                if slot.id in occupied:
                    continue
                sc = _slot_to_storage_class(slot)
                if sc is not None:
                    result[sc].append(slot)

        return result

    def _pack(
        self,
        parts: list[Part],
        slots: list[StorageSlot],
    ) -> tuple[list[tuple[int, int]], list[Part]]:
        """Assign parts to slots using category-affinity first-fit."""
        if not parts:
            return [], []
        if not slots:
            return [], list(parts)

        container_slots: dict[int, list[StorageSlot]] = defaultdict(list)
        for slot in slots:
            container_slots[slot.container_id].append(slot)

        used_slot_ids: set[int] = set()
        assignments: list[tuple[int, int]] = []
        unassigned: list[Part] = []

        slot_iterators: dict[int, int] = {cid: 0 for cid in container_slots}

        def _take_slot_from_container(container_id: int) -> StorageSlot | None:
            cslots = container_slots[container_id]
            idx = slot_iterators[container_id]
            while idx < len(cslots):
                s = cslots[idx]
                idx += 1
                slot_iterators[container_id] = idx
                if s.id not in used_slot_ids:
                    used_slot_ids.add(s.id)
                    return s
            slot_iterators[container_id] = idx
            return None

        category_affinity: dict[str, int] = {}

        for part in parts:
            cat = (part.category or "").lower()
            placed = False

            if cat in category_affinity:
                preferred_cid = category_affinity[cat]
                slot = _take_slot_from_container(preferred_cid)
                if slot is not None:
                    assignments.append((part.id, slot.id))
                    placed = True

            if not placed:
                for cid in container_slots:
                    if cid in category_affinity.values() and cid != category_affinity.get(cat):
                        pass
                    slot = _take_slot_from_container(cid)
                    if slot is not None:
                        assignments.append((part.id, slot.id))
                        category_affinity[cat] = cid
                        placed = True
                        break

            if not placed:
                unassigned.append(part)

        return assignments, unassigned

    def _estimate(
        self,
        unassigned_parts: list[Part],
        cls_settings: ClassifierSettings | None = None,
    ) -> StorageEstimate:
        """Estimate additional storage needed for unassigned parts."""
        counts: dict[StorageClass, int] = defaultdict(int)
        for part in unassigned_parts:
            sc = classify_part(part, cls_settings)
            counts[sc] += 1

        return StorageEstimate(
            small_short_cells_needed=counts.get(StorageClass.SMALL_SHORT_CELL, 0),
            large_cells_needed=counts.get(StorageClass.LARGE_CELL, 0),
            long_cells_needed=counts.get(StorageClass.LONG_CELL, 0),
            binder_cards_needed=counts.get(StorageClass.BINDER_CARD, 0),
        )
