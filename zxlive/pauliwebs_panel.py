from __future__ import annotations

import copy
from typing import Iterator, Optional, cast

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QBrush
from PySide6.QtWidgets import (QLabel, QListWidget,
                               QListWidgetItem, QSplitter, QVBoxLayout, QWidget, QToolButton)
from pyzx import EdgeType, VertexType, pauliweb
from zxlive.graphview import GraphView

from .base_panel import BasePanel, ToolbarSection
from .commands import UpdateGraph
from .common import VT, GraphT, get_settings_value
from .dialogs import show_error_msg
from .graphscene import EditGraphScene, GraphScene


import json
from pyzx.graph.jsonparser import json_to_graph
from pyzx.web import compute_pauli_webs

# type alias
PauliWeb = pauliweb.PauliWeb[int, tuple[int ,int]]

class PauliWebsPanel(BasePanel):
    """write something here"""
    
    graph_scene: GraphScene
    sidebar: QSplitter

    _curr_ety: EdgeType
    _curr_vty: VertexType
    snap_vertex_edge = True
    patterns_folder: Optional[str] = None

    def __init__(self,  graph: GraphT, *actions: QAction) -> None:
        super().__init__(*actions)
        self.graph_scene = GraphScene()

        self.graph_scene.edge_double_clicked.connect(self.edge_double_clicked)

        self._curr_vty = VertexType.Z
        self._curr_ety = EdgeType.SIMPLE
        self.patterns_folder = get_settings_value("patterns-folder", str)
        
        
        self.graph_view = GraphView(self.graph_scene)
        self.splitter.addWidget(self.graph_view)
        self.graph_view.set_graph(graph)
        
        self.web_container, self.web_list = create_titled_list_container("Pauli Webs")
        self.splitter.addWidget(self.web_container)
        self.web_list.itemSelectionChanged.connect(self._on_web_selection_changed)
        
        self._pauli_webs: list[PauliWeb] = []
        self._pauli_web_index: list[int] = []
        self._compute_pauli_webs()

        self.edge_clicked = False
        
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
        
        inputs = ()
        outputs = ()
        try:
            self.graph.auto_detect_io()
            inputs = self.graph.inputs()
            outputs = self.graph.outputs()
        except Exception:
            show_error_msg("Warning: Could not auto-detect inputs/outputs for Pauli web computation", parent=self)
        
        # Populate the list widget
        self.web_list.clear()
        
        for i, web in enumerate(self._pauli_webs):
            is_region = i >= len(stabs)
            is_stab = any(e[0] in outputs or e[1] in outputs for e in web.half_edges())
            is_costab = any(e[0] in inputs or e[1] in inputs for e in web.half_edges())
            name = (
                "Detecting Region" if is_region
                else "Logical" if is_stab and is_costab
                else "Co-stabiliser" if is_costab
                else "Stabiliser" if is_stab
                else "Pauli Web"
            )
            
            label = f"{name} #{i + 1}"
            
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, i) # Store the index
            self.web_list.addItem(item)
        
        if self._pauli_webs:
            self.web_list.setCurrentRow(-1)
            self._pauli_web_index = []
            self._show_current_pauli_web()
    
    def _show_current_pauli_web(self) -> None:
        new_g = copy.deepcopy(self.graph_scene.g)
        for e in new_g.edges():
            new_g.set_edata(e, "xweb0", False)
            new_g.set_edata(e, "zweb0", False)
            new_g.set_edata(e, "xweb1", False)
            new_g.set_edata(e, "zweb1", False)

        if self._pauli_web_index:
            web = self._pauli_webs[self._pauli_web_index[0]]
            for i in self._pauli_web_index[1:]:
                web *= self._pauli_webs[i]
            
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
    
    def _on_web_selection_changed(self) -> None:
        selected_items = self.web_list.selectedItems()
        if not selected_items:
            self._pauli_web_index = []
        else:
            self._pauli_web_index = [item.data(Qt.ItemDataRole.UserRole) for item in selected_items]
        self._show_current_pauli_web()
    
    def _toolbar_sections(self) -> Iterator[ToolbarSection]:
        self.clear_pauli_webs = QToolButton(self)
        self.clear_pauli_webs.setText("Clear Pauli Webs")
        self.clear_pauli_webs.clicked.connect(self._clear_pauli_webs)
        yield ToolbarSection(self.clear_pauli_webs)

    def _clear_pauli_webs(self) -> None:
        self._pauli_web_index = []
        self.web_list.clearSelection()
        self._show_current_pauli_web()
    def edge_double_clicked(self, v: VT) -> None:
        for i,web in enumerate(self._pauli_webs):
                edge = (v[0], v[1])
                if edge in web.half_edges():
                    item = self.web_list.item(i)
                    if item:
                        if not self.edge_clicked:
                            item.setBackground(QColor("#FFCCCC"))
                        else:
                            item.setBackground(QBrush())
                    
        self.edge_clicked = not self.edge_clicked

            

def create_titled_list_container(title: str) -> tuple[QWidget, QListWidget]:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)

    # Title Label
    title_label = QLabel(title)
    title_label.setStyleSheet("font-weight: bold; padding: 4px")
    layout.addWidget(title_label)

    # The List Widget
    list_widget = QListWidget()
    # Optional: remove border to make it look integrated
    list_widget.setStyleSheet("QListWidget { border: none; }")
    list_widget.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
    layout.addWidget(list_widget)

    return container, list_widget
