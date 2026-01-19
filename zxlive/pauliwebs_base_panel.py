from __future__ import annotations

import copy
import os
import subprocess
import sys
from enum import Enum
from typing import Callable, Iterator, Optional, TypedDict

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGridLayout, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QSpacerItem, QSplitter, QToolButton, QVBoxLayout, QWidget)
from pyzx import EdgeType, VertexType
from pyzx.utils import get_w_partner, vertex_is_w, phase_to_s, get_z_box_label
from pyzx.graph.jsonparser import string_to_phase
from zxlive.sfx import SFXEnum

from .base_panel import BasePanel, ToolbarSection
from .commands import ( ChangeEdgeCurve,MoveNode, UpdateGraph)
from .common import VT, GraphT, ToolType, get_data, pos_from_view, get_settings_value
from .dialogs import import_diagram_from_file, show_error_msg, update_dummy_vertex_text
from .eitem import EItem, HAD_EDGE_BLUE
from .vitem import VItem, BLACK
from .graphscene import EditGraphScene
from .settings import display_setting


import json
from pyzx.graph.jsonparser import json_to_graph
from pyzx.web import compute_pauli_webs

class PauliWebsBasePanel(BasePanel):
    """Base class implementing the shared functionality of graph edit
    and rule edit panels of ZXLive."""

    graph_scene: EditGraphScene
    sidebar: QSplitter

    _curr_ety: EdgeType
    _curr_vty: VertexType
    snap_vertex_edge = True
    patterns_folder: Optional[str] = None

    def __init__(self, *actions: QAction) -> None:
        super().__init__(*actions)
        self._curr_vty = VertexType.Z
        self._curr_ety = EdgeType.SIMPLE
        self.patterns_folder = get_settings_value("patterns-folder", str)

    def create_side_bar(self) -> None:
        self.sidebar = QSplitter(self)
        self.sidebar.setOrientation(Qt.Orientation.Vertical)

        vertex_container, vertex_layout = create_titled_widget("sdfhsdf")
        self.sidebar.addWidget(vertex_container)

        edge_container, edge_layout = create_titled_widget("Edges")
        self.sidebar.addWidget(edge_container)


    def vert_moved(self, vs: list[tuple[VT, float, float]]) -> None:
        self.undo_stack.push(MoveNode(self.graph_view, vs))

    def _vertex_dropped_onto(self, v: VT, w: VT) -> None:
        view_pos = self.graph_scene.vertex_map[v].pos()
        pos = pos_from_view(view_pos.x(), view_pos.y())
        self.vert_moved([(v, pos[0], pos[1])])

    def change_edge_curves(self, eitem: EItem, new_distance: float, old_distance: float) -> None:
        self.undo_stack.push(ChangeEdgeCurve(self.graph_view, eitem, new_distance, old_distance))
    
    def _compute_pauli_webs(self) -> None:
        # Kees: Convert to simple graph for Pauli web computation, should change in pyzx that Multigraphs also work
        graph_json = json.loads(self.graph_scene.g.to_json())
        
        try:
            edge_pairs = [tuple(sorted(edge[:2])) for edge in graph_json.get("edges", [])]
            unique_pairs = set(edge_pairs)
            has_duplicate_edges = len(edge_pairs) != len(unique_pairs)

            if has_duplicate_edges:
                raise ValueError("Graph is a multigraph. Pauli web computation requires a simple graph.")
            
        except ValueError as ve:
            show_error_msg(str(ve), parent=self)
            return
        
        simple_g = json_to_graph(graph_json, backend="simple")
    
        try:
            stabs, regions = compute_pauli_webs(simple_g)
        except Exception as err:
            show_error_msg("Failed to compute Pauli webs", str(err), parent=self)
            return

        # Store the webs
        self._pauli_webs = stabs + regions
        
        # Populate the list widget
        self.web_list.clear()

        for i, web in enumerate(self._pauli_webs):
            # Determine if it's a Stabilizer or Region for the label
            label = f"Stabilizer {i+1}" if i < len(stabs) else f"Region {i - len(stabs) + 1}"
            
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, i) # Store the index
            self.web_list.addItem(item)

        if self._pauli_webs:
            self.web_list.setCurrentRow(0)
            self._pauli_web_index = 0
            self._show_current_pauli_web()
    
    def _show_current_pauli_web(self) -> None:
        new_g = copy.deepcopy(self.graph_scene.g)
        for e in new_g.edges():
            new_g.set_edata(e, "xweb0", False)
            new_g.set_edata(e, "zweb0", False)
            new_g.set_edata(e, "xweb1", False)
            new_g.set_edata(e, "zweb1", False)

        if 0 <= self._pauli_web_index < len(self._pauli_webs):
            web = self._pauli_webs[self._pauli_web_index]
            for (s, t), pauli in web.half_edges().items():
                try:
                    edge = new_g.edge(s, t)
                except Exception:
                    continue
                if pauli in ("X", "Y") and s < t:
                    new_g.set_edata(edge, "xweb0", True)
                if pauli in ("X", "Y") and s > t:
                    new_g.set_edata(edge, "xweb1", True)
                if pauli in ("Z", "Y") and s < t:
                    new_g.set_edata(edge, "zweb0", True)
                if pauli in ("Z", "Y") and s > t:
                    new_g.set_edata(edge, "zweb1", True)

        self.undo_stack.push(UpdateGraph(self.graph_view, new_g))  # or SetGraph if you don’t want undo entries
        self.graph_scene.invalidate() # TODO: invalidating the whole scene might be overkill
    

def create_titled_list_container(title: str) -> tuple[QWidget, QListWidget]:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    # Title Label
    title_label = QLabel(title)
    title_label.setStyleSheet("font-weight: bold; padding: 6px; background-color: #f0f0f0;")
    layout.addWidget(title_label)

    # The List Widget
    list_widget = QListWidget()
    # Optional: remove border to make it look integrated
    list_widget.setStyleSheet("QListWidget { border: none; }")
    layout.addWidget(list_widget)

    return container, list_widget

