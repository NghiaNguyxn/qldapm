"""
Domain 3: Work Packages Management
(List/Filter, Get Full Context, Form Validation, Create, Update with auto-lockVersion,
Delete, Subtasks, Bulk Create WBS Hierarchy, Bulk Update, Custom Actions).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..client import OpenProjectAPIError, OpenProjectClient
from ..hal_normalizer import (
    build_openproject_filters,
    hours_to_iso_duration,
    normalize_activity,
    normalize_relation,
    normalize_user,
    normalize_work_package,
)
from ..registry import ToolRegistry


def _build_wp_payload(
    client: OpenProjectClient,
    args: Dict[str, Any],
    project_id: Optional[int | str] = None,
    is_create: bool = False,
) -> Dict[str, Any]:
    """Construct an OpenProject HAL+JSON WorkPackage request body from ergonomic parameters."""
    payload: Dict[str, Any] = {"_links": {}}

    if args.get("subject") is not None:
        payload["subject"] = str(args["subject"])

    if args.get("description") is not None:
        payload["description"] = {"format": "markdown", "raw": str(args["description"])}

    if args.get("comment"):
        payload["comment"] = {"format": "markdown", "raw": str(args["comment"])}

    if project_id is not None and is_create:
        payload["_links"]["project"] = {"href": f"/api/v3/projects/{project_id}"}

    if args.get("type_id") is not None:
        t_id = client.resolve_type_id(args["type_id"], project_id=project_id)
        payload["_links"]["type"] = {"href": f"/api/v3/types/{t_id}"}

    if args.get("status_id") is not None:
        s_id = client.resolve_status_id(args["status_id"])
        payload["_links"]["status"] = {"href": f"/api/v3/statuses/{s_id}"}

    if args.get("priority_id") is not None:
        p_id = client.resolve_priority_id(args["priority_id"])
        payload["_links"]["priority"] = {"href": f"/api/v3/priorities/{p_id}"}

    if "assignee_id" in args:
        aid = args["assignee_id"]
        payload["_links"]["assignee"] = {"href": f"/api/v3/users/{aid}" if aid else None}

    if "responsible_id" in args:
        rid = args["responsible_id"]
        payload["_links"]["responsible"] = {"href": f"/api/v3/users/{rid}" if rid else None}

    if "parent_id" in args:
        pid = args["parent_id"]
        payload["_links"]["parent"] = {"href": f"/api/v3/work_packages/{pid}" if pid else None}

    if "version_id" in args:
        vid = args["version_id"]
        payload["_links"]["version"] = {"href": f"/api/v3/versions/{vid}" if vid else None}

    if "category_id" in args:
        cid = args["category_id"]
        payload["_links"]["category"] = {"href": f"/api/v3/categories/{cid}" if cid else None}

    if "budget_id" in args:
        bid = args["budget_id"]
        payload["_links"]["budget"] = {"href": f"/api/v3/budgets/{bid}" if bid else None}

    # Scheduling & Dates
    if "date" in args and args["date"] is not None:
        payload["date"] = args["date"]
    if "start_date" in args:
        payload["startDate"] = args["start_date"]
    if "due_date" in args:
        payload["dueDate"] = args["due_date"]
    if "schedule_manually" in args and args["schedule_manually"] is not None:
        payload["scheduleManually"] = bool(args["schedule_manually"])

    # Effort & Progress
    if "estimated_hours" in args:
        payload["estimatedTime"] = (
            hours_to_iso_duration(args["estimated_hours"]) if args["estimated_hours"] is not None else None
        )
    if "remaining_hours" in args:
        payload["remainingTime"] = (
            hours_to_iso_duration(args["remaining_hours"]) if args["remaining_hours"] is not None else None
        )
    if "percentage_done" in args and args["percentage_done"] is not None:
        payload["percentageDone"] = int(args["percentage_done"])
    if "story_points" in args:
        payload["storyPoints"] = int(args["story_points"]) if args["story_points"] is not None else None

    if "lock_version" in args and args["lock_version"] is not None:
        payload["lockVersion"] = int(args["lock_version"])

    # Custom fields (e.g. {"customField1": "val", "customField2": "/api/v3/custom_options/5"})
    custom_fields = args.get("custom_fields")
    if isinstance(custom_fields, dict):
        for cf_key, cf_val in custom_fields.items():
            key = cf_key if cf_key.startswith("customField") else f"customField{cf_key}"
            if isinstance(cf_val, str) and cf_val.startswith("/api/v3/"):
                payload["_links"][key] = {"href": cf_val}
            else:
                payload[key] = cf_val

    if not payload["_links"]:
        del payload["_links"]

    return payload


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_list_work_packages",
        description=(
            "Query, search, and filter work packages across a project or the entire instance. "
            "Supports rich filtering (status, type, priority, assignee, author, version, category, "
            "parent, keyword search, date ranges, or raw OpenProject API v3 filters), sorting, and pagination."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (optional; omit to search globally or pass default).",
            },
            "status_id": {
                "type": ["integer", "string"],
                "description": "Filter by status ID or status name (e.g. 'In progress', 'Closed').",
            },
            "status_open": {
                "type": "boolean",
                "description": "If true, only open work packages; if false, only closed work packages.",
            },
            "type_id": {
                "type": ["integer", "string"],
                "description": "Filter by work package type ID or name (e.g. 'Task', 'Phase', 'Milestone', 'Bug').",
            },
            "priority_id": {
                "type": ["integer", "string"],
                "description": "Filter by priority ID or name.",
            },
            "assignee_id": {
                "type": ["integer", "string"],
                "description": "Filter by assignee user ID, 'me', or 'unassigned'.",
            },
            "author_id": {"type": ["integer", "string"], "description": "Filter by author user ID or 'me'."},
            "responsible_id": {"type": ["integer", "string"], "description": "Filter by responsible user ID."},
            "version_id": {"type": ["integer", "string"], "description": "Filter by version/sprint ID."},
            "category_id": {"type": ["integer", "string"], "description": "Filter by category ID."},
            "parent_id": {"type": ["integer", "string"], "description": "Filter by direct parent work package ID."},
            "subject_contains": {"type": "string", "description": "Case-insensitive substring search in subject."},
            "search_text": {"type": "string", "description": "Search by subject or ID (** operator)."},
            "start_date_from": {"type": "string", "description": "Start date range lower bound (YYYY-MM-DD)."},
            "start_date_to": {"type": "string", "description": "Start date range upper bound (YYYY-MM-DD)."},
            "due_date_from": {"type": "string", "description": "Due date range lower bound (YYYY-MM-DD)."},
            "due_date_to": {"type": "string", "description": "Due date range upper bound (YYYY-MM-DD)."},
            "active_on_date": {
                "type": "string",
                "description": "Filter tasks active on a specific date ('today' or 'YYYY-MM-DD' where startDate <= date <= dueDate).",
            },
            "updated_since": {"type": "string", "description": "ISO timestamp or date (YYYY-MM-DD) for recently updated items."},
            "raw_filters": {
                "type": "array",
                "description": "Optional raw OpenProject API v3 filter objects: [{'field': {'operator': '=', 'values': ['...']}}].",
                "items": {"type": "object"},
            },
            "sort_by": {
                "type": "string",
                "description": "JSON array of sort pairs, e.g. '[[\"id\", \"asc\"]]' or '[[\"updatedAt\", \"desc\"]]'.",
            },
            "group_by": {"type": "string", "description": "Optional column to group results by (e.g. 'status', 'type', 'assignee')."},
            "include_description": {
                "type": "boolean",
                "description": "Include markdown descriptions in list output (default false to save context tokens).",
                "default": False,
            },
            "max_items": {
                "type": "integer",
                "description": "Maximum number of work packages to return (default 50, max 500).",
                "default": 50,
            },
        },
        domain="work_packages",
        read_only=True,
        idempotent=True,
    )
    def op_list_work_packages(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id")
        if proj_id:
            client.guard_read_project(proj_id)

        status_id = args.get("status_id")
        if status_id is not None and not str(status_id).isdigit():
            status_id = client.resolve_status_id(status_id)

        type_id = args.get("type_id")
        if type_id is not None and not str(type_id).isdigit():
            type_id = client.resolve_type_id(type_id, project_id=proj_id)

        priority_id = args.get("priority_id")
        if priority_id is not None and not str(priority_id).isdigit():
            priority_id = client.resolve_priority_id(priority_id)

        filters_str = build_openproject_filters(
            raw_filters=args.get("raw_filters"),
            project_id=None if proj_id else None,  # If proj_id is given, we use project endpoint
            status_id=status_id,
            status_open=args.get("status_open"),
            type_id=type_id,
            priority_id=priority_id,
            assignee_id=args.get("assignee_id"),
            author_id=args.get("author_id"),
            responsible_id=args.get("responsible_id"),
            version_id=args.get("version_id"),
            category_id=args.get("category_id"),
            parent_id=args.get("parent_id"),
            subject_contains=args.get("subject_contains"),
            search_text=args.get("search_text"),
            start_date_from=args.get("start_date_from"),
            start_date_to=args.get("start_date_to"),
            due_date_from=args.get("due_date_from"),
            due_date_to=args.get("due_date_to"),
            active_on_date=args.get("active_on_date"),
            updated_since=args.get("updated_since"),
        )

        path = f"/api/v3/projects/{proj_id}/work_packages" if proj_id else "/api/v3/work_packages"
        params: Dict[str, Any] = {"filters": filters_str if filters_str else "[]"}
        if args.get("sort_by"):
            params["sortBy"] = args["sort_by"]
        else:
            params["sortBy"] = json.dumps([["id", "asc"]])
        if args.get("group_by"):
            params["groupBy"] = args["group_by"]

        max_items = min(max(1, int(args.get("max_items", 50))), 500)
        elements, total = client.fetch_all_elements(path, params=params, max_items=max_items)
        inc_desc = bool(args.get("include_description", False))

        items = [
            normalize_work_package(
                wp,
                sanitize=client.config.sanitize_untrusted_content,
                include_description=inc_desc,
                compact=True,
            )
            for wp in elements
        ]
        return {
            "total": total,
            "returned": len(items),
            "workPackages": items,
        }

    @registry.register(
        name="op_get_work_package",
        description=(
            "Retrieve complete details of a single work package by ID (/api/v3/work_packages/{id}), "
            "optionally embedding its activities/comments, relations, attachments, and watchers."
        ),
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
            "include_activities": {
                "type": "boolean",
                "description": "Include activity/comment history (default true).",
                "default": True,
            },
            "include_relations": {
                "type": "boolean",
                "description": "Include dependency relations (default true).",
                "default": True,
            },
            "include_watchers": {
                "type": "boolean",
                "description": "Include watcher users list (default false).",
                "default": False,
            },
        },
        required=["work_package_id"],
        domain="work_packages",
        read_only=True,
        idempotent=True,
    )
    def op_get_work_package(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args["work_package_id"]
        wp = client.get(f"/api/v3/work_packages/{wp_id}")
        proj_info = normalize_work_package(wp, sanitize=client.config.sanitize_untrusted_content, include_description=True)
        proj_id = (proj_info.get("project") or {}).get("id")
        if proj_id:
            client.guard_read_project(proj_id)

        if args.get("include_activities", True):
            try:
                acts_resp = client.get(f"/api/v3/work_packages/{wp_id}/activities")
                acts = (acts_resp.get("_embedded") or {}).get("elements") or []
                proj_info["activities"] = [
                    normalize_activity(a, sanitize=client.config.sanitize_untrusted_content)
                    for a in acts[-20:]
                ]
            except Exception:
                pass

        if args.get("include_relations", True):
            try:
                rels_resp = client.get(f"/api/v3/work_packages/{wp_id}/relations")
                rels = (rels_resp.get("_embedded") or {}).get("elements") or []
                proj_info["relations"] = [normalize_relation(r) for r in rels]
            except Exception:
                pass

        if args.get("include_watchers", False):
            try:
                w_resp = client.get(f"/api/v3/work_packages/{wp_id}/watchers")
                watchers = (w_resp.get("_embedded") or {}).get("elements") or []
                proj_info["watchers"] = [normalize_user(u) for u in watchers]
            except Exception:
                pass

        return proj_info

    @registry.register(
        name="op_validate_work_package_form",
        description=(
            "Validate a work package creation or update payload against OpenProject's Form endpoint "
            "(/api/v3/work_packages/form or /api/v3/work_packages/{id}/form) WITHOUT saving changes. "
            "Returns validation errors, default values, and writable schema fields."
        ),
        properties={
            "work_package_id": {
                "type": "integer",
                "description": "Optional existing work package ID to validate an update; omit to validate creation.",
            },
            "project_id": {"type": ["integer", "string"], "description": "Project ID (required when creating)."},
            "subject": {"type": "string", "description": "Work package subject."},
            "type_id": {"type": ["integer", "string"], "description": "Type ID or name."},
            "status_id": {"type": ["integer", "string"], "description": "Status ID or name."},
            "priority_id": {"type": ["integer", "string"], "description": "Priority ID or name."},
            "assignee_id": {"type": "integer", "description": "Assignee user ID."},
            "parent_id": {"type": "integer", "description": "Parent work package ID."},
            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)."},
            "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD)."},
            "estimated_hours": {"type": "number", "description": "Estimated hours."},
            "custom_fields": {"type": "object", "description": "Custom fields dictionary."},
        },
        domain="work_packages",
        read_only=True,
        idempotent=True,
    )
    def op_validate_work_package_form(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args.get("work_package_id")
        proj_id = args.get("project_id") or client.config.default_project_id
        payload = _build_wp_payload(client, args, project_id=proj_id, is_create=(wp_id is None))

        if wp_id is not None:
            current = client.get(f"/api/v3/work_packages/{wp_id}")
            payload["lockVersion"] = current.get("lockVersion", 0)
            form = client.post(f"/api/v3/work_packages/{wp_id}/form", json_body=payload)
        else:
            form = client.post("/api/v3/work_packages/form", json_body=payload)

        embedded = form.get("_embedded") or {}
        validation_errors = embedded.get("validationErrors") or {}
        schema = embedded.get("schema") or {}
        required_fields = [
            k for k, v in schema.items()
            if isinstance(v, dict) and v.get("required") and v.get("writable")
        ]

        return {
            "valid": len(validation_errors) == 0,
            "validationErrors": {
                k: v.get("message") if isinstance(v, dict) else v
                for k, v in validation_errors.items()
            },
            "requiredWritableFields": required_fields,
            "previewPayload": normalize_work_package(
                embedded.get("payload") or {},
                sanitize=client.config.sanitize_untrusted_content,
            ),
        }

    @registry.register(
        name="op_create_work_package",
        description=(
            "Create a new work package (Task, Phase, Milestone, Epic, User story, Bug, Feature) "
            "in a project (POST /api/v3/projects/{project_id}/work_packages)."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Target Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "subject": {"type": "string", "description": "Title/subject of the work package."},
            "type_id": {
                "type": ["integer", "string"],
                "description": "Work package type ID or name (e.g. 'Task', 'Milestone', 'Phase', 'Epic', 'Bug').",
            },
            "status_id": {
                "type": ["integer", "string"],
                "description": "Initial status ID or name (e.g. 'New', 'In progress').",
            },
            "priority_id": {
                "type": ["integer", "string"],
                "description": "Priority ID or name (e.g. 'Low', 'Normal', 'High', 'Immediate').",
            },
            "description": {"type": "string", "description": "Markdown description."},
            "parent_id": {"type": "integer", "description": "Parent work package ID for WBS hierarchy / subtasks."},
            "assignee_id": {"type": "integer", "description": "User ID of the assignee."},
            "responsible_id": {"type": "integer", "description": "User ID of the accountable/responsible person."},
            "version_id": {"type": "integer", "description": "Target Version / Sprint ID."},
            "category_id": {"type": "integer", "description": "Category ID."},
            "budget_id": {"type": "integer", "description": "Budget ID."},
            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)."},
            "due_date": {"type": "string", "description": "Finish/due date (YYYY-MM-DD)."},
            "date": {"type": "string", "description": "Single date (YYYY-MM-DD) when creating a Milestone."},
            "schedule_manually": {
                "type": "boolean",
                "description": "Set true for manual scheduling (fixed dates) or false for automatic Gantt scheduling.",
            },
            "estimated_hours": {
                "type": ["number", "string"],
                "description": "Estimated effort in decimal hours (e.g. 8, 2.5) or ISO-8601 ('PT8H').",
            },
            "remaining_hours": {
                "type": ["number", "string"],
                "description": "Remaining effort in decimal hours or ISO-8601.",
            },
            "percentage_done": {"type": "integer", "description": "Completion percentage (0 to 100)."},
            "story_points": {"type": "integer", "description": "Agile Story Points."},
            "custom_fields": {
                "type": "object",
                "description": "Optional dictionary of custom fields (e.g. {'customField1': 'value'}).",
            },
            "notify": {
                "type": "boolean",
                "description": "Whether to send email notifications (default false to avoid spam).",
                "default": False,
            },
        },
        required=["subject"],
        domain="work_packages",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_work_package(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required when OPENPROJECT_PROJECT_ID is not set.")
        client.guard_write_operation(proj_id)

        payload = _build_wp_payload(client, args, project_id=proj_id, is_create=True)
        notify = "true" if args.get("notify", False) else "false"
        created = client.post(
            f"/api/v3/projects/{proj_id}/work_packages",
            json_body=payload,
            params={"notify": notify},
        )
        return normalize_work_package(created, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_update_work_package",
        description=(
            "Update an existing work package (PATCH /api/v3/work_packages/{id}). "
            "Automatically fetches and handles optimistic locking (lockVersion) and retries on 409 Conflict. "
            "Supports updating status, dates, assignee, parent, progress %, effort, custom fields, and adding a comment."
        ),
        properties={
            "work_package_id": {"type": "integer", "description": "ID of the work package to update."},
            "subject": {"type": "string", "description": "Updated subject/title."},
            "description": {"type": "string", "description": "Updated Markdown description."},
            "comment": {"type": "string", "description": "Optional journal comment explaining the update."},
            "type_id": {"type": ["integer", "string"], "description": "New work package type ID or name."},
            "status_id": {
                "type": ["integer", "string"],
                "description": (
                    "New status ID or name following the 3-Tier Workflow: "
                    "Epic (READY, In progress, In review, Done); "
                    "Task (READY, BA in progress, BA Review, Dev in progress, Ready for test, Testing, Rework, Done); "
                    "Sub-task (READY, In progress, Done)."
                ),
            },
            "priority_id": {"type": ["integer", "string"], "description": "New priority ID or name."},
            "assignee_id": {"type": ["integer", "null"], "description": "New assignee user ID (or null to unassign)."},
            "responsible_id": {"type": ["integer", "null"], "description": "New responsible user ID (or null to clear)."},
            "parent_id": {"type": ["integer", "null"], "description": "New parent work package ID (or null to make root)."},
            "version_id": {"type": ["integer", "null"], "description": "New version/sprint ID (or null to clear)."},
            "category_id": {"type": ["integer", "null"], "description": "New category ID (or null to clear)."},
            "start_date": {"type": ["string", "null"], "description": "Updated start date (YYYY-MM-DD or null)."},
            "due_date": {"type": ["string", "null"], "description": "Updated due date (YYYY-MM-DD or null)."},
            "date": {"type": ["string", "null"], "description": "Updated milestone date (YYYY-MM-DD or null)."},
            "schedule_manually": {"type": "boolean", "description": "Manual scheduling toggle."},
            "estimated_hours": {"type": ["number", "string", "null"], "description": "Estimated hours."},
            "remaining_hours": {"type": ["number", "string", "null"], "description": "Remaining hours."},
            "percentage_done": {"type": "integer", "description": "Progress percentage (0-100)."},
            "story_points": {"type": ["integer", "null"], "description": "Story points."},
            "custom_fields": {"type": "object", "description": "Custom fields dictionary."},
            "lock_version": {"type": "integer", "description": "Optional known lockVersion (auto-fetched if omitted)."},
            "notify": {"type": "boolean", "description": "Send email notifications (default false).", "default": False},
        },
        required=["work_package_id"],
        domain="work_packages",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_work_package(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args["work_package_id"]
        client.guard_write_operation()

        # Enforce 3-Tier Workflow Status Rules if status_id is being updated
        if args.get("status_id") is not None:
            raw_status = str(args["status_id"]).strip().lower()
            current_wp = client.get(f"/api/v3/work_packages/{wp_id}")
            current_norm = normalize_work_package(current_wp, sanitize=False, include_description=False)
            wp_type_name = str((current_norm.get("type") or {}).get("name") or "").strip().lower()
            args["lock_version"] = current_wp.get("lockVersion", 0)

            # Rule 1: 'In review' (status 20) is strictly reserved for Epic (Tier 1)
            if raw_status in ("in review", "20") and "epic" not in wp_type_name:
                raise OpenProjectAPIError(
                    f"Workflow Guardrail: Status 'In review' is restricted exclusively to Epic (Tier 1), "
                    f"cannot apply to #{wp_id} (type='{wp_type_name}'). "
                    f"For Task (Tier 2), use 'BA Review' or 'Ready for test' / 'Testing'. "
                    f"For Sub-task (Tier 3), use 'READY' -> 'In progress' -> 'Done'.",
                    status_code=422,
                    error_identifier="mcp:InvalidTierStatusTransition",
                )

            # Rule 2: Sub-task (Tier 3) only uses READY, In progress, Done
            subtask_forbidden = {
                "ba in progress", "ba review", "dev in progress",
                "ready for test", "testing", "rework", "in review",
                "18", "19", "17", "10", "9", "14", "20",
            }
            if wp_type_name in ("sub-task", "subtask") and raw_status in subtask_forbidden:
                raise OpenProjectAPIError(
                    f"Workflow Guardrail: Sub-task #{wp_id} only supports the 3-step workflow "
                    f"('READY' -> 'In progress' -> 'Done'), cannot transition to '{args['status_id']}'.",
                    status_code=422,
                    error_identifier="mcp:SubtaskWorkflowViolation",
                )

        payload = _build_wp_payload(client, args, is_create=False)
        updated = client.patch_work_package_safe(
            wp_id=wp_id,
            payload=payload,
            notify=bool(args.get("notify", False)),
        )
        return normalize_work_package(updated, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_delete_work_package",
        description="Delete a work package by ID (DELETE /api/v3/work_packages/{id}).",
        properties={
            "work_package_id": {"type": "integer", "description": "ID of the work package to delete."},
        },
        required=["work_package_id"],
        domain="work_packages",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_work_package(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args["work_package_id"]
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/work_packages/{wp_id}")

    @registry.register(
        name="op_list_subtasks",
        description="List all direct child subtasks (and their statuses/assignees/dates) of a parent work package.",
        properties={
            "parent_id": {"type": "integer", "description": "ID of the parent work package."},
        },
        required=["parent_id"],
        domain="work_packages",
        read_only=True,
        idempotent=True,
    )
    def op_list_subtasks(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        parent_id = args["parent_id"]
        filters_str = build_openproject_filters(parent_id=parent_id)
        elements, total = client.fetch_all_elements(
            "/api/v3/work_packages",
            params={"filters": filters_str, "sortBy": json.dumps([["id", "asc"]])},
            max_items=200,
        )
        subtasks = [
            normalize_work_package(wp, sanitize=client.config.sanitize_untrusted_content, include_description=False)
            for wp in elements
        ]
        return {
            "parentId": parent_id,
            "totalSubtasks": total,
            "subtasks": subtasks,
        }

    @registry.register(
        name="op_bulk_create_work_packages",
        description=(
            "Batch-create multiple work packages or a complete hierarchical WBS tree in a single tool call. "
            "Each item in 'items' can define a symbolic 'ref_key' (e.g. 'EPIC-1') and children can reference "
            "it via 'parent_ref' ('EPIC-1') or an existing numeric 'parent_id'."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Target Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "items": {
                "type": "array",
                "description": (
                    "List of work package objects to create in order. Each object supports: "
                    "ref_key, parent_ref, parent_id, subject, type_id, status_id, priority_id, "
                    "assignee_id, start_date, due_date, estimated_hours, percentage_done, description, schedule_manually."
                ),
                "items": {"type": "object"},
            },
            "notify": {"type": "boolean", "description": "Send email notifications (default false).", "default": False},
        },
        required=["items"],
        domain="work_packages",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_bulk_create_work_packages(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_write_operation(proj_id)

        items = args.get("items") or []
        notify = "true" if args.get("notify", False) else "false"
        ref_map: Dict[str, int] = {}
        created_list: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for idx, item in enumerate(items):
            if not isinstance(item, dict) or not item.get("subject"):
                continue
            item_copy = dict(item)
            ref_key = item_copy.pop("ref_key", None)
            parent_ref = item_copy.pop("parent_ref", None)
            if parent_ref and str(parent_ref) in ref_map:
                item_copy["parent_id"] = ref_map[str(parent_ref)]

            try:
                payload = _build_wp_payload(client, item_copy, project_id=proj_id, is_create=True)
                created = client.post(
                    f"/api/v3/projects/{proj_id}/work_packages",
                    json_body=payload,
                    params={"notify": notify},
                )
                norm = normalize_work_package(created, sanitize=client.config.sanitize_untrusted_content, include_description=False)
                if ref_key and norm.get("id"):
                    ref_map[str(ref_key)] = int(norm["id"])
                created_list.append(norm)
            except Exception as exc:
                errors.append({"index": idx, "subject": item.get("subject"), "error": str(exc)})

        return {
            "requestedCount": len(items),
            "createdCount": len(created_list),
            "errorCount": len(errors),
            "refKeyToIdMap": ref_map,
            "createdWorkPackages": created_list,
            "errors": errors,
        }

    @registry.register(
        name="op_bulk_update_work_packages",
        description="Batch-update multiple work packages in one call (auto-handling lockVersion for each item).",
        properties={
            "updates": {
                "type": "array",
                "description": (
                    "Array of update objects. Each object MUST include 'work_package_id' plus any fields to update "
                    "(status_id, assignee_id, start_date, due_date, percentage_done, estimated_hours, parent_id, comment, etc.)."
                ),
                "items": {"type": "object"},
            },
            "notify": {"type": "boolean", "description": "Send email notifications (default false).", "default": False},
        },
        required=["updates"],
        domain="work_packages",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_bulk_update_work_packages(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        updates = args.get("updates") or []
        notify = bool(args.get("notify", False))
        succeeded: List[Dict[str, Any]] = []
        failed: List[Dict[str, Any]] = []

        for item in updates:
            if not isinstance(item, dict) or not item.get("work_package_id"):
                continue
            wp_id = item["work_package_id"]
            try:
                payload = _build_wp_payload(client, item, is_create=False)
                res = client.patch_work_package_safe(wp_id, payload, notify=notify)
                succeeded.append(
                    normalize_work_package(res, sanitize=client.config.sanitize_untrusted_content, include_description=False)
                )
            except Exception as exc:
                failed.append({"workPackageId": wp_id, "error": str(exc)})

        return {
            "requestedCount": len(updates),
            "updatedCount": len(succeeded),
            "failedCount": len(failed),
            "updatedWorkPackages": succeeded,
            "failures": failed,
        }

    @registry.register(
        name="op_execute_custom_action",
        description=(
            "Execute a preconfigured OpenProject Custom Action on a work package "
            "(POST /api/v3/custom_actions/{custom_action_id}/execute)."
        ),
        properties={
            "custom_action_id": {"type": "integer", "description": "ID of the custom action."},
            "work_package_id": {"type": "integer", "description": "Target work package ID."},
        },
        required=["custom_action_id", "work_package_id"],
        domain="work_packages",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_execute_custom_action(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        wp_id = args["work_package_id"]
        ca_id = args["custom_action_id"]
        current = client.get(f"/api/v3/work_packages/{wp_id}")
        payload = {
            "lockVersion": current.get("lockVersion", 0),
            "_links": {
                "workPackage": {"href": f"/api/v3/work_packages/{wp_id}"},
            },
        }
        res = client.post(f"/api/v3/custom_actions/{ca_id}/execute", json_body=payload)
        return normalize_work_package(res, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_list_work_package_revisions",
        description=(
            "List Git/Subversion repository revisions (commits) associated with a work package "
            "(/api/v3/work_packages/{id}/revisions)."
        ),
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
        },
        required=["work_package_id"],
        domain="work_packages",
        read_only=True,
        idempotent=True,
    )
    def op_list_work_package_revisions(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args["work_package_id"]
        data = client.get(f"/api/v3/work_packages/{wp_id}/revisions")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "workPackageId": wp_id,
            "total": len(elements),
            "revisions": [
                {
                    "id": r.get("id"),
                    "identifier": r.get("identifier"),
                    "formattedIdentifier": r.get("formattedIdentifier"),
                    "authorName": r.get("authorName"),
                    "message": (r.get("message") or {}).get("raw"),
                    "createdAt": r.get("createdAt"),
                }
                for r in elements
            ],
        }

    @registry.register(
        name="op_list_work_package_file_links",
        description=(
            "List external cloud storage File Links (Nextcloud / OneDrive / SharePoint) attached to a work package "
            "(/api/v3/work_packages/{id}/file_links)."
        ),
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
        },
        required=["work_package_id"],
        domain="work_packages",
        read_only=True,
        idempotent=True,
    )
    def op_list_work_package_file_links(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args["work_package_id"]
        data = client.get(f"/api/v3/work_packages/{wp_id}/file_links")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "workPackageId": wp_id,
            "total": len(elements),
            "fileLinks": [
                {
                    "id": fl.get("id"),
                    "originData": fl.get("originData"),
                    "createdAt": fl.get("createdAt"),
                }
                for fl in elements
            ],
        }

    @registry.register(
        name="op_import_standard_wbs_csv",
        description=(
            "Import the 95 Work Packages (4 Epics, 19 Tasks, 72 Sub-tasks) from OpenProject_Import_QLDAPM_Standard_Ratio.csv "
            "into a target project in Depth-First Staircase order, automatically resolving Types, Statuses, Assignees, "
            "Versions/Sprints, and Parent-Child links."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Target Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "csv_path": {
                "type": "string",
                "description": "Optional path to CSV file (defaults to OpenProject_Import_QLDAPM_Standard_Ratio.csv in workspace root).",
            },
            "clear_existing": {
                "type": "boolean",
                "description": "Whether to clear existing work packages in the project before importing (default true).",
                "default": True,
            },
        },
        domain="work_packages",
        read_only=False,
    )
    def op_import_standard_wbs_csv(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        import csv
        from pathlib import Path

        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_write_operation(project_ref=proj_id)

        default_csv = Path(__file__).resolve().parent.parent.parent / "OpenProject_Import_QLDAPM_Standard_Ratio.csv"
        csv_file = Path(args.get("csv_path") or default_csv)
        if not csv_file.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_file}")

        with open(csv_file, mode="r", encoding="utf-8-sig") as f:
            raw_rows = list(csv.DictReader(f))

        epics = [r for r in raw_rows if r["Type"] == "Epic"]
        tasks_by_epic: Dict[str, List[Dict[str, str]]] = {}
        subs_by_task: Dict[str, List[Dict[str, str]]] = {}
        for r in raw_rows:
            if r["Type"] == "Task":
                tasks_by_epic.setdefault(str(r["Parent"]).strip(), []).append(r)
            elif r["Type"] == "Sub-task":
                subs_by_task.setdefault(str(r["Parent"]).strip(), []).append(r)

        ordered_rows: List[Dict[str, str]] = []
        for e in epics:
            eid = str(e["ID"]).strip()
            ordered_rows.append(e)
            for t in tasks_by_epic.get(eid, []):
                tid = str(t["ID"]).strip()
                ordered_rows.append(t)
                for s in subs_by_task.get(tid, []):
                    ordered_rows.append(s)

        if bool(args.get("clear_existing", True)):
            existing_wps, _ = client.fetch_all_elements(
                f"/api/v3/projects/{proj_id}/work_packages",
                params={"filters": "[]"},
                max_items=500,
            )
            for wp in existing_wps:
                try:
                    client.delete(f"/api/v3/work_packages/{wp['id']}")
                except Exception:
                    pass

        users, _ = client.fetch_all_elements("/api/v3/users", max_items=200)
        assignee_map: Dict[str, int] = {}
        for u in users:
            uid = int(u["id"])
            uname = str(u.get("name") or "")
            uemail = str(u.get("email") or u.get("login") or "").lower()
            if "nghĩa" in uname.lower() or "nghia" in uemail:
                assignee_map["Nguyễn Trung Nghĩa"] = uid
            elif "trung" in uname.lower() or "trungnv" in uemail:
                assignee_map["Nguyễn Vĩnh Trung"] = uid
            elif "hiếu" in uname.lower() or "hieuvq" in uemail:
                assignee_map["Vũ Quốc Hiếu"] = uid
            elif "thành" in uname.lower() or "thanhbt" in uemail:
                assignee_map["Bùi Tuấn Thành"] = uid
            elif "vinh" in uname.lower() or "vinhld" in uemail:
                assignee_map["Lương Duy Vinh"] = uid

        versions, _ = client.fetch_all_elements(f"/api/v3/projects/{proj_id}/versions", max_items=100)
        ver_map = {str(v["name"]).strip(): int(v["id"]) for v in versions if "name" in v and "id" in v}

        types_list, _ = client.fetch_all_elements("/api/v3/types", max_items=100)
        type_map = {str(t["name"]).strip().lower(): int(t["id"]) for t in types_list}
        t_epic = type_map.get("epic") or type_map.get("sử thi") or 5
        t_task = type_map.get("task") or type_map.get("nhiệm vụ") or 1
        t_subtask = type_map.get("sub-task") or type_map.get("subtask") or t_task

        statuses_list, _ = client.fetch_all_elements("/api/v3/statuses", max_items=100)
        stat_map = {str(s["name"]).strip().lower(): int(s["id"]) for s in statuses_list}
        s_ready = stat_map.get("ready") or stat_map.get("mới") or stat_map.get("new") or 1
        s_inprog = stat_map.get("in progress") or stat_map.get("đang xử lý") or 7
        s_devinprog = stat_map.get("dev in progress") or s_inprog
        s_done = stat_map.get("done") or stat_map.get("closed") or stat_map.get("đóng cửa") or 12

        priorities_list, _ = client.fetch_all_elements("/api/v3/priorities", max_items=100)
        prio_map = {str(p["name"]).strip().lower(): int(p["id"]) for p in priorities_list}
        p_low = prio_map.get("low") or prio_map.get("thấp") or 7
        p_normal = prio_map.get("normal") or prio_map.get("bình thường") or 8
        p_high = prio_map.get("high") or prio_map.get("cao") or 9

        csv_id_to_op_id: Dict[str, int] = {}
        created_items: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []

        for r in ordered_rows:
            csv_id = str(r["ID"]).strip()
            parent_csv_id = str(r["Parent"]).strip()
            rtype = r["Type"].strip()
            subject = r["Subject"].strip()
            if rtype == "Epic" and not subject.startswith("[Epic"):
                subject = f"[{subject}]" if subject.startswith("Epic") else f"[Epic] {subject}"

            desc = r["Description"].strip()
            assignee_name = r["Assignee"].strip()
            sdate = r["Start date"].strip()
            fdate = r["Finish date"].strip()
            hours = int(float(r["Estimated time (Hours)"] or 0))
            sp_val = round(float(r["Story Points"] or 0))
            prio_str = r["Priority"].strip().lower()
            prio_id = p_high if prio_str == "high" else (p_low if prio_str == "low" else p_normal)

            raw_st = r["Status"].strip().lower()
            if raw_st in ("closed", "done"):
                stat_id = s_done
                pct_done = 100
            elif raw_st in ("in progress",):
                stat_id = s_devinprog if rtype == "Task" else s_inprog
                pct_done = 50
            else:
                stat_id = stat_map.get(raw_st, s_ready)
                pct_done = 0

            type_id = t_epic if rtype == "Epic" else (t_subtask if rtype == "Sub-task" else t_task)
            links: Dict[str, Any] = {
                "type": {"href": f"/api/v3/types/{type_id}"},
                "status": {"href": f"/api/v3/statuses/{stat_id}"},
                "priority": {"href": f"/api/v3/priorities/{prio_id}"},
            }
            if assignee_name in assignee_map:
                links["assignee"] = {"href": f"/api/v3/users/{assignee_map[assignee_name]}"}
            if parent_csv_id and parent_csv_id in csv_id_to_op_id:
                links["parent"] = {"href": f"/api/v3/work_packages/{csv_id_to_op_id[parent_csv_id]}"}

            vname = r.get("Version", "").strip()
            if vname and vname in ver_map:
                links["version"] = {"href": f"/api/v3/versions/{ver_map[vname]}"}

            payload: Dict[str, Any] = {
                "subject": subject,
                "description": {"format": "markdown", "raw": desc},
                "scheduleManually": True,
                "startDate": sdate,
                "dueDate": fdate,
                "storyPoints": sp_val,
                "percentageDone": pct_done,
                "_links": links,
            }
            if rtype == "Sub-task" and hours > 0:
                payload["estimatedTime"] = f"PT{hours}H"

            try:
                created = client.post(
                    f"/api/v3/projects/{proj_id}/work_packages",
                    params={"notify": "false"},
                    json_body=payload,
                )
                op_id = int(created["id"])
                csv_id_to_op_id[csv_id] = op_id
                created_items.append({
                    "csvId": csv_id,
                    "openProjectId": op_id,
                    "type": rtype,
                    "subject": subject,
                    "assignee": assignee_name,
                })
            except Exception as exc:
                errors.append({"csvId": csv_id, "subject": subject, "error": str(exc)})

        return {
            "projectId": proj_id,
            "totalRows": len(ordered_rows),
            "importedCount": len(created_items),
            "errorCount": len(errors),
            "errors": errors[:10],
            "sampleCreated": created_items[:15],
        }


