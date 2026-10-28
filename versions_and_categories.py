"""
Domain 5: Versions (Sprints / Releases / Milestones) & Categories Management
(List, Get with Progress Summary, Create, Update, Delete Versions & Categories).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..client import OpenProjectClient
from ..hal_normalizer import (
    build_openproject_filters,
    extract_link_id,
    extract_link_title,
    normalize_version,
    normalize_work_package,
)
from ..registry import ToolRegistry


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_list_versions",
        description=(
            "List versions (Sprints, Releases, or Milestones) available in a project "
            "(/api/v3/projects/{id}/versions) or globally (/api/v3/versions)."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Optional project ID or identifier (defaults to OPENPROJECT_PROJECT_ID if set).",
            },
            "status_filter": {
                "type": "string",
                "description": "Optional status filter: 'open', 'locked', or 'closed'.",
            },
        },
        domain="versions_categories",
        read_only=True,
        idempotent=True,
    )
    def op_list_versions(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if proj_id:
            client.guard_read_project(proj_id)
            path = f"/api/v3/projects/{proj_id}/versions"
        else:
            path = "/api/v3/versions"

        elements, total = client.fetch_all_elements(path, max_items=200)
        versions = [
            normalize_version(v, sanitize=client.config.sanitize_untrusted_content)
            for v in elements
        ]
        status_f = args.get("status_filter")
        if status_f:
            versions = [v for v in versions if str(v.get("status", "")).lower() == str(status_f).lower()]

        return {
            "total": len(versions),
            "versions": versions,
        }

    @registry.register(
        name="op_get_version",
        description=(
            "Get details of a specific Version/Sprint by ID (/api/v3/versions/{id}), "
            "along with completion statistics of work packages assigned to this version."
        ),
        properties={
            "version_id": {"type": "integer", "description": "Version ID."},
            "include_work_packages": {
                "type": "boolean",
                "description": "Include work package progress summary for this version (default true).",
                "default": True,
            },
        },
        required=["version_id"],
        domain="versions_categories",
        read_only=True,
        idempotent=True,
    )
    def op_get_version(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        vid = args["version_id"]
        ver = client.get(f"/api/v3/versions/{vid}")
        info = normalize_version(ver, sanitize=client.config.sanitize_untrusted_content)

        if args.get("include_work_packages", True):
            filters_str = build_openproject_filters(version_id=vid)
            raw_wps, total = client.fetch_all_elements(
                "/api/v3/work_packages",
                params={"filters": filters_str},
                max_items=300,
            )
            wps = [normalize_work_package(w, sanitize=False, include_description=False) for w in raw_wps]
            total_est = sum(float(w.get("estimatedHours") or 0.0) for w in wps)
            total_spent = sum(float(w.get("spentHours") or 0.0) for w in wps)
            avg_done = (
                round(sum(int(w.get("percentageDone") or 0) for w in wps) / len(wps), 1)
                if wps
                else 0.0
            )
            info["sprintSummary"] = {
                "workPackageCount": total,
                "averagePercentageDone": avg_done,
                "totalEstimatedHours": round(total_est, 2),
                "totalSpentHours": round(total_spent, 2),
                "workPackages": wps,
            }
        return info

    @registry.register(
        name="op_create_version",
        description="Create a new Version / Sprint / Release in a project (POST /api/v3/versions).",
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Defining project ID (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "name": {"type": "string", "description": "Version/Sprint name (e.g. 'Sprint 1', 'v1.0 Release')."},
            "description": {"type": "string", "description": "Optional description."},
            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)."},
            "end_date": {"type": "string", "description": "End/release date (YYYY-MM-DD)."},
            "status": {
                "type": "string",
                "description": "Version status: 'open' (default), 'locked', or 'closed'.",
                "default": "open",
            },
            "sharing": {
                "type": "string",
                "description": "Sharing scope: 'none' (default), 'descendants', 'hierarchy', 'tree', 'system'.",
                "default": "none",
            },
        },
        required=["name"],
        domain="versions_categories",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_version(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_write_operation(proj_id)

        payload: Dict[str, Any] = {
            "name": args["name"],
            "status": args.get("status", "open"),
            "sharing": args.get("sharing", "none"),
            "_links": {
                "definingProject": {"href": f"/api/v3/projects/{proj_id}"},
            },
        }
        if args.get("description") is not None:
            payload["description"] = {"raw": str(args["description"])}
        if args.get("start_date"):
            payload["startDate"] = args["start_date"]
        if args.get("end_date"):
            payload["endDate"] = args["end_date"]

        created = client.post("/api/v3/versions", json_body=payload)
        return normalize_version(created, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_update_version",
        description="Update an existing Version / Sprint (PATCH /api/v3/versions/{id}).",
        properties={
            "version_id": {"type": "integer", "description": "Version ID to update."},
            "name": {"type": "string", "description": "Updated name."},
            "description": {"type": "string", "description": "Updated description."},
            "start_date": {"type": ["string", "null"], "description": "Updated start date (YYYY-MM-DD)."},
            "end_date": {"type": ["string", "null"], "description": "Updated end date (YYYY-MM-DD)."},
            "status": {"type": "string", "description": "'open', 'locked', or 'closed'."},
            "sharing": {"type": "string", "description": "'none', 'descendants', 'hierarchy', 'tree', 'system'."},
        },
        required=["version_id"],
        domain="versions_categories",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_version(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        vid = args["version_id"]
        payload: Dict[str, Any] = {}
        if "name" in args and args["name"] is not None:
            payload["name"] = args["name"]
        if "description" in args and args["description"] is not None:
            payload["description"] = {"raw": str(args["description"])}
        if "start_date" in args:
            payload["startDate"] = args["start_date"]
        if "end_date" in args:
            payload["endDate"] = args["end_date"]
        if "status" in args and args["status"] is not None:
            payload["status"] = args["status"]
        if "sharing" in args and args["sharing"] is not None:
            payload["sharing"] = args["sharing"]

        updated = client.patch(f"/api/v3/versions/{vid}", json_body=payload)
        return normalize_version(updated, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_delete_version",
        description="Delete a Version by ID (DELETE /api/v3/versions/{id}).",
        properties={
            "version_id": {"type": "integer", "description": "Version ID to delete."},
        },
        required=["version_id"],
        domain="versions_categories",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_version(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/versions/{args['version_id']}")

    @registry.register(
        name="op_list_categories",
        description="List work package categories defined in a project (/api/v3/projects/{id}/categories).",
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
        },
        domain="versions_categories",
        read_only=True,
        idempotent=True,
    )
    def op_list_categories(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_read_project(proj_id)
        data = client.get(f"/api/v3/projects/{proj_id}/categories")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "projectId": proj_id,
            "total": len(elements),
            "categories": [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "defaultAssignee": {
                        "id": extract_link_id(c.get("_links") or {}, "defaultAssignee"),
                        "name": extract_link_title(c.get("_links") or {}, "defaultAssignee"),
                    } if extract_link_id(c.get("_links") or {}, "defaultAssignee") else None,
                }
                for c in elements
            ],
        }

    @registry.register(
        name="op_create_category",
        description="Create a new work package category in a project (POST /api/v3/projects/{id}/categories).",
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "name": {"type": "string", "description": "Category name (e.g. 'Backend', 'Frontend', 'Database')."},
            "default_assignee_id": {
                "type": "integer",
                "description": "Optional user ID to auto-assign when this category is selected.",
            },
        },
        required=["name"],
        domain="versions_categories",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_category(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_write_operation(proj_id)

        payload: Dict[str, Any] = {"name": args["name"], "_links": {}}
        if args.get("default_assignee_id"):
            payload["_links"]["defaultAssignee"] = {"href": f"/api/v3/users/{args['default_assignee_id']}"}
        if not payload["_links"]:
            del payload["_links"]

        created = client.post(f"/api/v3/projects/{proj_id}/categories", json_body=payload)
        return {
            "id": created.get("id"),
            "name": created.get("name"),
        }

    @registry.register(
        name="op_delete_category",
        description="Delete a work package category by ID (DELETE /api/v3/categories/{id}).",
        properties={
            "category_id": {"type": "integer", "description": "Category ID to delete."},
        },
        required=["category_id"],
        domain="versions_categories",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_category(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/categories/{args['category_id']}")
