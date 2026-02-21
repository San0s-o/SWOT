from __future__ import annotations

from typing import Callable, List

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QStandardItemModel
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.domain.models import AccountData
from app.domain.team_store import Team
from app.i18n import tr


class TeamEditorDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        account: AccountData,
        unit_label_fn: Callable[[int], str],
        unit_icon_fn: Callable[[int], QIcon],
        team: Team | None = None,
        unit_combo_model: QStandardItemModel | None = None,
    ):
        super().__init__(parent)
        self.account = account
        self.unit_label_fn = unit_label_fn
        self.unit_icon_fn = unit_icon_fn
        self.team = team
        self._unit_combo_model = unit_combo_model

        title = tr("btn.edit_team") if team else tr("btn.new_team")
        self.setWindowTitle(title)
        self.resize(600, 420)

        layout = QVBoxLayout(self)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(tr("label.team_name")))
        self.name_edit = QLineEdit(team.name if team else "")
        name_row.addWidget(self.name_edit, 1)
        layout.addLayout(name_row)

        control_row = QHBoxLayout()
        self.unit_combo = QComboBox()
        self.unit_combo.setIconSize(QSize(32, 32))
        control_row.addWidget(self.unit_combo, 1)
        self.btn_add_unit = QPushButton(tr("btn.add"))
        self.btn_add_unit.clicked.connect(self._add_unit_from_combo)
        control_row.addWidget(self.btn_add_unit)
        self.btn_remove_unit = QPushButton(tr("btn.remove"))
        self.btn_remove_unit.clicked.connect(self._remove_selected_unit)
        control_row.addWidget(self.btn_remove_unit)
        layout.addLayout(control_row)

        self.unit_list = QListWidget()
        self.unit_list.setIconSize(QSize(32, 32))
        layout.addWidget(self.unit_list, 1)

        self._populate_unit_combo()
        if self.team:
            for uid in self.team.unit_ids:
                self._append_unit(uid)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _populate_unit_combo(self) -> None:
        if self._unit_combo_model is not None:
            self.unit_combo.blockSignals(True)
            self.unit_combo.setModel(self._unit_combo_model)
            self.unit_combo.setModelColumn(0)
            self.unit_combo.setCurrentIndex(0)
            self.unit_combo.blockSignals(False)
            return
        self.unit_combo.clear()
        self.unit_combo.addItem("—", 0)
        if not self.account:
            return
        for uid in sorted(self.account.units_by_id.keys()):
            self.unit_combo.addItem(self.unit_icon_fn(uid), self.unit_label_fn(uid), uid)

    def _append_unit(self, uid: int) -> None:
        if uid == 0:
            return
        for idx in range(self.unit_list.count()):
            if int(self.unit_list.item(idx).data(Qt.UserRole) or 0) == uid:
                return
        label = self.unit_label_fn(uid)
        item = QListWidgetItem(label)
        item.setData(Qt.UserRole, uid)
        item.setIcon(self.unit_icon_fn(uid))
        self.unit_list.addItem(item)

    def _add_unit_from_combo(self) -> None:
        uid = int(self.unit_combo.currentData() or 0)
        if uid:
            self._append_unit(uid)

    def _remove_selected_unit(self) -> None:
        for item in list(self.unit_list.selectedItems()):
            self.unit_list.takeItem(self.unit_list.row(item))

    def _on_accept(self) -> None:
        if self.unit_list.count() == 0:
            QMessageBox.warning(self, tr("dlg.team_needs_units_title"), tr("dlg.team_needs_units"))
            return
        self.accept()

    @property
    def team_name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def unit_ids(self) -> List[int]:
        return [int(self.unit_list.item(idx).data(Qt.UserRole) or 0) for idx in range(self.unit_list.count())]
