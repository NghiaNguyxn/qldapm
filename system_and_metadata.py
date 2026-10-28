"""
Domain 1: System Diagnostics, Root Configuration, Current User, and Reference Metadata
(Statuses, Types, Priorities, Time Entry Activities, Roles, Schemas, Custom Options).
"""

from __future__ import annotations

import time
from typing import Any, Dict, List

from ..client import OpenProjectAPIError, OpenProjectClient
from ..hal_normalizer import extract_id_from_href, normalize_user
from ..registry import ToolRegistry


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_doctor_check",
        description=(
            "Run end-to-end diagnostics on the OpenProject connection, API v3 authentication, "
            "user identity, server version, active security policies, and network latency."
        ),
        properties={},
        domain="system",
        read_only=True,
        idempotent=True,
    )
    def op_doctor_check(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        t0 = time.perf_counter()
        root = client.get("/api/v3")
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)

        me = client.get("/api/v3/users/me")
        statuses = client.get_cached("statuses", "/api/v3/statuses")
        types = client.get_cached("types:global", "/api/v3/types")

        return {
            "healthy": True,
            "latencyMs": latency_ms,
            "instanceName": root.get("instanceName"),
            "coreVersion": root.get("coreVersion"),
            "baseUrl": client.config.base_url,
            "authenticatedUser": normalize_user(me),
            "securityPolicies": {
                "readOnly": client.config.read_only,
                "enableDeleteTools": client.config.enable_delete_tools,
                "enableAdminTools": client.config.enable_admin_tools,
                "sanitizeUntrustedContent": client.config.sanitize_untrusted_content,
                "readProjectsAllowlist": client.config.read_projects_allowlist,
                "writeProjectsAllowlist": client.config.write_projects_allowlist,
                "defaultProjectId": client.config.default_project_id,
            },
            "metadataCounts": {
                "statuses": statuses.get("total", 0),
                "types": types.get("total", 0),
            },
        }

    @registry.register(
        name="op_get_instance_configuration",
        description=(
            "Retrieve OpenProject root capabilities (/api/v3) and system configuration "
            "(/api/v3/configuration) such as hoursPerDay, daysPerWeek, dateFormat, and maximumAttachmentFileSize."
        ),
        properties={},
        domain="system",
        read_only=True,
        idempotent=True,
    )
    def op_get_instance_configuration(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        root = client.get("/api/v3")
        try:
            cfg = client.get("/api/v3/configuration")
        except OpenProjectAPIError:
            cfg = {}
        return {
            "instanceName": root.get("instanceName"),
            "coreVersion": root.get("coreVersion"),
            "hoursPerDay": cfg.get("hoursPerDay"),
            "daysPerWeek": cfg.get("daysPerWeek"),
            "maximumAttachmentFileSize": cfg.get("maximumAttachmentFileSize"),
            "hostName": cfg.get("hostName"),
            "activeFeatureFlags": cfg.get("activeFeatureFlags"),
        }

    @registry.register(
        name="op_get_current_user",
        description="Get profile and permissions of the currently authenticated OpenProject user (/api/v3/users/me).",
        properties={},
        domain="system",
        read_only=True,
        idempotent=True,
    )
    def op_get_current_user(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        me = client.get("/api/v3/users/me")
        return normalize_user(me)

    @registry.register(
        name="op_list_statuses",
        description="List all work package workflow statuses (ID, name, isClosed, isDefault, defaultDoneRatio).",
        properties={},
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_list_statuses(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        data = client.get_cached("statuses", "/api/v3/statuses")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "total": len(elements),
            "statuses": [
                {
                    "id": s.get("id"),
                    "name": s.get("name"),
                    "isClosed": s.get("isClosed"),
                    "isDefault": s.get("isDefault"),
                    "isReadonly": s.get("isReadonly"),
                    "defaultDoneRatio": s.get("defaultDoneRatio"),
                    "color": s.get("color"),
                    "position": s.get("position"),
                }
                for s in elements
            ],
        }

    @registry.register(
        name="op_get_status",
        description="Get details of a single work package status by ID (/api/v3/statuses/{id}).",
        properties={
            "status_id": {"type": "integer", "description": "ID of the status."},
        },
        required=["status_id"],
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_get_status(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        s = client.get(f"/api/v3/statuses/{args['status_id']}")
        return {
            "id": s.get("id"),
            "name": s.get("name"),
            "isClosed": s.get("isClosed"),
            "isDefault": s.get("isDefault"),
            "defaultDoneRatio": s.get("defaultDoneRatio"),
            "color": s.get("color"),
        }

    @registry.register(
        name="op_list_types",
        description=(
            "List work package types (e.g. Task, Milestone, Phase, Feature, Epic, Bug, User story). "
            "Optionally scoped to a specific project_id."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Optional project ID or identifier to list only types enabled in that project.",
            },
        },
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_list_types(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        project_id = args.get("project_id")
        if project_id:
            client.guard_read_project(project_id)
            data = client.get_cached(f"types:{project_id}", f"/api/v3/projects/{project_id}/types")
        else:
            data = client.get_cached("types:global", "/api/v3/types")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "total": len(elements),
            "types": [
                {
                    "id": t.get("id"),
                    "name": t.get("name"),
                    "color": t.get("color"),
                    "isDefault": t.get("isDefault"),
                    "isMilestone": t.get("isMilestone"),
                    "position": t.get("position"),
                }
                for t in elements
            ],
        }

    @registry.register(
        name="op_get_type",
        description="Get details of a single work package type by ID (/api/v3/types/{id}).",
        properties={
            "type_id": {"type": "integer", "description": "ID of the work package type."},
        },
        required=["type_id"],
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_get_type(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        t = client.get(f"/api/v3/types/{args['type_id']}")
        return {
            "id": t.get("id"),
            "name": t.get("name"),
            "color": t.get("color"),
            "isDefault": t.get("isDefault"),
            "isMilestone": t.get("isMilestone"),
            "position": t.get("position"),
        }

    @registry.register(
        name="op_list_priorities",
        description="List all work package priorities (e.g. Low, Normal, High, Immediate) (/api/v3/priorities).",
        properties={},
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_list_priorities(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        data = client.get_cached("priorities", "/api/v3/priorities")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "total": len(elements),
            "priorities": [
                {
                    "id": p.get("id"),
                    "name": p.get("name"),
                    "isDefault": p.get("isDefault"),
                    "isActive": p.get("isActive"),
                    "position": p.get("position"),
                }
                for p in elements
            ],
        }

    @registry.register(
        name="op_list_time_entry_activities",
        description="List available time tracking activity categories (e.g. Development, Management, Testing, Support).",
        properties={},
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_list_time_entry_activities(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            data = client.get_cached("time_entry_activities", "/api/v3/time_entry_activities")
            elements = (data.get("_embedded") or {}).get("elements") or []
        except OpenProjectAPIError:
            # Some OpenProject versions expose activities via time_entries/form
            form = client.post("/api/v3/time_entries/form", json_body={})
            schema = (form.get("_embedded") or {}).get("schema") or {}
            act_schema = schema.get("activity") or {}
            elements = ((act_schema.get("_embedded") or {}).get("allowedValues")) or []

        return {
            "total": len(elements),
            "activities": [
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "default": a.get("default"),
                    "position": a.get("position"),
                }
                for a in elements
            ],
        }

    @registry.register(
        name="op_list_roles",
        description="List all roles configured in OpenProject (/api/v3/roles).",
        properties={},
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_list_roles(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        data = client.get_cached("roles", "/api/v3/roles")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "total": len(elements),
            "roles": [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                }
                for r in elements
            ],
        }

    @registry.register(
        name="op_get_work_package_schema",
        description=(
            "Inspect the exact WorkPackage Schema for a specific (project_id, type_id) combination "
            "(/api/v3/work_packages/schemas/{project_id}-{type_id}), including writable properties and customFields."
        ),
        properties={
            "project_id": {"type": ["integer", "string"], "description": "Project ID."},
            "type_id": {"type": ["integer", "string"], "description": "Work package Type ID or name."},
        },
        required=["project_id", "type_id"],
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_get_work_package_schema(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args["project_id"]
        client.guard_read_project(proj_id)
        t_id = client.resolve_type_id(args["type_id"], project_id=proj_id)
        schema = client.get(f"/api/v3/work_packages/schemas/{proj_id}-{t_id}")
        fields_summary: Dict[str, Any] = {}
        for key, val in schema.items():
            if key.startswith("_") or not isinstance(val, dict):
                continue
            fields_summary[key] = {
                "name": val.get("name"),
                "type": val.get("type"),
                "required": val.get("required"),
                "writable": val.get("writable"),
                "hasDefault": val.get("hasDefault"),
            }
        return {
            "schemaId": f"{proj_id}-{t_id}",
            "fields": fields_summary,
        }

    @registry.register(
        name="op_get_custom_option",
        description="Retrieve a custom field option by ID (/api/v3/custom_options/{id}).",
        properties={
            "custom_option_id": {"type": "integer", "description": "ID of the custom option."},
        },
        required=["custom_option_id"],
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_get_custom_option(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        opt = client.get(f"/api/v3/custom_options/{args['custom_option_id']}")
        return {
            "id": opt.get("id"),
            "value": opt.get("value"),
        }

    @registry.register(
        name="op_list_working_days_and_holidays",
        description=(
            "Retrieve the instance's working week configuration (/api/v3/days/week) "
            "and non-working holidays (/api/v3/days/non_working) used by Gantt auto-scheduling."
        ),
        properties={},
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_list_working_days_and_holidays(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        week_days = []
        non_working = []
        try:
            w_resp = client.get("/api/v3/days/week")
            for d in ((w_resp.get("_embedded") or {}).get("elements") or []):
                week_days.append({
                    "dayOfWeek": d.get("day"),
                    "name": d.get("name"),
                    "working": d.get("working"),
                })
        except Exception:
            pass
        try:
            nw_resp = client.get("/api/v3/days/non_working")
            for nw in ((nw_resp.get("_embedded") or {}).get("elements") or []):
                non_working.append({
                    "date": nw.get("date"),
                    "name": nw.get("name"),
                })
        except Exception:
            pass
        return {
            "weekSchedule": week_days,
            "nonWorkingHolidays": non_working,
        }

    @registry.register(
        name="op_list_help_texts",
        description="List attribute help texts configured in OpenProject (/api/v3/help_texts).",
        properties={},
        domain="metadata",
        read_only=True,
        idempotent=True,
    )
    def op_list_help_texts(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        data = client.get("/api/v3/help_texts")
        elements = (data.get("_embedded") or {}).get("elements") or []
        return {
            "total": len(elements),
            "helpTexts": [
                {
                    "id": h.get("id"),
                    "attribute": h.get("attribute"),
                    "scope": h.get("scope"),
                    "helpText": (h.get("helpText") or {}).get("raw"),
                }
                for h in elements
            ],
        }

    @registry.register(
        name="op_render_markdown",
        description=(
            "Render OpenProject-flavored Markdown (including #work_package_id macros) into HTML "
            "via POST /api/v3/render/markdown."
        ),
        properties={
            "markdown_text": {"type": "string", "description": "Raw Markdown string to render."},
            "context_work_package_id": {
                "type": "integer",
                "description": "Optional context work package ID for resolving relative macros.",
            },
        },
        required=["markdown_text"],
        domain="system",
        read_only=True,
        idempotent=True,
    )
    def op_render_markdown(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        params = {}
        if args.get("context_work_package_id"):
            params["context"] = f"/api/v3/work_packages/{args['context_work_package_id']}"
        res = client.request(
            "POST",
            "/api/v3/render/markdown",
            params=params,
            json_body={"text": args["markdown_text"]},
        )
        return {"rendered": res}

    @registry.register(
        name="op_admin_sync_3tier_schema",
        description=(
            "[ADMIN] Synchronize the 3-Tier Hierarchy Types (Epic, Task, Sub-task), "
            "10 Standard Statuses (READY, In progress, BA in progress, BA Review, Dev in progress, "
            "Ready for test, Testing, Rework, In review, Done), enable them across projects, "
            "and configure the 3-Tier Adaptive Workflow Matrix."
        ),
        properties={
            "admin_username": {
                "type": "string",
                "description": "Admin login username/email for Rails Admin session.",
                "default": "trungnv.ba@stu.ptit.edu.vn",
            },
            "admin_password": {
                "type": "string",
                "description": "Admin login password for Rails Admin session.",
                "default": "Ptit@2026!StrongPassword",
            },
        },
        domain="system",
        read_only=False,
        idempotent=True,
    )
    def op_admin_sync_3tier_schema(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        import re
        import httpx

        client.guard_write_operation(is_admin=True)
        base = client.config.base_url
        admin_user = str(args.get("admin_username") or "trungnv.ba@stu.ptit.edu.vn")
        admin_pass = str(args.get("admin_password") or "Ptit@2026!StrongPassword")

        with httpx.Client(follow_redirects=True, timeout=30.0) as sess:
            login_html = sess.get(f"{base}/login").text
            m_csrf = re.search(r'name="authenticity_token" value="([^"]+)"', login_html)
            if not m_csrf:
                raise RuntimeError("Could not extract CSRF token from /login.")
            sess.post(
                f"{base}/login",
                data={
                    "authenticity_token": m_csrf.group(1),
                    "username": admin_user,
                    "password": admin_pass,
                },
            )

            def _csrf(html_text: str) -> str:
                m = re.search(r'name="authenticity_token" value="([^"]+)"', html_text)
                if not m:
                    m = re.search(r'name="csrf-token" content="([^"]+)"', html_text)
                return m.group(1) if m else ""

            # 1. Rename existing statuses & create missing statuses to match the exact 10 statuses
            existing_statuses = {
                int(s["id"]): s["name"]
                for s in (client.get("/api/v3/statuses").get("_embedded") or {}).get("elements", [])
            }
            rename_statuses = {
                1: ("READY", "0", "0", "1"),
                7: ("In progress", "0", "50", "0"),
                9: ("Testing", "0", "80", "0"),
                10: ("Ready for test", "0", "70", "0"),
                12: ("Done", "1", "100", "0"),
                14: ("Rework", "0", "40", "0"),
            }
            for sid, (sname, is_closed, ratio, is_def) in rename_statuses.items():
                if sid in existing_statuses:
                    ed_html = sess.get(f"{base}/statuses/{sid}/edit").text
                    sess.post(
                        f"{base}/statuses/{sid}",
                        data={
                            "_method": "patch",
                            "authenticity_token": _csrf(ed_html),
                            "status[name]": sname,
                            "status[is_closed]": is_closed,
                            "status[is_default]": is_def,
                            "status[default_done_ratio]": ratio,
                        },
                    )

            client.invalidate_cache()
            fresh_statuses = {
                s["name"].strip().lower(): int(s["id"])
                for s in (client.get("/api/v3/statuses").get("_embedded") or {}).get("elements", [])
            }
            new_statuses_needed = [
                ("Dev in progress", "0", "50"),
                ("BA in progress", "0", "20"),
                ("BA Review", "0", "30"),
                ("In review", "0", "90"),
            ]
            for sname, is_closed, ratio in new_statuses_needed:
                if sname.lower() not in fresh_statuses:
                    new_html = sess.get(f"{base}/statuses/new").text
                    sess.post(
                        f"{base}/statuses",
                        data={
                            "authenticity_token": _csrf(new_html),
                            "status[name]": sname,
                            "status[is_closed]": is_closed,
                            "status[is_default]": "0",
                            "status[default_done_ratio]": ratio,
                        },
                    )

            client.invalidate_cache()
            status_by_name = {
                s["name"].strip(): int(s["id"])
                for s in (client.get("/api/v3/statuses").get("_embedded") or {}).get("elements", [])
            }

            # 2. Rename Task (1), Epic (5), and create Sub-task if missing
            for tid, tname in [(1, "Task"), (5, "Epic")]:
                t_html = sess.get(f"{base}/types/{tid}/settings").text
                sess.post(
                    f"{base}/types/{tid}/details",
                    data={
                        "_method": "patch",
                        "authenticity_token": _csrf(t_html),
                        "type[name]": tname,
                        "type[is_in_roadmap]": "1",
                        "type[is_milestone]": "0",
                        "type[enabled_in_new_projects]": "1",
                    },
                )

            client.invalidate_cache()
            types_by_name = {
                t["name"].strip().lower(): int(t["id"])
                for t in (client.get("/api/v3/types").get("_embedded") or {}).get("elements", [])
            }
            if "sub-task" not in types_by_name and "subtask" not in types_by_name:
                nt_html = sess.get(f"{base}/types/new").text
                sess.post(
                    f"{base}/types",
                    data={
                        "authenticity_token": _csrf(nt_html),
                        "type[name]": "Sub-task",
                        "type[copy_workflow_from]": "1",
                        "type[is_in_roadmap]": "1",
                        "type[is_milestone]": "0",
                        "type[enabled_in_new_projects]": "1",
                    },
                )

            client.invalidate_cache()
            types_map = {
                t["name"].strip(): int(t["id"])
                for t in (client.get("/api/v3/types").get("_embedded") or {}).get("elements", [])
            }

            # 3. Enable Epic, Task, Sub-task across all projects
            for tname in ("Epic", "Task", "Sub-task"):
                tid = types_map.get(tname)
                if tid:
                    p_html = sess.get(f"{base}/types/{tid}/projects/edit").text
                    sess.post(
                        f"{base}/types/{tid}/projects/enable_all?value=1",
                        headers={"X-CSRF-Token": _csrf(p_html)},
                        data={"authenticity_token": _csrf(p_html)},
                    )

            # 4. Configure 3-Tier Workflow Matrix for Epic, Task, Sub-task across Roles (3, 5, 6, 11)
            st = status_by_name
            s_ready = st.get("READY", 1)
            s_inprog = st.get("In progress", 7)
            s_bainprog = st.get("BA in progress")
            s_bareview = st.get("BA Review")
            s_devinprog = st.get("Dev in progress")
            s_readytest = st.get("Ready for test", 10)
            s_testing = st.get("Testing", 9)
            s_rework = st.get("Rework", 14)
            s_inreview = st.get("In review")
            s_done = st.get("Done", 12)

            epic_pairs = [
                (s_ready, s_inprog),
                (s_inprog, s_inreview),
                (s_inreview, s_done),
                (s_inreview, s_inprog),
                (s_done, s_inprog),
            ]
            task_pairs = [
                (s_ready, s_bainprog),
                (s_ready, s_devinprog),
                (s_ready, s_inprog),
                (s_bainprog, s_bareview),
                (s_bareview, s_bainprog),
                (s_bareview, s_devinprog),
                (s_bareview, s_done),
                (s_devinprog, s_readytest),
                (s_readytest, s_testing),
                (s_testing, s_rework),
                (s_rework, s_devinprog),
                (s_testing, s_done),
                (s_done, s_rework),
                (s_inprog, s_done),
            ]
            subtask_pairs = [
                (s_ready, s_inprog),
                (s_inprog, s_done),
                (s_done, s_inprog),
            ]

            for tname, pairs in [("Epic", epic_pairs), ("Task", task_pairs), ("Sub-task", subtask_pairs)]:
                tid = types_map.get(tname)
                if not tid:
                    continue
                wf_html = sess.get(f"{base}/types/{tid}/workflow/edit?role_id=3").text
                token = _csrf(wf_html)
                form_data: Dict[str, Any] = {
                    "_method": "patch",
                    "authenticity_token": token,
                    "tab": "always",
                    "role_ids[]": ["3", "5", "6", "11"],
                }
                active_ids = {x for p in pairs for x in p if x}
                for sid in active_ids:
                    form_data[f"status[{sid}][{sid}][]"] = ["always"]
                for src, dst in pairs:
                    if src and dst:
                        form_data[f"status[{src}][{dst}][]"] = ["always"]
                sess.post(f"{base}/types/{tid}/workflow/matrix?tab=always", data=form_data)

            client.invalidate_cache()
            return {
                "synchronized": True,
                "types": types_map,
                "statuses": status_by_name,
            }


