"""KIN V1.1 TUI Foundation, Container, and Domain Widgets Package.

Spec authority: KIN-V1.1-TUI-SYSTEM.md §14.5
"""

from kin.tui.widgets.activity_feed import ActivityFeedWidget
from kin.tui.widgets.agent_card import AgentCardWidget
from kin.tui.widgets.agent_picker import AgentPickerWidget
from kin.tui.widgets.approval_card import ApprovalCardWidget
from kin.tui.widgets.artifact_list import ArtifactListWidget
from kin.tui.widgets.badge import BadgeWidget
from kin.tui.widgets.command_palette import CommandPaletteModal, CommandPaletteWidget
from kin.tui.widgets.data_table import ColumnDef, DataTableWidget
from kin.tui.widgets.dispatch_wizard import DispatchWizardWidget
from kin.tui.widgets.empty_state import EmptyStateWidget
from kin.tui.widgets.exchange_timeline import ExchangeTimelineWidget
from kin.tui.widgets.inspector import InspectorWidget
from kin.tui.widgets.lifecycle import (
    LifecycleWidgetMixin,
    WidgetLifecycleState,
    is_narrow_breakpoint,
)
from kin.tui.widgets.modal import ModalScreenWidget, ModalWidget
from kin.tui.widgets.outcome_card import OutcomeCardWidget
from kin.tui.widgets.panel import PanelWidget
from kin.tui.widgets.progress_bar import ProgressBarWidget
from kin.tui.widgets.quick_switcher import QuickSwitcherModal, QuickSwitcherWidget
from kin.tui.widgets.search_field import SearchFieldWidget
from kin.tui.widgets.session_map import SessionMapWidget
from kin.tui.widgets.sidebar_tree import SidebarNode, SidebarTreeWidget
from kin.tui.widgets.spinner import SpinnerWidget
from kin.tui.widgets.status_line import StatusLineWidget
from kin.tui.widgets.timeline import TimelineItem, TimelineWidget
from kin.tui.widgets.toast import ToastWidget
from kin.tui.widgets.trust_strip import TrustStripWidget
from kin.tui.widgets.workspace_tab_bar import WorkspaceTabBarWidget

__all__ = [
    "WidgetLifecycleState",
    "LifecycleWidgetMixin",
    "is_narrow_breakpoint",
    # Phase A Foundation Widgets (8)
    "PanelWidget",
    "BadgeWidget",
    "StatusLineWidget",
    "SpinnerWidget",
    "ProgressBarWidget",
    "ToastWidget",
    "ModalWidget",
    "ModalScreenWidget",
    "EmptyStateWidget",
    # Phase B Foundation & Migrated Components (8)
    "SearchFieldWidget",
    "ColumnDef",
    "DataTableWidget",
    "TimelineItem",
    "TimelineWidget",
    "WorkspaceTabBarWidget",
    "SidebarNode",
    "SidebarTreeWidget",
    "InspectorWidget",
    "CommandPaletteWidget",
    "CommandPaletteModal",
    "QuickSwitcherWidget",
    "QuickSwitcherModal",
    # Phase C Domain Widgets (10)
    "AgentCardWidget",
    "AgentPickerWidget",
    "DispatchWizardWidget",
    "SessionMapWidget",
    "ExchangeTimelineWidget",
    "ActivityFeedWidget",
    "ArtifactListWidget",
    "ApprovalCardWidget",
    "OutcomeCardWidget",
    "TrustStripWidget",
]
