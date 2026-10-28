"""
Domain 2: Projects Management
(List, Get, Create, Update, Copy/Clone, Delete, Available Assignees, Project Configuration).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..client import OpenProjectClient
from ..hal_normalizer import normalize_project, normalize_user
from ..registry import ToolRegistry


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_list_projects",
        description=(
            "List and search projects in OpenProject (/api/v3/projects). "
            "Supports filtering by active state or name/identifier keyword."
        ),
        properties={
            "active_only": {
                "type": "boolean",
                "description": "If true, only return active projects.",
            },
            "search_name": {
                "type": "string",
                "description": "Optional substring filter on project name or identifier.",
            },
            "max_items": {
                "type": "integer",
                "description": "Maximum projects to return (default 100).",
                "default": 100,
            },
        },
        domain="projects",
        read_only=True,
        idempotent=True,
    )
    def op_list_projects(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if args.get("active_only") is True:
            filters.append({"active": {"operator": "=", "values": ["t"]}})
        if args.get("search_name"):
            filters.append({"name_and_identifier": {"operator": "~", "values": [str(args["search_name"])]}})

        params: Dict[str, Any] = {}
        if filters:
            params["filters"] = json.dumps(filters, ensure_ascii=False)

        elements, total = client.fetch_all_elements(
            "/api/v3/projects",
            params=params,
            max_items=int(args.get("max_items", 100)),
        )
        normalized = [
            normalize_project(p, sanitize=client.config.sanitize_untrusted_content)
            for p in elements
            if client.config.is_project_allowed(p.get("id"), write=False)
            or client.config.is_project_allowed(p.get("identifier"), write=False)
        ]
        return {
            "total": total,
            "returned": len(normalized),
            "projects": normalized,
        }

    @registry.register(
        name="op_get_project",
        description=(
            "Get detailed information about a project by ID or identifier (/api/v3/projects/{id}), "
            "including available work package types, versions count, and categories."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier slug (defaults to OPENPROJECT_PROJECT_ID if configured).",
            },
        },
        domain="projects",
        read_only=True,
        idempotent=True,
    )
    def op_get_project(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required when OPENPROJECT_PROJECT_ID is not set.")
        client.guard_read_project(proj_id)

        proj = client.get(f"/api/v3/projects/{proj_id}")
        info = normalize_project(proj, sanitize=client.config.sanitize_untrusted_content)

        # Enrich with enabled types and categories
        try:
            types_resp = client.get(f"/api/v3/projects/{proj_id}/types")
            types_list = (types_resp.get("_embedded") or {}).get("elements") or []
            info["enabledTypes"] = [{"id": t.get("id"), "name": t.get("name")} for t in types_list]
        except Exception:
            pass

        try:
            cats_resp = client.get(f"/api/v3/projects/{proj_id}/categories")
            cats_list = (cats_resp.get("_embedded") or {}).get("elements") or []
            info["categories"] = [{"id": c.get("id"), "name": c.get("name")} for c in cats_list]
        except Exception:
            pass

        return info

    @registry.register(
        name="op_create_project",
        description="Create a new project in OpenProject (POST /api/v3/projects).",
        properties={
            "name": {"type": "string", "description": "Display name of the project."},
            "identifier": {
                "type": "string",
                "description": "Unique URL-safe slug identifier (lowercase letters, digits, hyphens/underscores).",
            },
            "description": {"type": "string", "description": "Markdown description of the project."},
            "public": {"type": "boolean", "description": "Whether the project is public (default false)."},
            "active": {"type": "boolean", "description": "Whether the project is active (default true)."},
            "status_code": {
                "type": "string",
                "description": "Optional project health status: 'on_track', 'at_risk', 'off_track', 'not_started', 'finished', 'discontinued'.",
            },
            "status_explanation": {"type": "string", "description": "Explanation of project status."},
            "parent_id": {"type": "integer", "description": "Optional parent project ID for sub-projects."},
        },
        required=["name", "identifier"],
        domain="projects",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_project(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(args.get("identifier"))
        payload: Dict[str, Any] = {
            "name": args["name"],
            "identifier": args["identifier"],
            "public": bool(args.get("public", False)),
            "active": bool(args.get("active", True)),
            "_links": {},
        }
        if args.get("description") is not None:
            payload["description"] = {"raw": str(args["description"])}
        if args.get("status_explanation") is not None:
            payload["statusExplanation"] = {"raw": str(args["status_explanation"])}
        if args.get("status_code"):
            payload["status"] = str(args["status_code"])
        if args.get("parent_id"):
            payload["_links"]["parent"] = {"href": f"/api/v3/projects/{args['parent_id']}"}

        created = client.post("/api/v3/projects", json_body=payload)
        return normalize_project(created, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_update_project",
        description="Update an existing project's attributes, status, description, or parent (PATCH /api/v3/projects/{id}).",
        properties={
            "project_id": {"type": ["integer", "string"], "description": "Project ID or identifier."},
            "name": {"type": "string", "description": "New project name."},
            "description": {"type": "string", "description": "Updated Markdown description."},
            "public": {"type": "boolean", "description": "Whether the project is public."},
            "active": {"type": "boolean", "description": "Whether the project is active or archived."},
            "status_code": {
                "type": "string",
                "description": "Project status: 'on_track', 'at_risk', 'off_track', 'not_started', 'finished', 'discontinued'.",
            },
            "status_explanation": {"type": "string", "description": "Markdown explanation of project status."},
            "parent_id": {"type": ["integer", "null"], "description": "Parent project ID (or null to make root)."},
        },
        required=["project_id"],
        domain="projects",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_project(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args["project_id"]
        client.guard_write_operation(proj_id)
        payload: Dict[str, Any] = {"_links": {}}

        if "name" in args and args["name"] is not None:
            payload["name"] = args["name"]
        if "description" in args and args["description"] is not None:
            payload["description"] = {"raw": str(args["description"])}
        if "public" in args and args["public"] is not None:
            payload["public"] = bool(args["public"])
        if "active" in args and args["active"] is not None:
            payload["active"] = bool(args["active"])
        if "status_code" in args and args["status_code"] is not None:
            payload["status"] = str(args["status_code"])
        if "status_explanation" in args and args["status_explanation"] is not None:
            payload["statusExplanation"] = {"raw": str(args["status_explanation"])}
        if "parent_id" in args:
            pid = args["parent_id"]
            payload["_links"]["parent"] = {"href": f"/api/v3/projects/{pid}" if pid else None}

        if not payload["_links"]:
            del payload["_links"]

        updated = client.patch(f"/api/v3/projects/{proj_id}", json_body=payload)
        return normalize_project(updated, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_copy_project",
        description=(
            "Copy / clone an existing project or template (POST /api/v3/projects/{id}/copy), "
            "optionally copying work packages, memberships, versions, categories, wiki, and boards."
        ),
        properties={
            "source_project_id": {"type": ["integer", "string"], "description": "ID or identifier of source project."},
            "name": {"type": "string", "description": "Name of the new copied project."},
            "identifier": {"type": "string", "description": "Identifier slug for the new copied project."},
            "copy_work_packages": {"type": "boolean", "description": "Copy work packages (default true)."},
            "copy_members": {"type": "boolean", "description": "Copy memberships (default true)."},
            "copy_versions": {"type": "boolean", "description": "Copy versions/sprints (default true)."},
            "copy_categories": {"type": "boolean", "description": "Copy categories (default true)."},
            "copy_wiki": {"type": "boolean", "description": "Copy wiki pages (default true)."},
            "copy_boards": {"type": "boolean", "description": "Copy agile boards (default true)."},
            "send_notifications": {"type": "boolean", "description": "Send email notifications (default false)."},
        },
        required=["source_project_id", "name", "identifier"],
        domain="projects",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_copy_project(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        src = args["source_project_id"]
        client.guard_read_project(src)
        client.guard_write_operation(args["identifier"])

        payload = {
            "name": args["name"],
            "identifier": args["identifier"],
            "_meta": {
                "copyWorkPackages": bool(args.get("copy_work_packages", True)),
                "copyMembers": bool(args.get("copy_members", True)),
                "copyVersions": bool(args.get("copy_versions", True)),
                "copyCategories": bool(args.get("copy_categories", True)),
                "copyWiki": bool(args.get("copy_wiki", True)),
                "copyBoards": bool(args.get("copy_boards", True)),
                "sendNotifications": bool(args.get("send_notifications", False)),
            },
        }
        return client.post(f"/api/v3/projects/{src}/copy", json_body=payload)

    @registry.register(
        name="op_delete_project",
        description="Permanently delete a project by ID (DELETE /api/v3/projects/{id}). Requires delete policy enabled.",
        properties={
            "project_id": {"type": ["integer", "string"], "description": "ID or identifier of the project to delete."},
        },
        required=["project_id"],
        domain="projects",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_project(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args["project_id"]
        client.guard_write_operation(proj_id, is_delete=True, is_admin=True)
        return client.delete(f"/api/v3/projects/{proj_id}")

    @registry.register(
        name="op_list_project_assignable_users",
        description=(
            "List all users/principals who can be assigned to work packages in a project "
            "(/api/v3/projects/{id}/available_assignees)."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
        },
        domain="projects",
        read_only=True,
        idempotent=True,
    )
    def op_list_project_assignable_users(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_read_project(proj_id)
        elements, total = client.fetch_all_elements(f"/api/v3/projects/{proj_id}/available_assignees")
        return {
            "projectId": proj_id,
            "total": total,
            "assignableUsers": [normalize_user(u) for u in elements],
        }
