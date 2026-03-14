from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from eurorack_inventory.services.assignment import AssignmentScope, AssignmentService


class AssignmentDialog(QDialog):
    def __init__(
        self,
        assignment_service: AssignmentService,
        categories: list[str],
        selected_part_ids: list[int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.assignment_service = assignment_service
        self.selected_part_ids = selected_part_ids or []
        self.setWindowTitle("Auto-Assign Parts to Storage")
        self.setMinimumWidth(420)
        self._build_ui(categories)

    def _build_ui(self, categories: list[str]) -> None:
        layout = QVBoxLayout(self)

        # Mode group
        mode_box = QGroupBox("Mode")
        mode_layout = QVBoxLayout(mode_box)
        self._mode_group = QButtonGroup(self)
        self._radio_incremental = QRadioButton("Incremental (unassigned only)")
        self._radio_rebuild = QRadioButton("Full rebuild (reassign everything)")
        self._radio_incremental.setChecked(True)
        self._mode_group.addButton(self._radio_incremental, 0)
        self._mode_group.addButton(self._radio_rebuild, 1)
        mode_layout.addWidget(self._radio_incremental)
        mode_layout.addWidget(self._radio_rebuild)
        layout.addWidget(mode_box)

        # Scope group
        scope_box = QGroupBox("Scope")
        scope_layout = QVBoxLayout(scope_box)
        self._scope_group = QButtonGroup(self)
        self._radio_all = QRadioButton("All parts")
        self._radio_selected = QRadioButton(
            f"Selected parts ({len(self.selected_part_ids)})"
        )
        self._radio_selected.setEnabled(len(self.selected_part_ids) > 0)
        self._radio_category = QRadioButton("By category:")
        self._radio_all.setChecked(True)
        self._scope_group.addButton(self._radio_all, 0)
        self._scope_group.addButton(self._radio_selected, 1)
        self._scope_group.addButton(self._radio_category, 2)
        scope_layout.addWidget(self._radio_all)
        scope_layout.addWidget(self._radio_selected)

        cat_row = QHBoxLayout()
        cat_row.addWidget(self._radio_category)
        self._category_combo = QComboBox()
        self._category_combo.addItems(categories)
        self._category_combo.setEnabled(False)
        cat_row.addWidget(self._category_combo, 1)
        scope_layout.addLayout(cat_row)
        layout.addWidget(scope_box)

        self._scope_group.idToggled.connect(self._on_scope_changed)

        # Run button
        self._run_btn = QPushButton("Run Assignment")
        self._run_btn.clicked.connect(self._run_assignment)
        layout.addWidget(self._run_btn)

        # Results
        self._results_label = QLabel("Results will appear here after running.")
        self._results_label.setWordWrap(True)
        layout.addWidget(self._results_label)

        self._results_text = QTextEdit()
        self._results_text.setReadOnly(True)
        self._results_text.setMaximumHeight(180)
        self._results_text.hide()
        layout.addWidget(self._results_text)

        # Close button
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignmentFlag.AlignRight)

    def _on_scope_changed(self, button_id: int, checked: bool) -> None:
        if checked:
            self._category_combo.setEnabled(button_id == 2)

    def _run_assignment(self) -> None:
        mode = "full_rebuild" if self._radio_rebuild.isChecked() else "incremental"

        if mode == "full_rebuild":
            reply = QMessageBox.warning(
                self,
                "Confirm Full Rebuild",
                "This will clear ALL existing storage assignments and reassign from scratch.\n\n"
                "Are you sure?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        scope = self._build_scope()
        result = self.assignment_service.assign(mode, scope)

        lines = [
            f"Assigned: {result.assigned_count} parts",
            f"Unassigned: {result.unassigned_count} parts",
            "",
            "Additional storage needed:",
            f"  Small cells: {result.estimate.small_short_cells_needed}",
            f"  Large cells: {result.estimate.large_cells_needed}",
            f"  Long cells: {result.estimate.long_cells_needed}",
            f"  Binder cards: {result.estimate.binder_cards_needed}",
        ]
        self._results_label.setText(
            f"Done: {result.assigned_count} assigned, {result.unassigned_count} unassigned"
        )
        self._results_text.setPlainText("\n".join(lines))
        self._results_text.show()

    def _build_scope(self) -> AssignmentScope:
        scope_id = self._scope_group.checkedId()
        if scope_id == 1:
            return AssignmentScope(
                all_parts=False,
                part_ids=list(self.selected_part_ids),
            )
        if scope_id == 2:
            cat = self._category_combo.currentText()
            return AssignmentScope(
                all_parts=False,
                categories=[cat] if cat else None,
            )
        return AssignmentScope(all_parts=True)
