from __future__ import annotations

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QHBoxLayout,
    QInputDialog,
)
from PySide6.QtCore import Qt

from eurorack_inventory.app import AppContext
from eurorack_inventory.ui.models import ProjectTableModel
from PySide6.QtWidgets import QTableView


class ProjectsScreen(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.current_project_id: int | None = None

        self.project_model = ProjectTableModel([])
        self.project_table = QTableView()
        self.project_table.setModel(self.project_model)
        self.project_table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.project_table.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.project_table.horizontalHeader().setStretchLastSection(True)
        self.project_table.verticalHeader().setVisible(False)
        self.project_table.clicked.connect(self._on_project_clicked)

        self.project_name = QLabel("Select a project")
        self.project_meta = QLabel("")
        self.build_list = QListWidget()
        self.availability_table = QTableWidget()
        self.availability_table.setColumnCount(4)
        self.availability_table.setHorizontalHeaderLabels(["Part ID", "Need", "Have", "Enough"])
        self.notes_text = QTextEdit()
        self.notes_text.setReadOnly(True)
        self.create_build_btn = QPushButton("Start New Build")
        self.create_build_btn.setToolTip("Create a new build instance and check part availability")
        self.create_build_btn.clicked.connect(self._create_build)

        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        left_layout = QVBoxLayout()
        left_layout.addWidget(self.project_table)
        left_widget = QWidget()
        left_widget.setLayout(left_layout)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.project_name)
        right_layout.addWidget(self.project_meta)
        right_layout.addWidget(QLabel("Availability"))
        right_layout.addWidget(self.availability_table)
        right_layout.addWidget(QLabel("Builds"))
        right_layout.addWidget(self.build_list)
        right_layout.addWidget(self.create_build_btn)
        right_layout.addWidget(QLabel("Notes"))
        right_layout.addWidget(self.notes_text)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([450, 650])

        layout = QVBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)

    def refresh(self) -> None:
        rows = self.context.project_service.list_projects()
        self.project_model.update_rows(rows)
        if rows and self.current_project_id is None:
            self.load_project(rows[0].id)

    def _on_project_clicked(self, index) -> None:
        project_id = self.project_model.project_id_at(index.row())
        if project_id is not None:
            self.load_project(project_id)

    def load_project(self, project_id: int) -> None:
        project = self.context.project_repo.get_project(project_id)
        if project is None:
            return
        self.current_project_id = project_id
        self.project_name.setText(project.name)
        self.project_meta.setText(f"{project.maker} | revision {project.revision or 'n/a'}")
        self.notes_text.setPlainText(project.notes or "")
        availability = self.context.project_service.get_project_availability(project_id)
        self.availability_table.setRowCount(len(availability))
        for row_idx, row in enumerate(availability):
            self.availability_table.setItem(row_idx, 0, QTableWidgetItem(str(row["part_id"])))
            self.availability_table.setItem(row_idx, 1, QTableWidgetItem(str(row["qty_required"])))
            self.availability_table.setItem(row_idx, 2, QTableWidgetItem(str(row["qty_available"])))
            self.availability_table.setItem(row_idx, 3, QTableWidgetItem("Yes" if row["enough_stock"] else "No"))
        builds = self.context.project_service.list_builds(project_id)
        self.build_list.clear()
        for build in builds:
            self.build_list.addItem(f"{build.status} | {build.nickname or '(unnamed)'}")

    def _create_build(self) -> None:
        if self.current_project_id is None:
            QMessageBox.information(self, "Select a project", "Select a project first.")
            return
        nickname, ok = QInputDialog.getText(self, "Create build", "Build nickname:")
        if not ok:
            return
        try:
            self.context.project_service.create_build(
                project_id=self.current_project_id,
                nickname=nickname.strip() or None,
            )
            self.load_project(self.current_project_id)
        except Exception as exc:
            QMessageBox.critical(self, "Create build failed", str(exc))
