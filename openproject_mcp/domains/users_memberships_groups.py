"""
Domain 8: Users, Project Memberships, Groups & Principals Management
(List/Get/Create/Update/Lock/Unlock/Delete Users, List/Create/Update/Delete Memberships & Groups, Principals).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..client import OpenProjectClient
from ..hal_normalizer import extract_id_from_href, normalize_membership, normalize_user
from ..registry import ToolRegistry


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_list_users",
        description=(
            "List and search user accounts in OpenProject (/api/v3/users). "
            "Supports filtering by name keyword, status ('active', 'locked', 'invited', 'registered'), or group_id."
        ),
        properties={
            "name_contains": {"type": "string", "description": "Substring search in user name or login."},
            "status": {
                "type": "string",
                "description": "Filter by status: 'active', 'locked', 'registered', 'invited'.",
            },
            "group_id": {"type": "integer", "description": "Filter users belonging to a specific group ID."},
            "max_items": {"type": "integer", "description": "Max users to return (default 100).", "default": 100},
        },
        domain="users_memberships",
        read_only=True,
        idempotent=True,
    )
    def op_list_users(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if args.get("name_contains"):
            filters.append({"name": {"operator": "~", "values": [str(args["name_contains"])]}})
        if args.get("status"):
            filters.append({"status": {"operator": "=", "values": [str(args["status"])]}})
        if args.get("group_id"):
            filters.append({"group": {"operator": "=", "values": [str(args["group_id"])]}})

        params = {"filters": json.dumps(filters)} if filters else {}
        elements, total = client.fetch_all_elements(
            "/api/v3/users",
            params=params,
            max_items=int(args.get("max_items", 100)),
        )
        return {
            "total": total,
            "returned": len(elements),
            "users": [normalize_user(u) for u in elements],
        }

    @registry.register(
        name="op_get_user",
        description="Get details of a single user by ID or 'me' (/api/v3/users/{id}).",
        properties={
            "user_id": {"type": ["integer", "string"], "description": "User ID or 'me'."},
        },
        required=["user_id"],
        domain="users_memberships",
        read_only=True,
        idempotent=True,
    )
    def op_get_user(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        u = client.get(f"/api/v3/users/{args['user_id']}")
        return normalize_user(u)

    @registry.register(
        name="op_create_user",
        description="Create a new user account in OpenProject (POST /api/v3/users). Requires Admin privileges.",
        properties={
            "login": {"type": "string", "description": "Unique username/login."},
            "first_name": {"type": "string", "description": "First name."},
            "last_name": {"type": "string", "description": "Last name."},
            "email": {"type": "string", "description": "Email address."},
            "password": {"type": "string", "description": "Initial password (min 10 chars typically)."},
            "admin": {"type": "boolean", "description": "Grant system administrator rights (default false)."},
            "status": {
                "type": "string",
                "description": "Account status: 'active' (default) or 'invited'.",
                "default": "active",
            },
            "language": {"type": "string", "description": "ISO language code (e.g. 'en', 'vi').", "default": "en"},
        },
        required=["login", "first_name", "last_name", "email"],
        domain="admin",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_user(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_admin=True)
        payload: Dict[str, Any] = {
            "login": args["login"],
            "firstName": args["first_name"],
            "lastName": args["last_name"],
            "email": args["email"],
            "admin": bool(args.get("admin", False)),
            "status": args.get("status", "active"),
            "language": args.get("language", "en"),
        }
        if args.get("password"):
            payload["password"] = args["password"]
        created = client.post("/api/v3/users", json_body=payload)
        return normalize_user(created)

    @registry.register(
        name="op_update_user",
        description="Update an existing user account (PATCH /api/v3/users/{id}). Requires Admin privileges.",
        properties={
            "user_id": {"type": "integer", "description": "User ID."},
            "login": {"type": "string", "description": "Updated login."},
            "first_name": {"type": "string", "description": "Updated first name."},
            "last_name": {"type": "string", "description": "Updated last name."},
            "email": {"type": "string", "description": "Updated email."},
            "admin": {"type": "boolean", "description": "Updated admin status."},
            "language": {"type": "string", "description": "Updated language code."},
        },
        required=["user_id"],
        domain="admin",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_user(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_admin=True)
        uid = args["user_id"]
        payload: Dict[str, Any] = {}
        for src, dst in (
            ("login", "login"),
            ("first_name", "firstName"),
            ("last_name", "lastName"),
            ("email", "email"),
            ("admin", "admin"),
            ("language", "language"),
        ):
            if src in args and args[src] is not None:
                payload[dst] = args[src]
        updated = client.patch(f"/api/v3/users/{uid}", json_body=payload)
        return normalize_user(updated)

    @registry.register(
        name="op_lock_unlock_user",
        description="Lock or unlock a user account (POST /api/v3/users/{id}/lock or /unlock). Requires Admin privileges.",
        properties={
            "user_id": {"type": "integer", "description": "User ID."},
            "action": {
                "type": "string",
                "enum": ["lock", "unlock"],
                "description": "'lock' to disable login or 'unlock' to re-enable.",
            },
        },
        required=["user_id", "action"],
        domain="admin",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_lock_unlock_user(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_admin=True)
        act = "lock" if args["action"] == "lock" else "unlock"
        res = client.post(f"/api/v3/users/{args['user_id']}/{act}", json_body={})
        return normalize_user(res) if isinstance(res, dict) and res.get("id") else res

    @registry.register(
        name="op_delete_user",
        description="Delete a user account (DELETE /api/v3/users/{id}). Requires Admin and Delete policy.",
        properties={
            "user_id": {"type": "integer", "description": "User ID to delete."},
        },
        required=["user_id"],
        domain="admin",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_user(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True, is_admin=True)
        return client.delete(f"/api/v3/users/{args['user_id']}")

    @registry.register(
        name="op_list_memberships",
        description=(
            "List project memberships (/api/v3/memberships) showing which users/groups belong to a project "
            "and their assigned roles."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Filter by project ID (defaults to OPENPROJECT_PROJECT_ID if set).",
            },
            "principal_id": {"type": "integer", "description": "Optional filter by user or group ID."},
        },
        domain="users_memberships",
        read_only=True,
        idempotent=True,
    )
    def op_list_memberships(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        filters: List[Dict[str, Any]] = []
        if proj_id:
            client.guard_read_project(proj_id)
            filters.append({"project": {"operator": "=", "values": [str(proj_id)]}})
        if args.get("principal_id"):
            filters.append({"principal": {"operator": "=", "values": [str(args["principal_id"])]}})

        params = {"filters": json.dumps(filters)} if filters else {}
        elements, total = client.fetch_all_elements("/api/v3/memberships", params=params, max_items=200)
        return {
            "total": total,
            "memberships": [normalize_membership(m) for m in elements],
        }

    @registry.register(
        name="op_create_membership",
        description=(
            "Add a user or group to a project with one or more roles (POST /api/v3/memberships). "
            "Use op_list_roles to inspect available role IDs."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Target project ID (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "principal_id": {"type": "integer", "description": "User ID or Group ID to add to the project."},
            "principal_type": {
                "type": "string",
                "enum": ["users", "groups"],
                "description": "'users' (default) or 'groups'.",
                "default": "users",
            },
            "role_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "List of Role IDs to grant (e.g. [3, 4]).",
            },
            "notification_message": {
                "type": "string",
                "description": "Optional welcome message sent to the member.",
            },
        },
        required=["principal_id", "role_ids"],
        domain="users_memberships",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_membership(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_write_operation(proj_id)

        p_type = "groups" if args.get("principal_type") == "groups" else "users"
        role_links = [{"href": f"/api/v3/roles/{rid}"} for rid in (args.get("role_ids") or [])]

        payload: Dict[str, Any] = {
            "_links": {
                "project": {"href": f"/api/v3/projects/{proj_id}"},
                "principal": {"href": f"/api/v3/{p_type}/{args['principal_id']}"},
                "roles": role_links,
            },
        }
        if args.get("notification_message"):
            payload["_meta"] = {"notificationMessage": {"raw": str(args["notification_message"])}}

        created = client.post("/api/v3/memberships", json_body=payload)
        return normalize_membership(created)

    @registry.register(
        name="op_update_membership",
        description="Update the roles assigned to an existing project membership (PATCH /api/v3/memberships/{id}).",
        properties={
            "membership_id": {"type": "integer", "description": "Membership ID."},
            "role_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "New list of Role IDs for this member.",
            },
        },
        required=["membership_id", "role_ids"],
        domain="users_memberships",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_membership(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        mid = args["membership_id"]
        role_links = [{"href": f"/api/v3/roles/{rid}"} for rid in (args.get("role_ids") or [])]
        updated = client.patch(f"/api/v3/memberships/{mid}", json_body={"_links": {"roles": role_links}})
        return normalize_membership(updated)

    @registry.register(
        name="op_delete_membership",
        description="Remove a member from a project by membership ID (DELETE /api/v3/memberships/{id}).",
        properties={
            "membership_id": {"type": "integer", "description": "Membership ID to revoke."},
        },
        required=["membership_id"],
        domain="users_memberships",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_membership(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/memberships/{args['membership_id']}")

    @registry.register(
        name="op_list_groups",
        description="List all user groups in OpenProject (/api/v3/groups).",
        properties={},
        domain="users_memberships",
        read_only=True,
        idempotent=True,
    )
    def op_list_groups(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        elements, total = client.fetch_all_elements("/api/v3/groups", max_items=200)
        groups = []
        for g in elements:
            links = g.get("_links") or {}
            members = [
                {"id": extract_id_from_href(m.get("href")), "name": m.get("title")}
                for m in (links.get("members") or [])
                if isinstance(m, dict)
            ]
            groups.append({
                "id": g.get("id"),
                "name": g.get("name"),
                "members": members,
                "createdAt": g.get("createdAt"),
            })
        return {"total": total, "groups": groups}

    @registry.register(
        name="op_create_group",
        description="Create a new user group (POST /api/v3/groups).",
        properties={
            "name": {"type": "string", "description": "Group name."},
            "member_user_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional list of user IDs to include in the group.",
            },
        },
        required=["name"],
        domain="admin",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_group(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_admin=True)
        payload: Dict[str, Any] = {"name": args["name"]}
        if args.get("member_user_ids"):
            payload["_links"] = {
                "members": [{"href": f"/api/v3/users/{uid}"} for uid in args["member_user_ids"]]
            }
        created = client.post("/api/v3/groups", json_body=payload)
        return {"id": created.get("id"), "name": created.get("name")}

    @registry.register(
        name="op_update_group",
        description="Update a user group's name or members list (PATCH /api/v3/groups/{id}).",
        properties={
            "group_id": {"type": "integer", "description": "Group ID."},
            "name": {"type": "string", "description": "Updated group name."},
            "member_user_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Updated list of member user IDs.",
            },
        },
        required=["group_id"],
        domain="admin",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_group(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_admin=True)
        gid = args["group_id"]
        payload: Dict[str, Any] = {}
        if args.get("name"):
            payload["name"] = args["name"]
        if args.get("member_user_ids") is not None:
            payload["_links"] = {
                "members": [{"href": f"/api/v3/users/{uid}"} for uid in args["member_user_ids"]]
            }
        updated = client.patch(f"/api/v3/groups/{gid}", json_body=payload)
        return {"id": updated.get("id"), "name": updated.get("name")}

    @registry.register(
        name="op_delete_group",
        description="Delete a user group by ID (DELETE /api/v3/groups/{id}).",
        properties={
            "group_id": {"type": "integer", "description": "Group ID to delete."},
        },
        required=["group_id"],
        domain="admin",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_group(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True, is_admin=True)
        return client.delete(f"/api/v3/groups/{args['group_id']}")

    @registry.register(
        name="op_list_principals",
        description="List principals (Users, Groups, PlaceholderUsers) (/api/v3/principals).",
        properties={
            "project_id": {"type": ["integer", "string"], "description": "Optional filter by project membership."},
        },
        domain="users_memberships",
        read_only=True,
        idempotent=True,
    )
    def op_list_principals(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if args.get("project_id"):
            filters.append({"member": {"operator": "=", "values": [str(args["project_id"])]}})
        params = {"filters": json.dumps(filters)} if filters else {}
        elements, total = client.fetch_all_elements("/api/v3/principals", params=params, max_items=200)
        return {
            "total": total,
            "principals": [normalize_user(p) for p in elements],
        }

    @registry.register(
        name="op_list_placeholder_users",
        description=(
            "List Placeholder Users (/api/v3/placeholder_users) used for capacity and resource "
            "planning before assigning concrete team members."
        ),
        properties={},
        domain="users_memberships",
        read_only=True,
        idempotent=True,
    )
    def op_list_placeholder_users(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        elements, total = client.fetch_all_elements("/api/v3/placeholder_users", max_items=200)
        return {
            "total": total,
            "placeholderUsers": [
                {"id": p.get("id"), "name": p.get("name"), "createdAt": p.get("createdAt")}
                for p in elements
            ],
        }

    @registry.register(
        name="op_create_placeholder_user",
        description="Create a new Placeholder User (POST /api/v3/placeholder_users).",
        properties={
            "name": {"type": "string", "description": "Display name of the placeholder user (e.g. 'QA Engineer #2')."},
        },
        required=["name"],
        domain="admin",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_placeholder_user(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_admin=True)
        created = client.post("/api/v3/placeholder_users", json_body={"name": args["name"]})
        return {"id": created.get("id"), "name": created.get("name")}

    @registry.register(
        name="op_delete_placeholder_user",
        description="Delete a Placeholder User by ID (DELETE /api/v3/placeholder_users/{id}).",
        properties={
            "placeholder_user_id": {"type": "integer", "description": "Placeholder user ID to delete."},
        },
        required=["placeholder_user_id"],
        domain="admin",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_placeholder_user(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True, is_admin=True)
        return client.delete(f"/api/v3/placeholder_users/{args['placeholder_user_id']}")

