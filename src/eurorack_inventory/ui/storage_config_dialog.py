from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)


class StorageConfigDialog(QDialog):
    """Dialog for creating a new storage container (grid box or binder)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Container")
        self.setMinimumWidth(400)

        self.type_combo = QComboBox()
        self.type_combo.addItem("Grid Box", "grid_box")
        self.type_combo.addItem("Binder", "binder")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.name_edit = QLineEdit()
        self.notes_label = QLabel("Notes")
        self.notes_edit = QLineEdit()

        # Grid box fields
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 26)
        self.rows_spin.setValue(6)
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 26)
        self.cols_spin.setValue(6)
        self.size_row = QHBoxLayout()
        self.size_row.setContentsMargins(0, 0, 0, 0)
        self.size_row.addWidget(self.rows_spin)
        self.size_row.addWidget(QLabel("x"))
        self.size_row.addWidget(self.cols_spin)
        self.size_widget = QWidget()
        self.size_widget.setLayout(self.size_row)

        grid_form = QFormLayout()
        grid_form.addRow("Size", self.size_widget)
        self.grid_widget = QWidget()
        self.grid_widget.setLayout(grid_form)

        # Binder fields
        self.cards_spin = QSpinBox()
        self.cards_spin.setRange(1, 100)
        self.cards_spin.setValue(10)
        self.bags_spin = QSpinBox()
        self.bags_spin.setRange(1, 20)
        self.bags_spin.setValue(4)

        binder_form = QFormLayout()
        binder_form.addRow("Number of cards", self.cards_spin)
        binder_form.addRow("Bags per card", self.bags_spin)
        self.binder_widget = QWidget()
        self.binder_widget.setLayout(binder_form)

        # Stack for switching between modes
        self.stack = QStackedWidget()
        self.stack.addWidget(self.grid_widget)
        self.stack.addWidget(self.binder_widget)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)

        common_form = QFormLayout()
        common_form.addRow("Type", self.type_combo)
        common_form.addRow("Name *", self.name_edit)
        common_form.addRow(self.notes_label, self.notes_edit)

        layout = QVBoxLayout(self)
        layout.addLayout(common_form)
        layout.addWidget(self.stack)
        layout.addWidget(buttons)
        self._on_type_changed(self.type_combo.currentIndex())

    def _on_type_changed(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Name is required.")
            return
        self.accept()

    def get_fields(self) -> dict:
        container_type = self.type_combo.currentData()
        fields = {
            "container_type": container_type,
            "name": self.name_edit.text().strip(),
            "notes": self.notes_edit.text().strip() or None,
        }
        if container_type == "grid_box":
            fields["rows"] = self.rows_spin.value()
            fields["cols"] = self.cols_spin.value()
        else:
            fields["num_cards"] = self.cards_spin.value()
            fields["bags_per_card"] = self.bags_spin.value()
        return fields
