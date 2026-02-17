from __future__ import annotations

from typing import List, Set

from PySide6.QtCore import Qt, QEvent, QModelIndex, QSortFilterProxyModel, QRegularExpression, QTimer, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QWidget, QComboBox, QCompleter

from app.domain.presets import SET_NAMES, SET_SIZES
from app.i18n import tr


class _NoScrollComboBox(QComboBox):
    """ComboBox that ignores mouse-wheel events to prevent accidental changes."""

    def wheelEvent(self, event):
        event.ignore()


class _UnitSearchComboBox(_NoScrollComboBox):
    """Unit combo with in-popup text filtering."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._suspend_filter: bool = False
        self._proxy_model = QSortFilterProxyModel(self)
        self._proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self._proxy_model.setFilterKeyColumn(0)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self._completer = QCompleter(self._proxy_model, self)
        self._completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchContains)
        self._completer.setCompletionMode(QCompleter.PopupCompletion)
        self._completer.activated.connect(self._on_completer_activated)
        self._completer.popup().pressed.connect(self._on_completer_popup_clicked)
        self._completer.popup().clicked.connect(self._on_completer_popup_clicked)
        self.setCompleter(self._completer)
        line_edit = self.lineEdit()
        if line_edit is not None:
            line_edit.setClearButtonEnabled(False)
            line_edit.setPlaceholderText(tr("main.search_placeholder"))
            line_edit.textChanged.connect(self._on_filter_text_edited)
        self.activated.connect(self._on_item_activated)

    def set_filter_suspended(self, suspended: bool) -> None:
        self._suspend_filter = bool(suspended)

    def set_source_model(self, model: QStandardItemModel) -> None:
        self._proxy_model.setSourceModel(model)
        self.setModel(model)
        self._completer.setModel(self._proxy_model)

    def showPopup(self) -> None:
        super().showPopup()
        QTimer.singleShot(0, self._focus_search_field)

    def hidePopup(self) -> None:
        super().hidePopup()
        self._clear_filter()
        self._sync_line_edit_to_current()

    def _on_filter_text_edited(self, text: str) -> None:
        if self._suspend_filter:
            return
        line_edit = self.lineEdit()
        # Ignore programmatic text updates while loading many combos.
        # This prevents completer popups from appearing during bulk assignments.
        if line_edit is None or not line_edit.hasFocus():
            return
        query = (text or "").strip()
        if not query:
            self._proxy_model.setFilterRegularExpression(QRegularExpression())
            self._completer.popup().hide()
            return
        escaped = QRegularExpression.escape(query)
        self._proxy_model.setFilterRegularExpression(
            QRegularExpression(f".*{escaped}.*", QRegularExpression.CaseInsensitiveOption)
        )
        self._completer.complete()

    def _clear_filter(self) -> None:
        self._proxy_model.setFilterRegularExpression(QRegularExpression())
        self._completer.popup().hide()

    def _focus_search_field(self) -> None:
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        line_edit.setFocus(Qt.PopupFocusReason)
        line_edit.selectAll()

    def _sync_line_edit_to_current(self) -> None:
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        current_text = self.currentText()
        line_edit.blockSignals(True)
        line_edit.setText(current_text)
        line_edit.blockSignals(False)

    def _reset_search_field(self, *_args) -> None:
        if self._suspend_filter:
            return
        line_edit = self.lineEdit()
        if line_edit is None:
            return
        line_edit.blockSignals(True)
        line_edit.clear()
        line_edit.blockSignals(False)
        self._clear_filter()

    def _on_item_activated(self, _index: int) -> None:
        self._clear_filter()
        self._sync_line_edit_to_current()

    def _on_completer_activated(self, _text: str) -> None:
        idx = self._completer.currentIndex()
        if not idx.isValid():
            return
        self._apply_completion_index(idx)

    def _on_completer_popup_clicked(self, index: QModelIndex) -> None:
        if not index.isValid():
            return
        self._apply_completion_index(index)

    def _apply_completion_index(self, completion_index: QModelIndex) -> None:
        # Prefer stable UID lookup because completer indices are not guaranteed to be
        # direct indices of our filter proxy model.
        uid = int(completion_index.data(Qt.UserRole) or 0)
        if uid > 0:
            row = self.findData(uid, role=Qt.UserRole)
            if row >= 0:
                self.setCurrentIndex(row)
                self._clear_filter()
                self._sync_line_edit_to_current()
                return

        src_idx = self._proxy_model.mapToSource(completion_index)
        if src_idx.isValid():
            self.setCurrentIndex(src_idx.row())
            self._clear_filter()
            self._sync_line_edit_to_current()
            return

        text = str(completion_index.data(Qt.DisplayRole) or "").strip()
        if text:
            row = self.findText(text, flags=Qt.MatchFixedString)
            if row >= 0:
                self.setCurrentIndex(row)
                self._clear_filter()
                self._sync_line_edit_to_current()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        line_edit = self.lineEdit()
        if line_edit is not None:
            key = event.key()
            if key == Qt.Key_Backspace:
                line_edit.backspace()
                event.accept()
                return
            if key == Qt.Key_Delete:
                line_edit.del_()
                event.accept()
                return
            text = event.text()
            if text and not (event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
                line_edit.insert(text)
                event.accept()
                return
        super().keyPressEvent(event)


class _SetMultiCombo(_NoScrollComboBox):
    """Checkable multi-select combo for rune sets with optional size enforcement."""

    selection_changed = Signal()

    ROLE_SET_ID = Qt.UserRole
    ROLE_SET_SIZE = Qt.UserRole + 1
    EXCLUDED_SET_IDS = {25}  # Intangible is handled automatically by the optimizer.

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._block_hide_once = False
        self._enforced_size: int | None = None
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        le = self.lineEdit()
        if le is not None:
            le.setReadOnly(True)
            le.setPlaceholderText("-")
            le.installEventFilter(self)
        model = QStandardItemModel(self)
        self.setModel(model)
        for sid in sorted(SET_NAMES.keys()):
            if int(sid) in self.EXCLUDED_SET_IDS:
                continue
            name = str(SET_NAMES[sid])
            ssize = int(SET_SIZES.get(int(sid), 2))
            item = QStandardItem(f"{name} ({sid})")
            item.setData(int(sid), self.ROLE_SET_ID)
            item.setData(int(ssize), self.ROLE_SET_SIZE)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setData(Qt.Unchecked, Qt.CheckStateRole)
            model.appendRow(item)
        self.view().pressed.connect(self._on_item_pressed)
        self.currentIndexChanged.connect(lambda _: self._refresh_text())
        self._apply_size_constraints()
        self._refresh_text()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            if isinstance(event, QMouseEvent) and event.button() == Qt.LeftButton:
                self.showPopup()
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_item_pressed(self, index) -> None:
        if not index.isValid():
            return
        item = self.model().item(index.row())
        if item is None or not item.isEnabled():
            return
        new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
        item.setCheckState(new_state)
        self._block_hide_once = True
        self._apply_size_constraints()
        self._refresh_text()
        self.selection_changed.emit()

    def hidePopup(self) -> None:
        if self._block_hide_once:
            self._block_hide_once = False
            return
        super().hidePopup()
        self._refresh_text()

    def checked_ids(self) -> List[int]:
        out: List[int] = []
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            if item.checkState() == Qt.Checked:
                out.append(int(item.data(self.ROLE_SET_ID) or 0))
        return [x for x in out if x > 0]

    def checked_sizes(self) -> Set[int]:
        out: Set[int] = set()
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            if item.checkState() == Qt.Checked:
                out.add(int(item.data(self.ROLE_SET_SIZE) or 0))
        return out

    def selected_size(self) -> int | None:
        sizes = self.checked_sizes()
        if len(sizes) == 1:
            return int(next(iter(sizes)))
        return None

    def set_enforced_size(self, size: int | None) -> None:
        self._enforced_size = int(size) if size in (2, 4) else None
        self._apply_size_constraints()
        self._refresh_text()

    def clear_checked(self) -> None:
        self.set_checked_ids([])

    def set_checked_ids(self, set_ids: List[int]) -> None:
        selected = [int(x) for x in (set_ids or []) if int(x) > 0]
        selected_set = set(selected)
        size_by_id = {int(sid): int(SET_SIZES.get(int(sid), 2)) for sid in selected}
        target_size = self._enforced_size
        if target_size is None and selected:
            first_id = int(selected[0])
            target_size = int(size_by_id.get(first_id, 0) or 0) or None

        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            sid = int(item.data(self.ROLE_SET_ID) or 0)
            ssize = int(item.data(self.ROLE_SET_SIZE) or 0)
            should_check = sid in selected_set and (target_size is None or ssize == int(target_size))
            item.setCheckState(Qt.Checked if should_check else Qt.Unchecked)
        self._apply_size_constraints()
        self._refresh_text()

    def _effective_size(self) -> int | None:
        if self._enforced_size in (2, 4):
            return int(self._enforced_size)
        sizes = self.checked_sizes()
        if len(sizes) == 1:
            return int(next(iter(sizes)))
        return None

    def _apply_size_constraints(self) -> None:
        eff_size = self._effective_size()
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            ssize = int(item.data(self.ROLE_SET_SIZE) or 0)
            allowed = eff_size is None or ssize == int(eff_size)
            item.setEnabled(bool(allowed))
            if not allowed and item.checkState() == Qt.Checked:
                item.setCheckState(Qt.Unchecked)

    def _refresh_text(self) -> None:
        ids = self.checked_ids()
        if not ids:
            text = "-"
        else:
            names = [str(SET_NAMES.get(int(sid), sid)) for sid in ids]
            text = ", ".join(names)
        le = self.lineEdit()
        if le is not None:
            le.setText(text)


class _MainstatMultiCombo(_NoScrollComboBox):
    """Checkable multi-select combo for allowed mainstats."""

    def __init__(self, options: List[str], parent: QWidget | None = None):
        super().__init__(parent)
        self._block_hide_once = False
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        le = self.lineEdit()
        if le is not None:
            le.setReadOnly(True)
            le.setPlaceholderText("Any")
            le.installEventFilter(self)
        model = QStandardItemModel(self)
        self.setModel(model)
        for key in options:
            item = QStandardItem(str(key))
            item.setData(str(key), Qt.UserRole)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsUserCheckable)
            item.setData(Qt.Unchecked, Qt.CheckStateRole)
            model.appendRow(item)
        self.view().pressed.connect(self._on_item_pressed)
        self.currentIndexChanged.connect(lambda _: self._refresh_text())
        self._refresh_text()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.lineEdit() and event.type() == QEvent.MouseButtonPress:
            if isinstance(event, QMouseEvent) and event.button() == Qt.LeftButton:
                self.showPopup()
                return True
        return super().eventFilter(obj, event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)

    def _on_item_pressed(self, index) -> None:
        if not index.isValid():
            return
        item = self.model().item(index.row())
        if item is None:
            return
        new_state = Qt.Unchecked if item.checkState() == Qt.Checked else Qt.Checked
        item.setCheckState(new_state)
        self._block_hide_once = True
        self._refresh_text()

    def hidePopup(self) -> None:
        if self._block_hide_once:
            self._block_hide_once = False
            return
        super().hidePopup()
        self._refresh_text()

    def checked_values(self) -> List[str]:
        out: List[str] = []
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            if item.checkState() == Qt.Checked:
                out.append(str(item.data(Qt.UserRole) or item.text() or ""))
        return [x for x in out if x]

    def set_checked_values(self, values: List[str]) -> None:
        selected = {str(v) for v in (values or []) if str(v)}
        m = self.model()
        for row in range(m.rowCount()):
            item = m.item(row)
            if item is None:
                continue
            key = str(item.data(Qt.UserRole) or item.text() or "")
            item.setCheckState(Qt.Checked if key in selected else Qt.Unchecked)
        self._refresh_text()

    def _refresh_text(self) -> None:
        vals = self.checked_values()
        text = "Any" if not vals else ", ".join(vals)
        le = self.lineEdit()
        if le is not None:
            le.setText(text)
