"""
Domain 7: Time Tracking (Time Entries) & Project Budgets
(List/Filter Time Entries, Get, Log Spent Time, Update, Delete, Timesheet Aggregator, Budgets).
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from typing import Any, Dict, List

from ..client import OpenProjectClient
from ..hal_normalizer import (
    extract_link_id,
    extract_link_title,
    hours_to_iso_duration,
    normalize_time_entry,
    wrap_untrusted_text,
)
from ..registry import ToolRegistry


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_list_time_entries",
        description=(
            "List and filter logged time entries (/api/v3/time_entries). "
            "Can filter by project_id, work_package_id, user_id, or spentOn date range."
        ),
        properties={
            "project_id": {"type": ["integer", "string"], "description": "Filter by project ID."},
            "work_package_id": {"type": "integer", "description": "Filter by work package ID."},
            "user_id": {"type": ["integer", "string"], "description": "Filter by user ID or 'me'."},
            "spent_on_from": {"type": "string", "description": "Start date (YYYY-MM-DD)."},
            "spent_on_to": {"type": "string", "description": "End date (YYYY-MM-DD)."},
            "max_items": {"type": "integer", "description": "Max entries to return (default 100).", "default": 100},
        },
        domain="time_budgets",
        read_only=True,
        idempotent=True,
    )
    def op_list_time_entries(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if args.get("project_id"):
            client.guard_read_project(args["project_id"])
            filters.append({"project": {"operator": "=", "values": [str(args["project_id"])]}})
        if args.get("work_package_id"):
            filters.append({"work_package": {"operator": "=", "values": [str(args["work_package_id"])]}})
        if args.get("user_id"):
            filters.append({"user": {"operator": "=", "values": [str(args["user_id"])]}})
        if args.get("spent_on_from") and args.get("spent_on_to"):
            filters.append(
                {"spentOn": {"operator": "<>d", "values": [args["spent_on_from"], args["spent_on_to"]]}}
            )

        params: Dict[str, Any] = {}
        if filters:
            params["filters"] = json.dumps(filters)

        elements, total = client.fetch_all_elements(
            "/api/v3/time_entries",
            params=params,
            max_items=int(args.get("max_items", 100)),
        )
        entries = [
            normalize_time_entry(e, sanitize=client.config.sanitize_untrusted_content)
            for e in elements
        ]
        total_hours = round(sum(float(e.get("hours") or 0.0) for e in entries), 2)
        return {
            "total": total,
            "returned": len(entries),
            "totalLoggedHours": total_hours,
            "timeEntries": entries,
        }

    @registry.register(
        name="op_get_time_entry",
        description="Get a single time entry by ID (/api/v3/time_entries/{id}).",
        properties={
            "time_entry_id": {"type": "integer", "description": "Time entry ID."},
        },
        required=["time_entry_id"],
        domain="time_budgets",
        read_only=True,
        idempotent=True,
    )
    def op_get_time_entry(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        entry = client.get(f"/api/v3/time_entries/{args['time_entry_id']}")
        return normalize_time_entry(entry, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_log_time_entry",
        description=(
            "Log spent time against a work package or project (POST /api/v3/time_entries). "
            "Accepts hours as decimal numbers (e.g. 2.5 for 2h 30m) or ISO-8601 strings ('PT2H30M')."
        ),
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID to log time against."},
            "project_id": {
                "type": ["integer", "string"],
                "description": "Optional project ID (inferred from work package if omitted).",
            },
            "hours": {
                "type": ["number", "string"],
                "description": "Hours spent (e.g. 3.5 or 'PT3H30M').",
            },
            "spent_on": {
                "type": "string",
                "description": "Date the work was performed (YYYY-MM-DD, defaults to today).",
            },
            "activity_id": {
                "type": "integer",
                "description": "Optional time entry activity ID (see op_list_time_entry_activities).",
            },
            "comment": {"type": "string", "description": "Comment describing the work performed."},
            "user_id": {"type": "integer", "description": "Optional user ID if logging on behalf of another user."},
        },
        required=["work_package_id", "hours"],
        domain="time_budgets",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_log_time_entry(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(args.get("project_id"))
        wp_id = int(args["work_package_id"])
        spent_on = args.get("spent_on") or date.today().isoformat()
        iso_hours = hours_to_iso_duration(args["hours"])

        payload: Dict[str, Any] = {
            "hours": iso_hours,
            "spentOn": spent_on,
            "_links": {
                "workPackage": {"href": f"/api/v3/work_packages/{wp_id}"},
                "entity": {"href": f"/api/v3/work_packages/{wp_id}"},
            },
        }
        if args.get("project_id"):
            payload["_links"]["project"] = {"href": f"/api/v3/projects/{args['project_id']}"}
        if args.get("activity_id"):
            payload["_links"]["activity"] = {"href": f"/api/v3/time_entries/activities/{args['activity_id']}"}
        if args.get("user_id"):
            payload["_links"]["user"] = {"href": f"/api/v3/users/{args['user_id']}"}
        if args.get("comment") is not None:
            payload["comment"] = {"raw": str(args["comment"])}

        created = client.post("/api/v3/time_entries", json_body=payload)
        return normalize_time_entry(created, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_update_time_entry",
        description="Update an existing time entry (PATCH /api/v3/time_entries/{id}).",
        properties={
            "time_entry_id": {"type": "integer", "description": "Time entry ID."},
            "hours": {"type": ["number", "string"], "description": "Updated hours (decimal or ISO-8601)."},
            "spent_on": {"type": "string", "description": "Updated date (YYYY-MM-DD)."},
            "activity_id": {"type": "integer", "description": "Updated activity ID."},
            "comment": {"type": "string", "description": "Updated comment."},
        },
        required=["time_entry_id"],
        domain="time_budgets",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_time_entry(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        tid = args["time_entry_id"]
        payload: Dict[str, Any] = {"_links": {}}
        if "hours" in args and args["hours"] is not None:
            payload["hours"] = hours_to_iso_duration(args["hours"])
        if "spent_on" in args and args["spent_on"] is not None:
            payload["spentOn"] = args["spent_on"]
        if "comment" in args and args["comment"] is not None:
            payload["comment"] = {"raw": str(args["comment"])}
        if "activity_id" in args and args["activity_id"] is not None:
            payload["_links"]["activity"] = {"href": f"/api/v3/time_entries/activities/{args['activity_id']}"}
        if not payload["_links"]:
            del payload["_links"]

        updated = client.patch(f"/api/v3/time_entries/{tid}", json_body=payload)
        return normalize_time_entry(updated, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_delete_time_entry",
        description="Delete a logged time entry by ID (DELETE /api/v3/time_entries/{id}).",
        properties={
            "time_entry_id": {"type": "integer", "description": "Time entry ID to delete."},
        },
        required=["time_entry_id"],
        domain="time_budgets",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_time_entry(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/time_entries/{args['time_entry_id']}")

    @registry.register(
        name="op_summarize_time_report",
        description=(
            "Generate an aggregated timesheet report breaking down logged hours by User, "
            "Work Package, Activity, and Date for a project or date range."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "spent_on_from": {"type": "string", "description": "Optional start date (YYYY-MM-DD)."},
            "spent_on_to": {"type": "string", "description": "Optional end date (YYYY-MM-DD)."},
        },
        domain="time_budgets",
        read_only=True,
        idempotent=True,
    )
    def op_summarize_time_report(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        filters: List[Dict[str, Any]] = []
        if proj_id:
            client.guard_read_project(proj_id)
            filters.append({"project": {"operator": "=", "values": [str(proj_id)]}})
        if args.get("spent_on_from") and args.get("spent_on_to"):
            filters.append(
                {"spentOn": {"operator": "<>d", "values": [args["spent_on_from"], args["spent_on_to"]]}}
            )

        params = {"filters": json.dumps(filters)} if filters else {}
        elements, _ = client.fetch_all_elements("/api/v3/time_entries", params=params, max_items=500)
        entries = [normalize_time_entry(e, sanitize=False) for e in elements]

        by_user: Dict[str, float] = defaultdict(float)
        by_wp: Dict[str, float] = defaultdict(float)
        by_activity: Dict[str, float] = defaultdict(float)
        total_hours = 0.0

        for e in entries:
            h = float(e.get("hours") or 0.0)
            total_hours += h
            u_name = (e.get("user") or {}).get("name") or "Unknown"
            wp_info = e.get("workPackage") or {}
            wp_label = f"#{wp_info.get('id')} {wp_info.get('subject')}" if wp_info.get("id") else "Unlinked"
            act_name = (e.get("activity") or {}).get("name") or "Unspecified"
            by_user[u_name] = round(by_user[u_name] + h, 2)
            by_wp[wp_label] = round(by_wp[wp_label] + h, 2)
            by_activity[act_name] = round(by_activity[act_name] + h, 2)

        return {
            "projectId": proj_id,
            "entryCount": len(entries),
            "totalHours": round(total_hours, 2),
            "hoursByUser": dict(sorted(by_user.items(), key=lambda x: x[1], reverse=True)),
            "hoursByActivity": dict(sorted(by_activity.items(), key=lambda x: x[1], reverse=True)),
            "hoursByWorkPackage": dict(sorted(by_wp.items(), key=lambda x: x[1], reverse=True)),
        }

    @registry.register(
        name="op_list_budgets",
        description="List budgets defined in a project (/api/v3/projects/{id}/budgets).",
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID (defaults to OPENPROJECT_PROJECT_ID).",
            },
        },
        domain="time_budgets",
        read_only=True,
        idempotent=True,
    )
    def op_list_budgets(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_read_project(proj_id)
        data = client.get(f"/api/v3/projects/{proj_id}/budgets")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "projectId": proj_id,
            "total": len(elements),
            "budgets": [
                {
                    "id": b.get("id"),
                    "subject": b.get("subject"),
                    "fixedDate": b.get("fixedDate"),
                    "baseAmount": b.get("baseAmount"),
                }
                for b in elements
            ],
        }

    @registry.register(
        name="op_get_budget",
        description="Get details of a single budget by ID (/api/v3/budgets/{id}).",
        properties={
            "budget_id": {"type": "integer", "description": "Budget ID."},
        },
        required=["budget_id"],
        domain="time_budgets",
        read_only=True,
        idempotent=True,
    )
    def op_get_budget(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        b = client.get(f"/api/v3/budgets/{args['budget_id']}")
        desc_obj = b.get("description") or {}
        return {
            "id": b.get("id"),
            "subject": b.get("subject"),
            "fixedDate": b.get("fixedDate"),
            "description": wrap_untrusted_text(
                desc_obj.get("raw") if isinstance(desc_obj, dict) else None,
                sanitize=client.config.sanitize_untrusted_content,
            ),
        }
