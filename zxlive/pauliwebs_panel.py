import copy
import json
import os
from typing import Iterator

from PySide6.QtCore import Signal, QSettings
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QInputDialog, QMessageBox, QToolButton, QListWidgetItem
from pyzx import EdgeType, VertexType, sqasm
from pyzx.circuit.qasmparser import QASMParser
from zxlive.eitem import EItem
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut, Qt
from PySide6.QtWidgets import QMenu

from .common import ET, VT, GraphT, get_settings_value
from .pauliwebs_base_panel import PauliWebsBasePanel, create_titled_list_container
from .graphscene import EditGraphScene
from .graphview import GraphView
from .base_panel import BasePanel, ToolbarSection
from .graphview import GraphTool, ProofGraphView, WandTrace

import json
from pyzx.graph.jsonparser import json_to_graph
from pyzx.web import compute_pauli_webs

class PauliWebsPanel(PauliWebsBasePanel):
    """Panel for the edit mode of ZXLive."""
    graph_scene: EditGraphScene

    _curr_ety: EdgeType
    _curr_vty: VertexType

    def __init__(self, graph: GraphT, *actions: QAction) -> None:
        super().__init__(*actions)
        self.graph_scene = EditGraphScene()

        self.graph_scene.vertices_moved.connect(self.vert_moved)
        self.graph_scene.vertex_dropped_onto.connect(self._vertex_dropped_onto)
        self.graph_scene.edge_dragged.connect(self.change_edge_curves)

        self._curr_vty = VertexType.Z
        self._curr_ety = EdgeType.SIMPLE

        self.graph_view = GraphView(self.graph_scene)
        self.splitter.addWidget(self.graph_view)
        self.graph_view.set_graph(graph)

        self.web_container, self.web_list = create_titled_list_container("Pauli Webs")
        self.splitter.addWidget(self.web_container)
        self.web_list.itemClicked.connect(self._on_web_item_clicked)

        self._pauli_webs = []
        self._pauli_web_index = -1
        self._compute_pauli_webs()
        
    def _toolbar_sections(self) -> Iterator[ToolbarSection]:
        yield from []

    def _on_web_item_clicked(self, item: QListWidgetItem) -> None:
        # Retrieve the index we stored in the item
        index = item.data(Qt.ItemDataRole.UserRole)
        self._pauli_web_index = index
        self._show_current_pauli_web()