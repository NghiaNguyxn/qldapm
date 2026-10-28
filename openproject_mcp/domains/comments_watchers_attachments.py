"""
Domain 6: Comments / Activities, Watchers & Attachments Management
(List/Add/Edit Comments, List/Add/Remove Watchers, List/Upload/Delete Attachments).
"""

from __future__ import annotations

from typing import Any, Dict, List

from ..client import OpenProjectClient
from ..hal_normalizer import (
    extract_link_id,
    extract_link_title,
    normalize_activity,
    normalize_user,
    wrap_untrusted_text,
)
from ..registry import ToolRegistry


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_list_work_package_activities",
        description=(
            "List activity journal entries and comments on a work package "
            "(/api/v3/work_packages/{id}/activities)."
        ),
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
            "comments_only": {
                "type": "boolean",
                "description": "If true, only return entries that contain user comments (default false).",
                "default": False,
            },
        },
        required=["work_package_id"],
        domain="collaboration",
        read_only=True,
        idempotent=True,
    )
    def op_list_work_package_activities(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args["work_package_id"]
        data = client.get(f"/api/v3/work_packages/{wp_id}/activities")
        elements = (data.get("_embedded") or {}).get("elements") or []
        activities = [
            normalize_activity(a, sanitize=client.config.sanitize_untrusted_content)
            for a in elements
        ]
        if args.get("comments_only"):
            activities = [a for a in activities if a.get("comment")]
        return {
            "workPackageId": wp_id,
            "total": len(activities),
            "activities": activities,
        }

    @registry.register(
        name="op_add_work_package_comment",
        description="Post a new Markdown comment on a work package (POST /api/v3/work_packages/{id}/activities).",
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
            "comment": {"type": "string", "description": "Markdown comment text."},
            "internal": {
                "type": "boolean",
                "description": "Mark comment as internal/private (if supported by instance, default false).",
                "default": False,
            },
            "notify": {
                "type": "boolean",
                "description": "Send email notification to watchers/assignees (default false).",
                "default": False,
            },
        },
        required=["work_package_id", "comment"],
        domain="collaboration",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_add_work_package_comment(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        wp_id = args["work_package_id"]
        payload: Dict[str, Any] = {
            "comment": {"raw": str(args["comment"])},
        }
        if args.get("internal"):
            payload["internal"] = True

        notify = "true" if args.get("notify", False) else "false"
        created = client.post(
            f"/api/v3/work_packages/{wp_id}/activities",
            json_body=payload,
            params={"notify": notify},
        )
        return normalize_activity(created, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_update_comment",
        description="Edit an existing activity comment by activity ID (PATCH /api/v3/activities/{id}).",
        properties={
            "activity_id": {"type": "integer", "description": "Activity journal entry ID."},
            "comment": {"type": "string", "description": "Updated Markdown comment text."},
        },
        required=["activity_id", "comment"],
        domain="collaboration",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_comment(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        act_id = args["activity_id"]
        updated = client.patch(
            f"/api/v3/activities/{act_id}",
            json_body={"comment": {"raw": str(args["comment"])}},
        )
        return normalize_activity(updated, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_list_watchers",
        description="List users watching a work package (/api/v3/work_packages/{id}/watchers).",
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
        },
        required=["work_package_id"],
        domain="collaboration",
        read_only=True,
        idempotent=True,
    )
    def op_list_watchers(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args["work_package_id"]
        data = client.get(f"/api/v3/work_packages/{wp_id}/watchers")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "workPackageId": wp_id,
            "total": len(elements),
            "watchers": [normalize_user(u) for u in elements],
        }

    @registry.register(
        name="op_add_watcher",
        description="Add a user as a watcher to a work package (POST /api/v3/work_packages/{id}/watchers).",
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
            "user_id": {"type": "integer", "description": "User ID to add as watcher."},
        },
        required=["work_package_id", "user_id"],
        domain="collaboration",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_add_watcher(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        wp_id = args["work_package_id"]
        uid = args["user_id"]
        added = client.post(
            f"/api/v3/work_packages/{wp_id}/watchers",
            json_body={"user": {"href": f"/api/v3/users/{uid}"}},
        )
        return normalize_user(added)

    @registry.register(
        name="op_remove_watcher",
        description="Remove a user from watching a work package (DELETE /api/v3/work_packages/{id}/watchers/{user_id}).",
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
            "user_id": {"type": "integer", "description": "User ID to remove."},
        },
        required=["work_package_id", "user_id"],
        domain="collaboration",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_remove_watcher(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        return client.delete(f"/api/v3/work_packages/{args['work_package_id']}/watchers/{args['user_id']}")

    @registry.register(
        name="op_list_attachments",
        description="List file attachments on a work package (/api/v3/work_packages/{id}/attachments).",
        properties={
            "work_package_id": {"type": "integer", "description": "Work package ID."},
        },
        required=["work_package_id"],
        domain="collaboration",
        read_only=True,
        idempotent=True,
    )
    def op_list_attachments(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args["work_package_id"]
        data = client.get(f"/api/v3/work_packages/{wp_id}/attachments")
        elements = (data.get("_embedded") or {}).get("elements") or []
        attachments = []
        for att in elements:
            links = att.get("_links") or {}
            desc_obj = att.get("description") or {}
            attachments.append({
                "id": att.get("id"),
                "fileName": att.get("fileName"),
                "fileSize": att.get("fileSize"),
                "contentType": att.get("contentType"),
                "description": wrap_untrusted_text(
                    desc_obj.get("raw") if isinstance(desc_obj, dict) else None,
                    sanitize=client.config.sanitize_untrusted_content,
                ),
                "author": {
                    "id": extract_link_id(links, "author"),
                    "name": extract_link_title(links, "author"),
                },
                "downloadHref": (links.get("downloadLocation") or {}).get("href"),
                "createdAt": att.get("createdAt"),
            })
        return {
            "workPackageId": wp_id,
            "total": len(attachments),
            "attachments": attachments,
        }

    @registry.register(
        name="op_upload_attachment",
        description="Upload a local file as an attachment to a work package (POST /api/v3/work_packages/{id}/attachments).",
        properties={
            "work_package_id": {"type": "integer", "description": "Target work package ID."},
            "file_path": {"type": "string", "description": "Absolute or relative local file path to upload."},
            "description": {"type": "string", "description": "Optional attachment description."},
            "custom_file_name": {"type": "string", "description": "Optional override file name."},
        },
        required=["work_package_id", "file_path"],
        domain="collaboration",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_upload_attachment(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        wp_id = args["work_package_id"]
        res = client.upload_attachment_file(
            container_path=f"/api/v3/work_packages/{wp_id}/attachments",
            file_path=args["file_path"],
            description=str(args.get("description") or ""),
            custom_file_name=args.get("custom_file_name"),
        )
        return {
            "id": res.get("id"),
            "fileName": res.get("fileName"),
            "fileSize": res.get("fileSize"),
            "contentType": res.get("contentType"),
            "createdAt": res.get("createdAt"),
        }

    @registry.register(
        name="op_delete_attachment",
        description="Delete a file attachment by ID (DELETE /api/v3/attachments/{id}).",
        properties={
            "attachment_id": {"type": "integer", "description": "Attachment ID to delete."},
        },
        required=["attachment_id"],
        domain="collaboration",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_attachment(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/attachments/{args['attachment_id']}")
