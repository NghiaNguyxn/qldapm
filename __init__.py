"""
Domain Tool Modules for the OpenProject MCP Server.
"""

from __future__ import annotations

from ..registry import ToolRegistry
from . import (
    analytics_evm_agile,
    comments_watchers_attachments,
    projects,
    queries_wiki_collab,
    relations_and_gantt,
    system_and_metadata,
    time_and_budgets,
    users_memberships_groups,
    versions_and_categories,
    work_packages,
)


def register_all_domain_tools(registry: ToolRegistry) -> None:
    """Register all 10 OpenProject API v3 domain modules into the central ToolRegistry."""
    system_and_metadata.register_tools(registry)
    projects.register_tools(registry)
    work_packages.register_tools(registry)
    relations_and_gantt.register_tools(registry)
    versions_and_categories.register_tools(registry)
    comments_watchers_attachments.register_tools(registry)
    time_and_budgets.register_tools(registry)
    users_memberships_groups.register_tools(registry)
    queries_wiki_collab.register_tools(registry)
    analytics_evm_agile.register_tools(registry)
