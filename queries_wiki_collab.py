"""
Domain 9: Saved Queries (Gantt/Board/Table Views), Wiki Pages, News, Documents, Meetings & Notifications
(Full Collaborative & View Management Suite).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..client import OpenProjectClient
from ..hal_normalizer import (
    extract_link_id,
    extract_link_title,
    normalize_work_package,
    wrap_untrusted_text,
)
from ..registry import ToolRegistry


def register_tools(registry: ToolRegistry) -> None:

    # ------------------------------------------------------------------
    # Saved Queries (Gantt, Boards, Filtered Views)
    # ------------------------------------------------------------------

    @registry.register(
        name="op_list_queries",
        description="List saved Queries / Views (Gantt charts, task tables, filtered views) (/api/v3/queries).",
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Optional project ID filter.",
            },
        },
        domain="queries_collab",
        read_only=True,
        idempotent=True,
    )
    def op_list_queries(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id")
        filters: List[Dict[str, Any]] = []
        if proj_id:
            client.guard_read_project(proj_id)
            filters.append({"project": {"operator": "=", "values": [str(proj_id)]}})

        params = {"filters": json.dumps(filters)} if filters else {}
        elements, total = client.fetch_all_elements("/api/v3/queries", params=params, max_items=100)
        queries = []
        for q in elements:
            links = q.get("_links") or {}
            queries.append({
                "id": q.get("id"),
                "name": q.get("name"),
                "public": q.get("public"),
                "starred": q.get("starred"),
                "timelineVisible": q.get("timelineVisible"),
                "showHierarchies": q.get("showHierarchies"),
                "project": {
                    "id": extract_link_id(links, "project"),
                    "name": extract_link_title(links, "project"),
                } if extract_link_id(links, "project") else None,
            })
        return {"total": total, "queries": queries}

    @registry.register(
        name="op_get_query",
        description="Get details and embedded work package results of a saved Query by ID (/api/v3/queries/{id}).",
        properties={
            "query_id": {"type": "integer", "description": "Query ID."},
        },
        required=["query_id"],
        domain="queries_collab",
        read_only=True,
        idempotent=True,
    )
    def op_get_query(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        q = client.get(f"/api/v3/queries/{args['query_id']}")
        results_emb = ((q.get("_embedded") or {}).get("results") or {}).get("_embedded") or {}
        elements = results_emb.get("elements") or []
        return {
            "id": q.get("id"),
            "name": q.get("name"),
            "public": q.get("public"),
            "starred": q.get("starred"),
            "timelineVisible": q.get("timelineVisible"),
            "showHierarchies": q.get("showHierarchies"),
            "filters": q.get("filters"),
            "resultsCount": len(elements),
            "results": [
                normalize_work_package(w, sanitize=client.config.sanitize_untrusted_content, include_description=False)
                for w in elements[:100]
            ],
        }

    @registry.register(
        name="op_create_query",
        description=(
            "Create a new saved Query view (e.g. a Gantt Chart view with timelineVisible=true "
            "or a hierarchical WBS table view) (POST /api/v3/queries)."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "name": {"type": "string", "description": "Name of the saved view (e.g. 'Master Gantt Schedule')."},
            "public": {"type": "boolean", "description": "Make view visible to all project members (default true).", "default": True},
            "starred": {"type": "boolean", "description": "Pin view to left sidebar menu (default true).", "default": True},
            "timeline_visible": {
                "type": "boolean",
                "description": "Enable Gantt timeline split-view (default true).",
                "default": True,
            },
            "show_hierarchies": {
                "type": "boolean",
                "description": "Display parent-child WBS hierarchy tree (default true).",
                "default": True,
            },
        },
        required=["name"],
        domain="queries_collab",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_query(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        client.guard_write_operation(proj_id)
        payload: Dict[str, Any] = {
            "name": args["name"],
            "public": bool(args.get("public", True)),
            "starred": bool(args.get("starred", True)),
            "timelineVisible": bool(args.get("timeline_visible", True)),
            "showHierarchies": bool(args.get("show_hierarchies", True)),
        }
        if proj_id:
            payload["_links"] = {"project": {"href": f"/api/v3/projects/{proj_id}"}}

        created = client.post("/api/v3/queries", json_body=payload)
        return {
            "id": created.get("id"),
            "name": created.get("name"),
            "public": created.get("public"),
            "starred": created.get("starred"),
            "timelineVisible": created.get("timelineVisible"),
            "showHierarchies": created.get("showHierarchies"),
        }

    @registry.register(
        name="op_delete_query",
        description="Delete a saved Query view by ID (DELETE /api/v3/queries/{id}).",
        properties={
            "query_id": {"type": "integer", "description": "Query ID to delete."},
        },
        required=["query_id"],
        domain="queries_collab",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_query(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/queries/{args['query_id']}")

    # ------------------------------------------------------------------
    # Wiki Pages, News, Documents, Meetings
    # ------------------------------------------------------------------

    @registry.register(
        name="op_get_wiki_page",
        description="Retrieve a Wiki page by ID (/api/v3/wiki_pages/{id}).",
        properties={
            "wiki_page_id": {"type": "integer", "description": "Wiki page ID."},
        },
        required=["wiki_page_id"],
        domain="queries_collab",
        read_only=True,
        idempotent=True,
    )
    def op_get_wiki_page(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp = client.get(f"/api/v3/wiki_pages/{args['wiki_page_id']}")
        links = wp.get("_links") or {}
        return {
            "id": wp.get("id"),
            "title": wp.get("title"),
            "project": {
                "id": extract_link_id(links, "project"),
                "name": extract_link_title(links, "project"),
            },
        }

    @registry.register(
        name="op_list_news",
        description="List news announcements across OpenProject or for a project (/api/v3/news).",
        properties={
            "project_id": {"type": ["integer", "string"], "description": "Optional project ID filter."},
            "max_items": {"type": "integer", "description": "Max items (default 50).", "default": 50},
        },
        domain="queries_collab",
        read_only=True,
        idempotent=True,
    )
    def op_list_news(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if args.get("project_id"):
            client.guard_read_project(args["project_id"])
            filters.append({"project_id": {"operator": "=", "values": [str(args["project_id"])]}})
        params = {"filters": json.dumps(filters)} if filters else {}
        elements, total = client.fetch_all_elements(
            "/api/v3/news",
            params=params,
            max_items=int(args.get("max_items", 50)),
        )
        news_list = []
        for n in elements:
            links = n.get("_links") or {}
            desc_obj = n.get("description") or {}
            news_list.append({
                "id": n.get("id"),
                "title": n.get("title"),
                "summary": n.get("summary"),
                "description": wrap_untrusted_text(
                    desc_obj.get("raw") if isinstance(desc_obj, dict) else None,
                    sanitize=client.config.sanitize_untrusted_content,
                ),
                "project": {
                    "id": extract_link_id(links, "project"),
                    "name": extract_link_title(links, "project"),
                },
                "author": {
                    "id": extract_link_id(links, "author"),
                    "name": extract_link_title(links, "author"),
                },
                "createdAt": n.get("createdAt"),
            })
        return {"total": total, "news": news_list}

    @registry.register(
        name="op_create_news",
        description="Create a project news announcement (POST /api/v3/news).",
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "title": {"type": "string", "description": "News headline."},
            "summary": {"type": "string", "description": "Short summary teaser."},
            "description": {"type": "string", "description": "Full Markdown body of the announcement."},
        },
        required=["title"],
        domain="queries_collab",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_news(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_write_operation(proj_id)
        payload = {
            "title": args["title"],
            "summary": str(args.get("summary") or ""),
            "description": {"raw": str(args.get("description") or "")},
            "_links": {
                "project": {"href": f"/api/v3/projects/{proj_id}"},
            },
        }
        created = client.post("/api/v3/news", json_body=payload)
        return {
            "id": created.get("id"),
            "title": created.get("title"),
            "summary": created.get("summary"),
            "createdAt": created.get("createdAt"),
        }

    @registry.register(
        name="op_delete_news",
        description="Delete a news entry by ID (DELETE /api/v3/news/{id}).",
        properties={
            "news_id": {"type": "integer", "description": "News ID to delete."},
        },
        required=["news_id"],
        domain="queries_collab",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_news(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/news/{args['news_id']}")

    @registry.register(
        name="op_list_documents",
        description="List documents in OpenProject (/api/v3/documents).",
        properties={
            "max_items": {"type": "integer", "description": "Max documents (default 50).", "default": 50},
        },
        domain="queries_collab",
        read_only=True,
        idempotent=True,
    )
    def op_list_documents(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        elements, total = client.fetch_all_elements(
            "/api/v3/documents",
            max_items=int(args.get("max_items", 50)),
        )
        docs = []
        for d in elements:
            desc_obj = d.get("description") or {}
            docs.append({
                "id": d.get("id"),
                "title": d.get("title"),
                "description": wrap_untrusted_text(
                    desc_obj.get("raw") if isinstance(desc_obj, dict) else None,
                    sanitize=client.config.sanitize_untrusted_content,
                ),
                "createdAt": d.get("createdAt"),
            })
        return {"total": total, "documents": docs}

    @registry.register(
        name="op_list_meetings",
        description="List meetings in OpenProject (/api/v3/meetings).",
        properties={
            "project_id": {"type": ["integer", "string"], "description": "Optional project ID filter."},
        },
        domain="queries_collab",
        read_only=True,
        idempotent=True,
    )
    def op_list_meetings(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        elements, total = client.fetch_all_elements("/api/v3/meetings", max_items=100)
        return {
            "total": total,
            "meetings": [
                {
                    "id": m.get("id"),
                    "title": m.get("title"),
                    "startTime": m.get("startTime"),
                    "duration": m.get("duration"),
                    "location": m.get("location"),
                }
                for m in elements
            ],
        }

    # ------------------------------------------------------------------
    # In-App Notifications
    # ------------------------------------------------------------------

    @registry.register(
        name="op_list_notifications",
        description="List in-app notifications for the current authenticated user (/api/v3/notifications).",
        properties={
            "unread_only": {
                "type": "boolean",
                "description": "If true, only return unread notifications (default true).",
                "default": True,
            },
            "max_items": {"type": "integer", "description": "Max items (default 50).", "default": 50},
        },
        domain="queries_collab",
        read_only=True,
        idempotent=True,
    )
    def op_list_notifications(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if args.get("unread_only", True):
            filters.append({"readIAN": {"operator": "=", "values": ["f"]}})
        params = {"filters": json.dumps(filters)} if filters else {}
        elements, total = client.fetch_all_elements(
            "/api/v3/notifications",
            params=params,
            max_items=int(args.get("max_items", 50)),
        )
        notifs = []
        for n in elements:
            links = n.get("_links") or {}
            notifs.append({
                "id": n.get("id"),
                "reason": n.get("reason"),
                "readIAN": n.get("readIAN"),
                "resource": {
                    "id": extract_link_id(links, "resource"),
                    "title": extract_link_title(links, "resource"),
                },
                "actor": {
                    "id": extract_link_id(links, "actor"),
                    "name": extract_link_title(links, "actor"),
                },
                "project": {
                    "id": extract_link_id(links, "project"),
                    "name": extract_link_title(links, "project"),
                },
                "createdAt": n.get("createdAt"),
            })
        return {"total": total, "notifications": notifs}

    @registry.register(
        name="op_mark_notification_read",
        description=(
            "Mark a specific notification as read (/api/v3/notifications/{id}/read_ian) "
            "or mark ALL notifications as read when notification_id is omitted (/api/v3/notifications/read_ian)."
        ),
        properties={
            "notification_id": {
                "type": "integer",
                "description": "Optional notification ID; omit to mark all unread notifications as read.",
            },
        },
        domain="queries_collab",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_mark_notification_read(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        nid = args.get("notification_id")
        if nid:
            return client.post(f"/api/v3/notifications/{nid}/read_ian", json_body={})
        return client.post("/api/v3/notifications/read_ian", json_body={})

    @registry.register(
        name="op_update_query",
        description="Update a saved Query view (name, public, starred, timeline_visible, show_hierarchies) (PATCH /api/v3/queries/{id}).",
        properties={
            "query_id": {"type": "integer", "description": "Query ID to update."},
            "name": {"type": "string", "description": "Updated query view name."},
            "public": {"type": "boolean", "description": "Updated public visibility."},
            "starred": {"type": "boolean", "description": "Pin/unpin view in sidebar."},
            "timeline_visible": {"type": "boolean", "description": "Toggle Gantt timeline view."},
            "show_hierarchies": {"type": "boolean", "description": "Toggle WBS hierarchy tree mode."},
        },
        required=["query_id"],
        domain="queries_collab",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_query(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        qid = args["query_id"]
        payload: Dict[str, Any] = {}
        for src, dst in (
            ("name", "name"),
            ("public", "public"),
            ("starred", "starred"),
            ("timeline_visible", "timelineVisible"),
            ("show_hierarchies", "showHierarchies"),
        ):
            if src in args and args[src] is not None:
                payload[dst] = args[src]
        updated = client.patch(f"/api/v3/queries/{qid}", json_body=payload)
        return {
            "id": updated.get("id"),
            "name": updated.get("name"),
            "public": updated.get("public"),
            "starred": updated.get("starred"),
            "timelineVisible": updated.get("timelineVisible"),
            "showHierarchies": updated.get("showHierarchies"),
        }

    @registry.register(
        name="op_update_news",
        description="Update an existing News announcement (PATCH /api/v3/news/{id}).",
        properties={
            "news_id": {"type": "integer", "description": "News ID."},
            "title": {"type": "string", "description": "Updated headline."},
            "summary": {"type": "string", "description": "Updated summary."},
            "description": {"type": "string", "description": "Updated Markdown body."},
        },
        required=["news_id"],
        domain="queries_collab",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_news(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        nid = args["news_id"]
        payload: Dict[str, Any] = {}
        if args.get("title") is not None:
            payload["title"] = args["title"]
        if args.get("summary") is not None:
            payload["summary"] = args["summary"]
        if args.get("description") is not None:
            payload["description"] = {"raw": str(args["description"])}
        updated = client.patch(f"/api/v3/news/{nid}", json_body=payload)
        return {"id": updated.get("id"), "title": updated.get("title")}

    @registry.register(
        name="op_list_grids",
        description="List dashboard Grids (Project Overview widgets, My Page layouts) (/api/v3/grids).",
        properties={
            "scope": {"type": "string", "description": "Optional page scope URI filter."},
        },
        domain="queries_collab",
        read_only=True,
        idempotent=True,
    )
    def op_list_grids(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if args.get("scope"):
            filters.append({"scope": {"operator": "=", "values": [str(args["scope"])]}})
        params = {"filters": json.dumps(filters)} if filters else {}
        elements, total = client.fetch_all_elements("/api/v3/grids", params=params, max_items=50)
        return {
            "total": total,
            "grids": [
                {
                    "id": g.get("id"),
                    "rowCount": g.get("rowCount"),
                    "columnCount": g.get("columnCount"),
                    "widgetsCount": len(g.get("widgets") or []),
                }
                for g in elements
            ],
        }

