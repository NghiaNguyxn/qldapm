"""
MCP Primitive #2: Resources & Resource Templates (openproject:// URI scheme).
Allows MCP Clients and Users to attach live, read-only OpenProject context directly into the LLM prompt.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from .client import OpenProjectClient
from .hal_normalizer import (
    normalize_membership,
    normalize_project,
    normalize_version,
    normalize_work_package,
)
from .registry import ToolRegistry


def list_static_resources(client: OpenProjectClient) -> List[Dict[str, Any]]:
    """Return static MCP resources for resources/list."""
    default_proj = client.config.default_project_id or "default"
    resources = [
        {
            "uri": "openproject://instance/info",
            "name": "OpenProject Instance & System Configuration",
            "description": "Root instance metadata, version, hoursPerDay, and authenticated user info.",
            "mimeType": "application/json",
        },
        {
            "uri": "openproject://metadata/catalog",
            "name": "OpenProject Reference Metadata Catalog",
            "description": "All global statuses, work package types, priorities, and roles.",
            "mimeType": "application/json",
        },
        {
            "uri": "openproject://projects/list",
            "name": "OpenProject Active Projects Directory",
            "description": "List of all active projects accessible to the authenticated user.",
            "mimeType": "application/json",
        },
        {
            "uri": "openproject://notifications/unread",
            "name": "Unread In-App Notifications",
            "description": "Current user's unread OpenProject notifications.",
            "mimeType": "application/json",
        },
    ]
    if client.config.default_project_id:
        resources.extend([
            {
                "uri": f"openproject://projects/{default_proj}/overview",
                "name": f"Default Project (#{default_proj}) Overview",
                "description": "Project metadata, enabled types, versions, categories, and members.",
                "mimeType": "application/json",
            },
            {
                "uri": f"openproject://projects/{default_proj}/wbs",
                "name": f"Default Project (#{default_proj}) WBS Hierarchy Tree",
                "description": "Full hierarchical Work Breakdown Structure tree and 100% rule audit.",
                "mimeType": "application/json",
            },
            {
                "uri": f"openproject://projects/{default_proj}/gantt-cpm",
                "name": f"Default Project (#{default_proj}) Gantt Critical Path & EVM",
                "description": "Critical Path Method (CPM) network analysis and Earned Value Management (EVM) snapshot.",
                "mimeType": "application/json",
            },
        ])
    return resources


def list_resource_templates() -> List[Dict[str, Any]]:
    """Return dynamic URI templates (RFC 6570) for resources/templates/list."""
    return [
        {
            "uriTemplate": "openproject://projects/{project_id}/overview",
            "name": "Project Overview & Team Roster",
            "description": "Complete overview, types, versions, categories, and members of a project.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "openproject://projects/{project_id}/wbs",
            "name": "Project WBS Hierarchy Tree",
            "description": "Hierarchical WBS tree (Epic -> Phase -> Story -> Task -> Subtask) for a project.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "openproject://projects/{project_id}/gantt-cpm",
            "name": "Project Gantt Critical Path & EVM Snapshot",
            "description": "Critical Path Method (ES/EF/LS/LF/Float) and EVM (BAC/PV/EV/AC/CPI/SPI) for a project.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "openproject://work-packages/{work_package_id}",
            "name": "Work Package Full Context",
            "description": "Detailed work package attributes, description, comments, relations, and subtasks.",
            "mimeType": "application/json",
        },
        {
            "uriTemplate": "openproject://versions/{version_id}/sprint-report",
            "name": "Version / Sprint Progress Report",
            "description": "Sprint details, completion percentage, estimated vs spent hours, and assigned tasks.",
            "mimeType": "application/json",
        },
    ]


def read_resource(uri: str, client: OpenProjectClient, registry: ToolRegistry) -> Dict[str, Any]:
    """Resolve an openproject:// resource URI and return an MCP ReadResourceResult."""
    uri = uri.strip()

    if uri == "openproject://instance/info":
        t = registry.get_tool("op_doctor_check")
        data = t.handler(client, {}) if t else {}
        return _wrap_json_resource(uri, data)

    if uri == "openproject://metadata/catalog":
        statuses = client.get_cached("statuses", "/api/v3/statuses")
        types = client.get_cached("types:global", "/api/v3/types")
        priorities = client.get_cached("priorities", "/api/v3/priorities")
        roles = client.get_cached("roles", "/api/v3/roles")
        payload = {
            "statuses": [
                {"id": s.get("id"), "name": s.get("name"), "isClosed": s.get("isClosed")}
                for s in ((statuses.get("_embedded") or {}).get("elements") or [])
            ],
            "types": [
                {"id": t.get("id"), "name": t.get("name"), "isMilestone": t.get("isMilestone")}
                for t in ((types.get("_embedded") or {}).get("elements") or [])
            ],
            "priorities": [
                {"id": p.get("id"), "name": p.get("name"), "isDefault": p.get("isDefault")}
                for p in ((priorities.get("_embedded") or {}).get("elements") or [])
            ],
            "roles": [
                {"id": r.get("id"), "name": r.get("name")}
                for r in ((roles.get("_embedded") or {}).get("elements") or [])
            ],
        }
        return _wrap_json_resource(uri, payload)

    if uri == "openproject://projects/list":
        t = registry.get_tool("op_list_projects")
        data = t.handler(client, {"active_only": True}) if t else {}
        return _wrap_json_resource(uri, data)

    if uri == "openproject://notifications/unread":
        t = registry.get_tool("op_list_notifications")
        data = t.handler(client, {"unread_only": True}) if t else {}
        return _wrap_json_resource(uri, data)

    m_proj_overview = re.match(r"^openproject://projects/([^/]+)/overview$", uri)
    if m_proj_overview:
        proj_id = m_proj_overview.group(1)
        t_proj = registry.get_tool("op_get_project")
        t_mem = registry.get_tool("op_list_memberships")
        t_ver = registry.get_tool("op_list_versions")
        data = {
            "project": t_proj.handler(client, {"project_id": proj_id}) if t_proj else {},
            "memberships": t_mem.handler(client, {"project_id": proj_id}) if t_mem else {},
            "versions": t_ver.handler(client, {"project_id": proj_id}) if t_ver else {},
        }
        return _wrap_json_resource(uri, data)

    m_proj_wbs = re.match(r"^openproject://projects/([^/]+)/wbs$", uri)
    if m_proj_wbs:
        proj_id = m_proj_wbs.group(1)
        t_wbs = registry.get_tool("op_generate_wbs_tree")
        data = t_wbs.handler(client, {"project_id": proj_id}) if t_wbs else {}
        return _wrap_json_resource(uri, data)

    m_proj_gantt = re.match(r"^openproject://projects/([^/]+)/gantt-cpm$", uri)
    if m_proj_gantt:
        proj_id = m_proj_gantt.group(1)
        t_cpm = registry.get_tool("op_analyze_gantt_critical_path")
        t_evm = registry.get_tool("op_analyze_project_evm")
        data = {
            "criticalPathAnalysis": t_cpm.handler(client, {"project_id": proj_id}) if t_cpm else {},
            "earnedValueManagement": t_evm.handler(client, {"project_id": proj_id}) if t_evm else {},
        }
        return _wrap_json_resource(uri, data)

    m_wp = re.match(r"^openproject://work-packages/(\d+)$", uri)
    if m_wp:
        wp_id = int(m_wp.group(1))
        t_wp = registry.get_tool("op_get_work_package")
        t_sub = registry.get_tool("op_list_subtasks")
        data = {
            "workPackage": t_wp.handler(client, {"work_package_id": wp_id}) if t_wp else {},
            "subtasks": t_sub.handler(client, {"parent_id": wp_id}) if t_sub else {},
        }
        return _wrap_json_resource(uri, data)

    m_ver = re.match(r"^openproject://versions/(\d+)/sprint-report$", uri)
    if m_ver:
        vid = int(m_ver.group(1))
        t_ver = registry.get_tool("op_get_version")
        data = t_ver.handler(client, {"version_id": vid, "include_work_packages": True}) if t_ver else {}
        return _wrap_json_resource(uri, data)

    raise ValueError(f"Unsupported or unknown OpenProject MCP Resource URI: {uri}")


def _wrap_json_resource(uri: str, data: Any) -> Dict[str, Any]:
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(data, ensure_ascii=False, indent=2),
            }
        ]
    }
