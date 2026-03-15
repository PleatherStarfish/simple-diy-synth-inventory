from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from PySide6.QtGui import QClipboard, QGuiApplication

from eurorack_inventory.domain.models import BomSource, ShoppingListItem
from eurorack_inventory.services.bom import BomService


class ShoppingListDialog(QDialog):
    """Dialog showing aggregated shopping list across selected BOM sources."""

    HEADERS = ["Component", "Type", "Package", "Need", "Have", "Buy", "Tayda PN", "Mouser PN", "BOMs"]

    def __init__(
        self,
        parent,
        *,
        bom_service: BomService,
        sources: list[BomSource],
    ) -> None:
        super().__init__(parent)
        self.bom_service = bom_service
        self.sources = sources
        self.shopping_items: list[ShoppingListItem] = []

        self.setWindowTitle("Shopping List")
        self.setMinimumSize(900, 500)

        # Source checkboxes
        source_group = QGroupBox("Select BOMs to include")
        source_layout = QVBoxLayout()
        select_btns = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(self._select_all)
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.clicked.connect(self._deselect_all)
        select_btns.addWidget(select_all_btn)
        select_btns.addWidget(deselect_all_btn)
        select_btns.addStretch()
        source_layout.addLayout(select_btns)
        self.source_checks: list[tuple[QCheckBox, int]] = []
        for source in sources:
            cb = QCheckBox(f"{source.module_name} ({source.filename})")
            cb.setChecked(True)
            cb.stateChanged.connect(self._refresh_table)
            source_layout.addWidget(cb)
            self.source_checks.append((cb, source.id))
        source_group.setLayout(source_layout)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # Buttons
        btn_layout = QHBoxLayout()
        export_btn = QPushButton("Export CSV...")
        export_btn.clicked.connect(self._export_csv)
        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.clicked.connect(self._copy_clipboard)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(export_btn)
        btn_layout.addWidget(copy_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(source_group)
        layout.addWidget(self.table)
        layout.addLayout(btn_layout)

        self._refresh_table()

    def _selected_source_ids(self) -> list[int]:
        return [sid for cb, sid in self.source_checks if cb.isChecked()]

    def _select_all(self) -> None:
        for cb, _ in self.source_checks:
            cb.setChecked(True)

    def _deselect_all(self) -> None:
        for cb, _ in self.source_checks:
            cb.setChecked(False)

    def _refresh_table(self) -> None:
        source_ids = self._selected_source_ids()
        if not source_ids:
            self.shopping_items = []
            self.table.setRowCount(0)
            return

        self.shopping_items = [
            item for item in self.bom_service.get_shopping_list(source_ids)
            if item.qty_to_buy > 0
        ]
        self.table.setRowCount(len(self.shopping_items))
        for row_idx, item in enumerate(self.shopping_items):
            self.table.setItem(row_idx, 0, QTableWidgetItem(item.normalized_value))
            self.table.setItem(row_idx, 1, QTableWidgetItem(item.component_type or ""))
            self.table.setItem(row_idx, 2, QTableWidgetItem(item.package_hint or ""))
            self.table.setItem(row_idx, 3, _num_item(item.qty_needed))
            self.table.setItem(row_idx, 4, _num_item(item.qty_available))
            self.table.setItem(row_idx, 5, _num_item(item.qty_to_buy))
            self.table.setItem(row_idx, 6, QTableWidgetItem(item.tayda_pn or ""))
            self.table.setItem(row_idx, 7, QTableWidgetItem(item.mouser_pn or ""))
            self.table.setItem(row_idx, 8, QTableWidgetItem(", ".join(item.bom_source_names)))

    def _to_csv_string(self) -> str:
        buf = StringIO()
        writer = csv.writer(buf)
        writer.writerow(self.HEADERS)
        for item in self.shopping_items:
            writer.writerow([
                item.normalized_value,
                item.component_type or "",
                item.package_hint or "",
                item.qty_needed,
                item.qty_available,
                item.qty_to_buy,
                item.tayda_pn or "",
                item.mouser_pn or "",
                ", ".join(item.bom_source_names),
            ])
        return buf.getvalue()

    def _export_csv(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Shopping List", "shopping_list.csv", "CSV Files (*.csv)"
        )
        if not path:
            return
        Path(path).write_text(self._to_csv_string())
        QMessageBox.information(self, "Export", f"Shopping list saved to:\n{path}")

    def _copy_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        clipboard.setText(self._to_csv_string())
        QMessageBox.information(self, "Copied", "Shopping list copied to clipboard.")


def _num_item(val: int) -> QTableWidgetItem:
    item = QTableWidgetItem(str(val))
    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return item
