from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.domain.artifact_effects import artifact_effect_text, ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID
from app.domain.models import Artifact, Rune
from app.domain.presets import EFFECT_ID_TO_MAINSTAT_KEY, SET_NAMES
from app.engine.efficiency import rune_efficiency
from app.engine.greedy_optimizer import GreedyUnitResult
from app.i18n import tr


def _stat_label_tr(key: str) -> str:
    return tr("stat." + key)


def _artifact_kind_label(type_id: int) -> str:
    if type_id == 1:
        return tr("artifact.attribute")
    if type_id == 2:
        return tr("artifact.type")
    return str(type_id)


def _artifact_effect_text(effect_id: int, value: int | float | str) -> str:
    return artifact_effect_text(effect_id, value, fallback_prefix="Effekt")


class OptimizeResultDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        title: str,
        summary: str,
        results: List[GreedyUnitResult],
        rune_lookup: Dict[int, Rune],
        artifact_lookup: Dict[int, Artifact],
        unit_label_fn: Callable[[int], str],
        unit_icon_fn: Callable[[int], QIcon],
        unit_spd_fn: Callable[[int, List[int], Dict[int, Dict[int, int]], Dict[int, Dict[int, int]]], int],
        unit_stats_fn: Callable[[int, List[int], Dict[int, Dict[int, int]], Dict[int, Dict[int, int]]], Dict[str, int]],
        set_icon_fn: Callable[[int], QIcon],
        unit_base_stats_fn: Callable[[int], Dict[str, int]],
        unit_leader_bonus_fn: Callable[[int, List[int]], Dict[str, int]],
        unit_totem_bonus_fn: Callable[[int], Dict[str, int]],
        unit_spd_buff_bonus_fn: Callable[[int, List[int], Dict[int, Dict[int, int]]], Dict[str, int]],
        unit_team_index: Optional[Dict[int, int]] = None,
        unit_display_order: Optional[Dict[int, int]] = None,
        mode_rune_owner: Optional[Dict[int, int]] = None,
        team_header_by_index: Optional[Dict[int, str]] = None,
        group_size: int = 3,
        baseline_runes_by_unit: Optional[Dict[int, Dict[int, int]]] = None,
        baseline_artifacts_by_unit: Optional[Dict[int, Dict[int, int]]] = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(1680, 900)
        self.setMinimumSize(1560, 860)

        self._results = list(results)
        self._results_by_key: Dict[int, GreedyUnitResult] = {
            int(idx): r for idx, r in enumerate(self._results)
        }
        self._unit_label_fn = unit_label_fn
        self._unit_icon_fn = unit_icon_fn
        self._unit_spd_fn = unit_spd_fn
        self._unit_stats_fn = unit_stats_fn
        self._set_icon_fn = set_icon_fn
        self._unit_base_stats_fn = unit_base_stats_fn
        self._unit_leader_bonus_fn = unit_leader_bonus_fn
        self._unit_totem_bonus_fn = unit_totem_bonus_fn
        self._unit_spd_buff_bonus_fn = unit_spd_buff_bonus_fn
        self._unit_team_index = unit_team_index or {}
        self._unit_display_order = unit_display_order or {}
        self._rune_lookup = rune_lookup
        self._artifact_lookup = artifact_lookup
        self._mode_rune_owner = mode_rune_owner or {}
        self._team_header_by_index = dict(team_header_by_index or {})
        self._group_size = max(1, int(group_size))
        self._baseline_runes_by_unit: Dict[int, Dict[int, int]] = {
            int(uid): {int(slot): int(rid) for slot, rid in dict(by_slot or {}).items()}
            for uid, by_slot in dict(baseline_runes_by_unit or {}).items()
            if int(uid or 0) > 0
        }
        self._baseline_artifacts_by_unit: Dict[int, Dict[int, int]] = {
            int(uid): {int(t): int(aid) for t, aid in dict(by_type or {}).items()}
            for uid, by_type in dict(baseline_artifacts_by_unit or {}).items()
            if int(uid or 0) > 0
        }
        self._has_baseline_compare = bool(self._baseline_runes_by_unit or self._baseline_artifacts_by_unit)
        self._compare_checkbox: QCheckBox | None = None
        self.saved = False
        self._stats_detailed = True
        self._runes_detailed = True
        self._current_uid: Optional[int] = None

        root = QVBoxLayout(self)
        if summary:
            lbl = QLabel(summary)
            lbl.setWordWrap(True)
            root.addWidget(lbl)

        if self._has_baseline_compare:
            compare_row = QHBoxLayout()
            self._compare_checkbox = QCheckBox(tr("result.compare_before_after"))
            self._compare_checkbox.toggled.connect(self._on_compare_toggle)
            compare_row.addWidget(self._compare_checkbox)
            compare_row.addStretch(1)
            root.addLayout(compare_row)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        self.nav_list = QListWidget()
        self.nav_list.setMinimumWidth(280)
        self.nav_list.currentRowChanged.connect(self._on_nav_selected)
        body.addWidget(self.nav_list, 0)

        right = QVBoxLayout()
        body.addLayout(right, 1)

        self.team_icon_bar = QFrame()
        self.team_icon_bar.setFrameShape(QFrame.StyledPanel)
        self.team_icon_layout = QHBoxLayout(self.team_icon_bar)
        self.team_icon_layout.setContentsMargins(8, 8, 8, 8)
        self.team_icon_layout.setSpacing(10)
        right.addWidget(self.team_icon_bar)

        self.detail_container = QWidget()
        self.detail_layout = QHBoxLayout(self.detail_container)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(8)
        right.addWidget(self.detail_container, 1)

        self._populate_nav()

        btn_bar = QHBoxLayout()
        self.btn_save = QPushButton(tr("btn.save"))
        self.btn_save.clicked.connect(self._on_save)
        btn_bar.addWidget(self.btn_save)
        btn_bar.addStretch()
        btn_close = QPushButton(tr("btn.close"))
        btn_close.clicked.connect(self.reject)
        btn_bar.addWidget(btn_close)
        root.addLayout(btn_bar)

    def _populate_nav(self) -> None:
        self.nav_list.clear()
        has_selection = False
        for team_idx, team_results in self._grouped_results():
            header_text = str(self._team_header_by_index.get(int(team_idx), f"Team {team_idx + 1}"))
            header = QListWidgetItem(header_text)
            header.setData(Qt.UserRole, None)
            header.setFlags(Qt.NoItemFlags)
            self.nav_list.addItem(header)
            for result_key, result in team_results:
                label = self._unit_label_fn(result.unit_id)
                state = "OK" if result.ok else tr("label.error")
                item_text = f"{label} [{state}]"
                if not bool(result.ok):
                    msg = str(getattr(result, "message", "") or "").strip()
                    if msg:
                        short = msg if len(msg) <= 72 else (msg[:69] + "...")
                        item_text = f"{item_text} - {short}"
                item = QListWidgetItem(item_text)
                icon = self._unit_icon_fn(result.unit_id)
                if not icon.isNull():
                    item.setIcon(icon)
                item.setData(Qt.UserRole, int(result_key))
                if not bool(result.ok):
                    msg = str(getattr(result, "message", "") or "").strip()
                    if msg:
                        item.setToolTip(msg)
                self.nav_list.addItem(item)
                if not has_selection:
                    self.nav_list.setCurrentItem(item)
                    has_selection = True

        if not has_selection:
            self._render_details(None)

    def _on_nav_selected(self, row: int) -> None:
        if row < 0:
            self._render_details(None)
            return
        item = self.nav_list.item(row)
        if not item:
            self._render_details(None)
            return
        result_key = item.data(Qt.UserRole)
        if result_key is None:
            self._render_details(None)
            return
        self._render_details(int(result_key))

    def _team_results_for_key(self, result_key: int) -> List[Tuple[int, GreedyUnitResult]]:
        for _team_idx, team_results in self._grouped_results():
            for key, _res in team_results:
                if int(key) == int(result_key):
                    return list(team_results)
        return []

    def _render_team_icon_bar(self, selected_result_key: int | None) -> None:
        while self.team_icon_layout.count():
            child = self.team_icon_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if selected_result_key is None:
            return

        team_results = self._team_results_for_key(int(selected_result_key))

        for result_key, result in team_results:
            card = QFrame()
            card.setFrameShape(QFrame.StyledPanel)
            card.setProperty("selected", int(result_key) == int(selected_result_key))
            v = QVBoxLayout(card)
            v.setContentsMargins(6, 6, 6, 6)
            v.setSpacing(4)

            icon_lbl = QLabel()
            icon = self._unit_icon_fn(result.unit_id)
            if not icon.isNull():
                icon_lbl.setPixmap(icon.pixmap(72, 72))
            icon_lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(icon_lbl)

            runes_by_unit = {int(r.unit_id): (r.runes_by_slot or {}) for _, r in team_results}
            artifacts_by_unit = {int(r.unit_id): (r.artifacts_by_type or {}) for _, r in team_results}
            spd = self._unit_spd_fn(
                result.unit_id,
                [int(r.unit_id) for _, r in team_results],
                runes_by_unit,
                artifacts_by_unit,
            )
            spd_lbl = QLabel(str(spd))
            spd_lbl.setAlignment(Qt.AlignCenter)
            v.addWidget(spd_lbl)

            self.team_icon_layout.addWidget(card)

        self.team_icon_layout.addStretch(1)

    def _grouped_results(self) -> List[Tuple[int, List[Tuple[int, GreedyUnitResult]]]]:
        indexed = [(int(idx), r) for idx, r in enumerate(self._results)]
        if not self._unit_team_index:
            out: List[Tuple[int, List[Tuple[int, GreedyUnitResult]]]] = []
            team_count = (len(indexed) + self._group_size - 1) // self._group_size
            for team_idx in range(team_count):
                start = int(team_idx * self._group_size)
                end = int((team_idx + 1) * self._group_size)
                out.append((team_idx, indexed[start:end]))
            return out

        grouped: Dict[int, List[Tuple[int, GreedyUnitResult]]] = {}
        for key, r in indexed:
            t = int(self._unit_team_index.get(int(r.unit_id), 0))
            grouped.setdefault(t, []).append((int(key), r))
        out = []
        for team_idx in sorted(grouped.keys()):
            arr = grouped[team_idx]
            arr.sort(key=lambda pair: (self._unit_display_order.get(int(pair[1].unit_id), 10000), int(pair[0])))
            out.append((team_idx, arr))
        return out

    def _team_unit_ids_for(self, result_key: int) -> List[int]:
        team_results = self._team_results_for_key(int(result_key))
        if team_results:
            return [int(r.unit_id) for _, r in team_results]
        return [int(r.unit_id) for r in self._results]

    def _render_details(self, result_key: int | None) -> None:
        self._render_team_icon_bar(result_key)
        self._current_uid = int(result_key) if result_key is not None else None

        while self.detail_layout.count():
            child = self.detail_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if result_key is None:
            w = QWidget()
            QVBoxLayout(w).addWidget(QLabel(tr("dlg.select_left")))
            self.detail_layout.addWidget(w)
            return

        result = self._results_by_key.get(int(result_key))
        if not result:
            w = QWidget()
            QVBoxLayout(w).addWidget(QLabel(tr("dlg.no_result")))
            self.detail_layout.addWidget(w)
            return

        unit_id = int(result.unit_id)
        team_unit_ids = self._team_unit_ids_for(int(result_key))
        team_results = self._team_results_for_key(int(result_key))
        runes_by_unit = {int(r.unit_id): (r.runes_by_slot or {}) for _, r in team_results} if team_results else {
            int(r.unit_id): (r.runes_by_slot or {}) for r in self._results
        }
        artifacts_by_unit = {int(r.unit_id): (r.artifacts_by_type or {}) for _, r in team_results} if team_results else {
            int(r.unit_id): (r.artifacts_by_type or {}) for r in self._results
        }
        total_stats = self._unit_stats_fn(unit_id, team_unit_ids, runes_by_unit, artifacts_by_unit)
        base_stats = self._unit_base_stats_fn(unit_id)
        leader_bonus = self._unit_leader_bonus_fn(unit_id, team_unit_ids)
        totem_bonus = self._unit_totem_bonus_fn(unit_id)
        spd_buff_bonus = self._unit_spd_buff_bonus_fn(unit_id, team_unit_ids, artifacts_by_unit)
        before_stats: Dict[str, int] | None = None
        if self._compare_enabled():
            has_unit_baseline = bool(self._baseline_runes_by_unit.get(int(unit_id), {}))
            has_unit_baseline = has_unit_baseline or bool(self._baseline_artifacts_by_unit.get(int(unit_id), {}))
            if has_unit_baseline:
                before_stats = self._unit_stats_fn(
                    unit_id,
                    team_unit_ids,
                    self._baseline_runes_by_unit,
                    self._baseline_artifacts_by_unit,
                )

        self.detail_layout.addWidget(
            self._build_stats_tab(
                unit_id,
                result,
                base_stats,
                total_stats,
                leader_bonus,
                totem_bonus,
                spd_buff_bonus,
                before_stats=before_stats,
            )
        )

        if result.ok and result.runes_by_slot:
            self.detail_layout.addWidget(self._build_runes_tab(result, unit_id))
        if result.ok and result.artifacts_by_type:
            self.detail_layout.addWidget(self._build_artifacts_tab(result))

    def _build_stats_tab(
        self,
        unit_id: int,
        result: GreedyUnitResult,
        base_stats: Dict[str, int],
        total_stats: Dict[str, int],
        leader_bonus: Dict[str, int],
        totem_bonus: Dict[str, int],
        spd_buff_bonus: Dict[str, int],
        before_stats: Optional[Dict[str, int]] = None,
    ) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)

        label = self._unit_label_fn(unit_id)
        title = QLabel(f"<b>{label}</b>" if result.ok else f"<b>{label} ({tr('label.error')})</b>")
        title.setTextFormat(Qt.RichText)
        v.addWidget(title)

        rune_ids = list((result.runes_by_slot or {}).values())
        eff_values = [rune_efficiency(r) for rid in rune_ids if (r := self._rune_lookup.get(int(rid)))]
        if eff_values:
            avg_eff = sum(eff_values) / len(eff_values)
            eff_lbl = QLabel(tr("result.avg_rune_eff", eff=f"{avg_eff:.2f}"))
        else:
            eff_lbl = QLabel(tr("result.avg_rune_eff_none"))
        eff_lbl.setTextFormat(Qt.RichText)
        eff_lbl.setStyleSheet("color: #bbb;")
        v.addWidget(eff_lbl)

        if not result.ok:
            msg = QLabel(result.message)
            msg.setWordWrap(True)
            v.addWidget(msg)
            v.addStretch()
            return w

        stat_keys = ["HP", "ATK", "DEF", "SPD", "CR", "CD", "RES", "ACC"]
        has_leader = any(leader_bonus.get(k, 0) != 0 for k in stat_keys)
        has_totem = any(totem_bonus.get(k, 0) != 0 for k in stat_keys)
        has_buff = any(spd_buff_bonus.get(k, 0) != 0 for k in stat_keys)
        table = QTableWidget()
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.NoSelection)
        table.verticalHeader().setVisible(False)
        table.setRowCount(len(stat_keys))

        if before_stats is not None:
            table.setColumnCount(4)
            table.setHorizontalHeaderLabels(
                [tr("header.stat"), tr("header.before"), tr("header.after"), tr("header.delta")]
            )
            for i, key in enumerate(stat_keys):
                before_val = int(before_stats.get(key, 0) or 0)
                after_val = int(total_stats.get(key, 0) or 0)
                delta = int(after_val - before_val)
                delta_text = f"+{delta}" if delta > 0 else str(delta)
                table.setItem(i, 0, QTableWidgetItem(_stat_label_tr(key)))
                it_before = QTableWidgetItem(str(before_val))
                it_before.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 1, it_before)
                it_after = QTableWidgetItem(str(after_val))
                it_after.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 2, it_after)
                it_delta = QTableWidgetItem(delta_text)
                it_delta.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if delta > 0:
                    it_delta.setForeground(QColor("#2ecc71"))
                elif delta < 0:
                    it_delta.setForeground(QColor("#e74c3c"))
                else:
                    it_delta.setForeground(QColor("#aaaaaa"))
                table.setItem(i, 3, it_delta)
        elif self._stats_detailed:
            headers = [tr("header.stat"), tr("header.base"), tr("header.runes")]
            if has_totem:
                headers.append(tr("header.totem"))
            if has_leader:
                headers.append(tr("header.leader"))
            if has_buff:
                headers.append("Buff")
            headers.append(tr("header.total"))
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)

            total_col = len(headers) - 1
            buff_col = total_col - 1 if has_buff else -1
            leader_col = total_col - 1 - (1 if has_buff else 0) if has_leader else -1
            totem_col = 3 if has_totem else -1
            runes_col = 2

            for i, key in enumerate(stat_keys):
                base = base_stats.get(key, 0)
                total = total_stats.get(key, 0)
                lead = leader_bonus.get(key, 0)
                totem = totem_bonus.get(key, 0)
                buff = spd_buff_bonus.get(key, 0)
                rune_bonus = total - base - lead - totem - buff
                table.setItem(i, 0, QTableWidgetItem(_stat_label_tr(key)))
                it_b = QTableWidgetItem(str(base))
                it_b.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 1, it_b)
                rune_str = f"+{rune_bonus}" if rune_bonus >= 0 else str(rune_bonus)
                it_r = QTableWidgetItem(rune_str)
                it_r.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, runes_col, it_r)
                if has_totem and totem_col >= 0:
                    totem_str = f"+{totem}" if totem > 0 else str(totem) if totem else ""
                    it_tt = QTableWidgetItem(totem_str)
                    it_tt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(i, totem_col, it_tt)
                if has_leader and leader_col >= 0:
                    lead_str = f"+{lead}" if lead > 0 else str(lead) if lead else ""
                    it_l = QTableWidgetItem(lead_str)
                    it_l.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(i, leader_col, it_l)
                if has_buff and buff_col >= 0:
                    buff_str = f"+{buff}" if buff > 0 else str(buff) if buff else ""
                    if key == "SPD" and int(buff or 0) > 0:
                        eff_x10 = int(spd_buff_bonus.get("SPD_BUFF_EFF_PCT_X10", 0) or 0)
                        if eff_x10 > 0:
                            buff_str = f"{buff_str} ({float(eff_x10) / 10.0:.1f}%)"
                    it_bf = QTableWidgetItem(buff_str)
                    it_bf.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    table.setItem(i, buff_col, it_bf)
                it_t = QTableWidgetItem(str(total))
                it_t.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, total_col, it_t)
        else:
            table.setColumnCount(2)
            table.setHorizontalHeaderLabels([tr("header.stat"), tr("header.value")])
            for i, key in enumerate(stat_keys):
                table.setItem(i, 0, QTableWidgetItem(_stat_label_tr(key)))
                it_v = QTableWidgetItem(str(total_stats.get(key, 0)))
                it_v.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, 1, it_v)

        table.resizeColumnsToContents()
        table.setMaximumHeight(table.verticalHeader().length() + table.horizontalHeader().height() + 4)
        v.addWidget(table)
        v.addStretch()
        return w

    def _build_runes_tab(self, result: GreedyUnitResult, unit_id: int) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)

        grid = QGridLayout()
        grid.setSpacing(6)
        slots = sorted((result.runes_by_slot or {}).items())
        for idx, (slot, rune_id) in enumerate(slots):
            rune = self._rune_lookup.get(rune_id)
            if not rune:
                continue
            row, col = divmod(idx, 2)
            grid.addWidget(self._build_rune_frame(rune, slot), row, col)
        v.addLayout(grid)
        v.addStretch()
        return w

    def _build_artifacts_tab(self, result: GreedyUnitResult) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)
        v.addWidget(QLabel(f"<b>{tr('ui.artifacts_title')}</b>"))

        for art_type in (1, 2):
            aid = int((result.artifacts_by_type or {}).get(art_type, 0) or 0)
            if aid <= 0:
                continue
            art = self._artifact_lookup.get(aid)
            if art is None:
                v.addWidget(QLabel(f"{_artifact_kind_label(art_type)}: {aid}"))
                continue

            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 3px; padding: 4px; }")
            fv = QVBoxLayout(frame)
            fv.setContentsMargins(6, 4, 6, 4)
            fv.setSpacing(2)

            kind = _artifact_kind_label(art_type)
            focus = ""
            if art.pri_effect:
                focus = ARTIFACT_MAIN_FOCUS_BY_EFFECT_ID.get(int(art.pri_effect[0] or 0), "")
            header_text = f"<b>{kind}</b> | {focus} | +{int(art.level or 0)}" if focus else f"<b>{kind}</b> | +{int(art.level or 0)}"
            fv.addWidget(QLabel(header_text))

            owner_uid = int(art.occupied_id or 0)
            if owner_uid > 0:
                owner = self._unit_label_fn(owner_uid)
                owner_lbl = QLabel(tr("ui.current_on", owner=owner))
                owner_lbl.setStyleSheet("color: #888; font-size: 7pt;")
                fv.addWidget(owner_lbl)

            sec_lines: List[str] = []
            for sec in (art.sec_effects or []):
                if not sec:
                    continue
                try:
                    eid = int(sec[0] or 0)
                    val = sec[1] if len(sec) > 1 else 0
                except Exception:
                    continue
                sec_lines.append(f"• {_artifact_effect_text(eid, val)}")
            if sec_lines:
                for line in sec_lines:
                    lbl = QLabel(line)
                    lbl.setStyleSheet("font-size: 8pt;")
                    fv.addWidget(lbl)

            v.addWidget(frame)

        v.addStretch()
        return w

    def _build_rune_frame(self, rune: Rune, slot: int) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet("QFrame { border: 1px solid #444; border-radius: 3px; padding: 2px; }")
        main_v = QVBoxLayout(frame)
        main_v.setSpacing(2)
        main_v.setContentsMargins(6, 4, 6, 4)

        owner_uid = self._mode_rune_owner.get(rune.rune_id)
        if not owner_uid and rune.occupied_type == 1 and rune.occupied_id:
            owner_uid = int(rune.occupied_id)

        header = QHBoxLayout()
        header.setSpacing(4)
        set_icon = self._set_icon_fn(rune.set_id)
        icon_lbl = QLabel()
        if not set_icon.isNull():
            icon_lbl.setPixmap(set_icon.pixmap(28, 28))
        else:
            icon_lbl.setFixedSize(28, 28)
        header.addWidget(icon_lbl)
        set_name = SET_NAMES.get(rune.set_id, f"Set {rune.set_id}")
        header.addWidget(QLabel(f"<b>{tr('ui.slot')} {slot}</b> | {set_name} | +{rune.upgrade_curr}"))
        header.addStretch()
        if owner_uid:
            monster_icon = self._unit_icon_fn(owner_uid)
            if not monster_icon.isNull():
                monster_icon_lbl = QLabel()
                monster_icon_lbl.setPixmap(monster_icon.pixmap(32, 32))
                header.addWidget(monster_icon_lbl)
        main_v.addLayout(header)

        if owner_uid:
            owner = self._unit_label_fn(owner_uid)
            src = QLabel(tr("ui.current_on", owner=owner))
            src.setStyleSheet("color: #888; font-size: 7pt;")
            main_v.addWidget(src)

        main_v.addWidget(QLabel(f"{tr('ui.main')}: {self._stat_label(rune.pri_eff)}"))
        pfx = self._prefix_text(rune.prefix_eff)
        if pfx != "—":
            main_v.addWidget(QLabel(f"{tr('ui.prefix')}: {pfx}"))

        for sec in (rune.sec_eff or []):
            if not sec:
                continue
            eff_id = int(sec[0] or 0)
            value = int(sec[1] or 0)
            gem_flag = int(sec[2] or 0) if len(sec) >= 3 else 0
            grind = int(sec[3] or 0) if len(sec) >= 4 else 0
            key = EFFECT_ID_TO_MAINSTAT_KEY.get(eff_id, f"Effect {eff_id}")
            total = value + grind
            if self._runes_detailed:
                if grind:
                    text = f"{key} {total} <span style='color: #FFD700;'>({value}+{grind})</span>"
                else:
                    text = f"{key} {value}"
            else:
                text = f"{key} {total}"
            if gem_flag:
                text = f"<span style='color:#1abc9c'>{text} [Gem]</span>"
            lbl = QLabel(text)
            lbl.setTextFormat(Qt.RichText)
            lbl.setStyleSheet("font-size: 8pt;")
            main_v.addWidget(lbl)

        return frame

    def _stat_label(self, stat: Tuple[int, int]) -> str:
        eff_id, value = stat
        key = EFFECT_ID_TO_MAINSTAT_KEY.get(int(eff_id or 0), f"Effect {eff_id}")
        return f"{key} {self._fmt(value)}"

    def _prefix_text(self, prefix: Tuple[int, int]) -> str:
        if not prefix or prefix[0] == 0:
            return "—"
        return self._stat_label(prefix)

    def _fmt(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    def _on_save(self):
        self.saved = True
        self.btn_save.setEnabled(False)
        self.btn_save.setText(tr("btn.saved"))

    def _compare_enabled(self) -> bool:
        if not self._has_baseline_compare:
            return False
        if self._compare_checkbox is None:
            return False
        return bool(self._compare_checkbox.isChecked())

    def _on_compare_toggle(self, _checked: bool) -> None:
        if self._current_uid is None:
            return
        self._render_details(int(self._current_uid))
