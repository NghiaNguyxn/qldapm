"""
Domain 3: Work Packages Management
(List/Filter, Get Full Context, Form Validation, Create, Update with auto-lockVersion,
Delete, Subtasks, Bulk Create WBS Hierarchy, Bulk Update, Custom Actions).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..client import OpenProjectAPIError, OpenProjectClient
from ..config import ROLE_PROFILES
from ..hal_normalizer import (
    build_openproject_filters,
    hours_to_iso_duration,
    normalize_activity,
    normalize_relation,
    normalize_user,
    normalize_work_package,
)
from ..registry import ToolRegistry

_STATUS_ID_TO_KEY: Dict[int, str] = {
    1: "ready",
    3: "ready",
    4: "ready",
    5: "ready",
    6: "ready",
    7: "in progress",
    8: "ready for test",
    9: "testing",
    10: "ready for test",
    11: "rework",
    12: "done",
    13: "ready",
    14: "rework",
    15: "dev in progress",
    16: "ba in progress",
    17: "ba review",
    18: "in review",
    20: "in review",
}

_NON_PM_TASK_TRANSITIONS: dict[str, set[tuple[str, str]]] = {}

_NON_PM_ALLOWED_SUBTASK_PREFIXES: Dict[str, tuple[str, ...]] = {
    "BA": ("[ba]",),
    "BE": ("[be]",),
    "FE": ("[fe]",),
    "TESTER": ("[tester]", "[qa]", "[bug]"),
}

_ALL_SUBTASK_ROLE_PREFIXES = ("[pm]", "[ba]", "[be]", "[fe]", "[tester]", "[qa]", "[bug]")

_SUBTASK_VALID_TRANSITIONS: Dict[str, set[str]] = {
    "ready": {"ready", "in progress"},
    "in progress": {"ready", "in progress", "done"},
    "done": {"in progress", "done"},
}


def _round_openproject_story_points(sp_val: Any, subject: Optional[str] = None) -> Optional[int]:
    """
    Convert integer or fractional Story Points into OpenProject's integer storyPoints field.
    For the standard 30-20-15-35 screen split (3.0 + 2.0 + 1.5 + 3.5 = 10.0 SP),
    1.5 ([FE]) rounds up to 2 and 3.5 ([Tester]) rounds down to 3 so the 4 Sub-tasks
    sum to 3 + 2 + 2 + 3 = 10 SP on OpenProject.
    """
    if sp_val is None or str(sp_val).strip() == "":
        return None
    subj_low = str(subject or "").strip().lower()
    if "[bug]" in subj_low:
        return 0
    val = float(sp_val)
    if val <= 0:
        return 0
    if abs(val - 1.5) < 1e-6:
        return 2
    if abs(val - 3.5) < 1e-6:
        return 3
    if subj_low.startswith("[fe]") and abs(val - int(val) - 0.5) < 1e-6:
        return int(val) + 1
    if subj_low.startswith(("[tester]", "[qa]")) and abs(val - int(val) - 0.5) < 1e-6:
        return int(val)
    return int(val + 0.5)


def _canonical_type_kind(type_id_or_name: Any, resolved_type_id: Optional[int] = None) -> str:
    """Classify a work package type into 'epic', 'task', 'sub-task', or 'other'."""
    if resolved_type_id == 5:
        return "epic"
    if resolved_type_id == 8:
        return "sub-task"
    if resolved_type_id == 1:
        return "task"
    raw = str(type_id_or_name or "").strip().lower()
    if raw in ("5", "epic", "sử thi"):
        return "epic"
    if raw in ("8", "sub-task", "subtask"):
        return "sub-task"
    if raw in ("1", "task", "nhiệm vụ"):
        return "task"
    return "other"


def _canonical_status_key(status_id_or_name: Any, resolved_status_id: Optional[int] = None) -> str:
    """Normalize a status ID or name into a lowercase canonical key."""
    if resolved_status_id is not None and resolved_status_id in _STATUS_ID_TO_KEY:
        return _STATUS_ID_TO_KEY[resolved_status_id]
    raw = str(status_id_or_name or "").strip().lower()
    if raw.isdigit() and int(raw) in _STATUS_ID_TO_KEY:
        return _STATUS_ID_TO_KEY[int(raw)]
    if raw in (
        "ready", "to do", "todo", "new", "mới",
        "được chỉ định", "xác nhận", "để được lên lịch", "theo lịch trình", "đang chờ",
    ):
        return "ready"
    if raw in ("in progress", "đang xử lý"):
        return "in progress"
    if raw in ("testing", "đang kiểm thử", "kiểm thử"):
        return "testing"
    if raw in ("ready for test", "sẵn sàng kiểm thử", "đã phát triển"):
        return "ready for test"
    if raw in ("rework", "làm lại", "kiểm tra không thành công"):
        return "rework"
    if raw in ("dev in progress", "đang lập trình"):
        return "dev in progress"
    if raw in ("ba in progress", "đang phân tích"):
        return "ba in progress"
    if raw in ("ba review", "duyệt srs"):
        return "ba review"
    if raw in ("in review", "đang rà soát"):
        return "in review"
    if raw in ("done", "closed", "completed", "đóng cửa", "hoàn thành"):
        return "done"
    return raw


def _fetch_children_for_gate(
    client: OpenProjectClient,
    wp_id: int | str,
    child_refs: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Fetch normalized child work packages of a parent Epic or Task for Pre-Transition Gate verification."""
    try:
        filters_str = build_openproject_filters(parent_id=wp_id)
        elements, _ = client.fetch_all_elements(
            "/api/v3/work_packages",
            params={"filters": filters_str, "sortBy": json.dumps([["id", "asc"]])},
            max_items=200,
        )
        if elements:
            return [
                normalize_work_package(el, sanitize=False, include_description=False)
                for el in elements
                if isinstance(el, dict) and str(el.get("id")) != str(wp_id)
            ]
    except Exception:
        pass

    resolved_children: List[Dict[str, Any]] = []
    for cref in child_refs:
        cid = cref.get("id")
        if not cid or str(cid) == str(wp_id):
            continue
        try:
            c_raw = client.get(f"/api/v3/work_packages/{cid}")
            if isinstance(c_raw, dict) and str(c_raw.get("id")) == str(cid):
                resolved_children.append(
                    normalize_work_package(c_raw, sanitize=False, include_description=False)
                )
        except Exception:
            continue
    return resolved_children


def _enforce_create_role_guardrails(
    client: OpenProjectClient,
    args: Dict[str, Any],
    project_id: Optional[int | str] = None,
) -> Dict[str, Any]:
    """
    Enforce 5-Role creation guardrails & smart defaults:
    - Non-PM roles (BA, BE, FE, TESTER) cannot create Tier 1 Epic or Tier 2 Task items.
    - Tier 1 Epic & Tier 2 Task items always default to PM (user_id=4) and strip direct estimated_hours
      to protect the WBS 100% Rule (derivedEstimatedHours).
    - Tier 3 [Bug] Sub-tasks automatically default to type_id=8 (Sub-task), 0 Story Points, and BE/FE assignee.
    - Non-PM roles can only create Sub-tasks under an existing parent_id with their allowed role prefix.
    """
    norm_args = dict(args)
    active_role = client.get_effective_role()
    subj = str(norm_args.get("subject") or "").strip()
    subj_low = subj.lower()

    if norm_args.get("type_id") is None:
        if subj_low.startswith(_ALL_SUBTASK_ROLE_PREFIXES) or (
            norm_args.get("parent_id") is not None and active_role != "PM"
        ):
            norm_args["type_id"] = 8
        elif subj_low.startswith(("[epic]", "[epic ", "epic ")):
            norm_args["type_id"] = 5
        else:
            norm_args["type_id"] = 1

    t_id = client.resolve_type_id(norm_args["type_id"], project_id=project_id)
    type_kind = _canonical_type_kind(norm_args["type_id"], resolved_type_id=t_id)

    # Guardrail 1: Non-PM roles cannot create Epic or parent Task work packages
    if type_kind in ("epic", "task") and active_role != "PM":
        role_member = ROLE_PROFILES.get(active_role, {}).get("member_name", active_role)
        raise OpenProjectAPIError(
            f"Role Guardrail Violation: Active role '{active_role}' ({role_member}) is not permitted "
            f"to create Tier 1 'Epic' or Tier 2 'Task' work packages. "
            f"Only 'PM' (Nguyễn Trung Nghĩa, user_id=4) can create Epics and parent Tasks. "
            f"Role '{active_role}' may only create Tier 3 'Sub-task' (type_id=8) items under an existing parent Task.",
            status_code=403,
            error_identifier="mcp:RoleGuardrailViolation",
            recovery_hint="Set type_id='Sub-task' (8) with a valid 'parent_id' (parent Task ID), or switch to role 'PM' via op_switch_role(role='PM').",
        )

    # Guardrail 1b: Validate initial status_id against 3-Tier workflow rules if provided
    if norm_args.get("status_id") is not None:
        raw_st = str(norm_args["status_id"]).strip().lower()
        res_st_id = client.resolve_status_id(norm_args["status_id"])
        st_key = _canonical_status_key(raw_st, resolved_status_id=res_st_id)
        if (raw_st in ("in review", "18", "20") or st_key == "in review") and type_kind != "epic":
            raise OpenProjectAPIError(
                f"Workflow Guardrail: Status 'In review' is restricted exclusively to Epic (Tier 1), "
                f"cannot apply to '{type_kind}'.",
                status_code=422,
                error_identifier="mcp:InvalidTierStatusTransition",
                recovery_hint="Use 'READY' (1) or 'In progress' (7) when creating a Task or Sub-task.",
            )
        if type_kind == "epic" and st_key not in ("ready", "in progress", "in review", "done"):
            raise OpenProjectAPIError(
                f"Workflow Guardrail: Epic (Tier 1) only supports statuses ('READY', 'In progress', 'In review', 'Done'), "
                f"cannot use '{norm_args['status_id']}'.",
                status_code=422,
                error_identifier="mcp:InvalidTierStatusTransition",
                recovery_hint="Use 'READY' (1) or 'In progress' (7) for Epic.",
            )
        if type_kind == "sub-task" and st_key not in ("ready", "in progress", "done"):
            raise OpenProjectAPIError(
                f"Workflow Guardrail: Sub-task (Tier 3) only supports ('READY' -> 'In progress' -> 'Done'), "
                f"cannot initialize with status '{norm_args['status_id']}'.",
                status_code=422,
                error_identifier="mcp:SubtaskWorkflowViolation",
                recovery_hint="Initialize the Sub-task with status_id='READY' (1) or 'In progress' (7).",
            )

    # Guardrail 2: Epic and Task always default to PM (user_id=4) and never set direct estimated_hours > 0
    if type_kind in ("epic", "task"):
        if norm_args.get("estimated_hours") is not None:
            try:
                if float(norm_args["estimated_hours"]) > 0:
                    norm_args.pop("estimated_hours", None)
            except (ValueError, TypeError):
                norm_args.pop("estimated_hours", None)
        if norm_args.get("assignee_id") is None:
            norm_args["assignee_id"] = 4
        else:
            norm_args["assignee_id"] = client.resolve_assignee_id(norm_args["assignee_id"])
    elif type_kind == "sub-task":
        # Guardrail 2b: Non-PM roles must specify parent_id and use their allowed Sub-task prefix
        if active_role != "PM":
            if not norm_args.get("parent_id"):
                raise OpenProjectAPIError(
                    f"Role Guardrail Violation: Active role '{active_role}' cannot create an orphan Sub-task "
                    f"without 'parent_id'. Every Tier 3 Sub-task must belong to an existing Tier 2 parent Task.",
                    status_code=403,
                    error_identifier="mcp:RoleGuardrailViolation",
                    recovery_hint="Provide 'parent_id' (or 'parent_ref' in op_bulk_create_work_packages) pointing to the parent Task (type_id=1).",
                )
            allowed_prefixes = _NON_PM_ALLOWED_SUBTASK_PREFIXES.get(active_role, ())
            if not subj_low.startswith(allowed_prefixes):
                raise OpenProjectAPIError(
                    f"Role Guardrail Violation: Active role '{active_role}' is only permitted to create Sub-tasks "
                    f"with prefixes {list(allowed_prefixes)}, cannot create '{subj}'.",
                    status_code=403,
                    error_identifier="mcp:RoleGuardrailViolation",
                    recovery_hint=f"Prefix the Sub-task subject with one of {list(allowed_prefixes)}.",
                )

        # [Bug] Sub-tasks always carry 0 Story Points and must be assigned to BE (6) or FE (7)
        if "[bug]" in subj_low:
            norm_args["story_points"] = 0
            if norm_args.get("assignee_id") is not None:
                norm_args["assignee_id"] = client.resolve_assignee_id(norm_args["assignee_id"])
                if norm_args["assignee_id"] not in (6, 7):
                    raise OpenProjectAPIError(
                        f"Role Guardrail Violation: [Bug] Sub-tasks must be assigned to "
                        f"BE (user_id=6) or FE (user_id=7), cannot assign to '{norm_args['assignee_id']}'.",
                        status_code=403,
                        error_identifier="mcp:RoleGuardrailViolation",
                        recovery_hint="Set assignee_id='BE' (user_id=6) for Backend bugs or assignee_id='FE' (user_id=7) for UI/Frontend bugs.",
                    )
            else:
                norm_args["assignee_id"] = (
                    7 if any(k in subj_low for k in ("fe", "ui", "ux", "giao diện", "css")) else 6
                )
        elif norm_args.get("assignee_id") is not None:
            norm_args["assignee_id"] = client.resolve_assignee_id(norm_args["assignee_id"])
            if active_role in ("BA", "BE", "FE", "TESTER"):
                own_uid = int(ROLE_PROFILES[active_role]["user_id"])
                if norm_args["assignee_id"] != own_uid:
                    raise OpenProjectAPIError(
                        f"Role Guardrail Violation: Active role '{active_role}' can only create Sub-tasks "
                        f"assigned to themselves (user_id={own_uid}), cannot assign to '{norm_args['assignee_id']}'.",
                        status_code=403,
                        error_identifier="mcp:RoleGuardrailViolation",
                        recovery_hint=f"Set assignee_id='me' (user_id={own_uid}) or omit assignee_id.",
                    )
        else:
            if subj_low.startswith("[ba]"):
                norm_args["assignee_id"] = 5
            elif subj_low.startswith("[be]"):
                norm_args["assignee_id"] = 6
            elif subj_low.startswith("[fe]"):
                norm_args["assignee_id"] = 7
            elif subj_low.startswith(("[tester]", "[qa]")):
                norm_args["assignee_id"] = 8
            elif subj_low.startswith("[pm]"):
                norm_args["assignee_id"] = 4
            elif active_role in ROLE_PROFILES:
                norm_args["assignee_id"] = int(ROLE_PROFILES[active_role]["user_id"])

    return norm_args


def _enforce_update_role_guardrails(
    client: OpenProjectClient,
    wp_id: int | str,
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Enforce 3-Tier Workflow, Pre-Transition Child Gates & 5-Role Transition Guardrails when updating a work package:
    - 'In review' (18/20) is strictly reserved for Epic (Tier 1).
    - Sub-task (Tier 3) only supports READY (1) -> In progress (7) -> Done (12) and reopen Done (12) -> In progress (7).
    - Tier 1 Epic (type_id=5) and Tier 2 Task (type_id=1) are 100% owned, edited, and transitioned by PM (user_id=4).
      Non-PM roles (BA, BE, FE, TESTER) may only post handoff comments on Epic/Task and must transition only their
      Tier 3 Sub-task (type_id=8) items.
    - Pre-Transition Child State Gates enforce child Sub-task completion before BA Review, Ready for test, or Done.
    - BA/BE/FE cannot modify or close Sub-tasks belonging to another team member; TESTER can only update
      status_id/percentage_done/comment on cross-role Sub-tasks for QA verification/reopen.
    - [Bug] Sub-tasks always enforce 0 Story Points.
    """
    norm_args = dict(args)
    active_role = client.get_effective_role()

    if "assignee_id" in norm_args and norm_args["assignee_id"] is not None:
        if str(norm_args["assignee_id"]).strip().lower() in ("none", "null", "unassigned", ""):
            norm_args["assignee_id"] = None
        else:
            norm_args["assignee_id"] = client.resolve_assignee_id(norm_args["assignee_id"])

    if "responsible_id" in norm_args and norm_args["responsible_id"] is not None:
        if str(norm_args["responsible_id"]).strip().lower() in ("none", "null", "unassigned", ""):
            norm_args["responsible_id"] = None
        else:
            norm_args["responsible_id"] = client.resolve_assignee_id(norm_args["responsible_id"])

    needs_current_wp = (
        norm_args.get("status_id") is not None
        or "assignee_id" in norm_args
        or "type_id" in norm_args
        or "story_points" in norm_args
        or "estimated_hours" in norm_args
        or "subject" in norm_args
        or active_role != "PM"
    )
    if not needs_current_wp:
        return norm_args

    current_wp = client.get(f"/api/v3/work_packages/{wp_id}")
    current_norm = normalize_work_package(current_wp, sanitize=False, include_description=False)
    wp_type_id = (current_norm.get("type") or {}).get("id")
    wp_type_name = str((current_norm.get("type") or {}).get("name") or "").strip().lower()
    type_kind = _canonical_type_kind(wp_type_name, resolved_type_id=wp_type_id)

    cur_status_id = (current_norm.get("status") or {}).get("id")
    cur_status_name = str((current_norm.get("status") or {}).get("name") or "").strip().lower()
    cur_status_key = _canonical_status_key(cur_status_name, resolved_status_id=cur_status_id)
    cur_subj = str(current_norm.get("subject") or "").strip()
    cur_subj_low = cur_subj.lower()
    new_subj_low = str(norm_args.get("subject") or "").strip().lower()
    effective_subj = str(norm_args.get("subject") or cur_subj).strip()

    comment_only_allowed_keys = {"work_package_id", "comment", "lock_version", "notify", "project_id"}
    non_comment_fields = sorted(
        k for k in args.keys()
        if k not in comment_only_allowed_keys and (k in ("assignee_id", "responsible_id", "parent_id", "version_id", "category_id", "budget_id", "start_date", "due_date", "date", "estimated_hours", "remaining_hours", "story_points") or args.get(k) is not None)
    )

    norm_args["lock_version"] = current_wp.get("lockVersion", 0)

    # Check 0a: Protect WBS 100% Rule — strip positive estimated_hours passed directly on Epic or Task
    if type_kind in ("epic", "task") and "estimated_hours" in norm_args and norm_args["estimated_hours"] is not None:
        try:
            if float(norm_args["estimated_hours"]) > 0:
                norm_args.pop("estimated_hours", None)
        except (ValueError, TypeError):
            norm_args.pop("estimated_hours", None)

    # Check 0b: [Bug] Sub-tasks always enforce 0 Story Points on update, and pre-round story_points with effective_subj
    if type_kind == "sub-task" and ("[bug]" in cur_subj_low or "[bug]" in new_subj_low):
        if "story_points" in norm_args and norm_args["story_points"] is not None:
            norm_args["story_points"] = 0
    elif "story_points" in norm_args and norm_args["story_points"] is not None:
        norm_args["story_points"] = _round_openproject_story_points(
            norm_args["story_points"], effective_subj
        )

    # Check 1: Non-PM cannot convert work package type to/from Epic or Task
    if norm_args.get("type_id") is not None and active_role != "PM":
        target_t_id = client.resolve_type_id(norm_args["type_id"])
        target_type_kind = _canonical_type_kind(norm_args["type_id"], resolved_type_id=target_t_id)
        if type_kind in ("epic", "task") or target_type_kind in ("epic", "task"):
            raise OpenProjectAPIError(
                f"Role Guardrail Violation: Active role '{active_role}' cannot change work package type "
                f"of #{wp_id} to/from Epic or Task. Only PM (user_id=4) is authorized.",
                status_code=403,
                error_identifier="mcp:RoleGuardrailViolation",
                recovery_hint="Keep the existing type or switch to role 'PM' via op_switch_role(role='PM').",
            )

    # Check 2: Non-PM cannot reassign Epic or parent Task away from PM (user_id=4)
    if type_kind in ("epic", "task") and "assignee_id" in norm_args:
        if active_role != "PM" and norm_args["assignee_id"] != 4:
            raise OpenProjectAPIError(
                f"Role Guardrail Violation: Tier 1 Epic and Tier 2 Task work packages must remain assigned "
                f"to PM (Nguyễn Trung Nghĩa, user_id=4). Active role '{active_role}' cannot reassign #{wp_id}.",
                status_code=403,
                error_identifier="mcp:RoleGuardrailViolation",
                recovery_hint="Omit 'assignee_id' when updating a parent Task, or assign your own Tier 3 Sub-task instead.",
            )

    # Check 2b: Cross-role Sub-task ownership guardrails for BA, BE, FE, and TESTER
    if type_kind == "sub-task" and active_role in ("BA", "BE", "FE"):
        own_uid = int(ROLE_PROFILES[active_role]["user_id"])
        own_prefix = str(ROLE_PROFILES[active_role]["subtask_prefix"]).lower()
        allowed_own_prefixes = (own_prefix,) if active_role == "BA" else (own_prefix, "[bug]")
        cur_assignee_id = (current_norm.get("assignee") or {}).get("id")
        if cur_assignee_id is not None and int(cur_assignee_id) != own_uid:
            raise OpenProjectAPIError(
                f"Role Guardrail Violation: Active role '{active_role}' (user_id={own_uid}) cannot modify "
                f"Sub-task #{wp_id} assigned to user_id={cur_assignee_id}.",
                status_code=403,
                error_identifier="mcp:RoleGuardrailViolation",
                recovery_hint=f"Only update Sub-tasks assigned to {active_role} (user_id={own_uid}).",
            )
        if (
            cur_subj_low.startswith(_ALL_SUBTASK_ROLE_PREFIXES)
            and not cur_subj_low.startswith(allowed_own_prefixes)
        ):
            raise OpenProjectAPIError(
                f"Role Guardrail Violation: Active role '{active_role}' cannot modify Sub-task #{wp_id} "
                f"('{current_norm.get('subject')}').",
                status_code=403,
                error_identifier="mcp:RoleGuardrailViolation",
                recovery_hint=f"Only update Sub-tasks with prefix {list(allowed_own_prefixes)}.",
            )
        if "subject" in norm_args and norm_args["subject"] is not None:
            if not new_subj_low.startswith(allowed_own_prefixes):
                raise OpenProjectAPIError(
                    f"Role Guardrail Violation: Active role '{active_role}' cannot rename Sub-task #{wp_id} "
                    f"to '{norm_args['subject']}'. Subject must start with {list(allowed_own_prefixes)}.",
                    status_code=403,
                    error_identifier="mcp:RoleGuardrailViolation",
                    recovery_hint=f"Keep the Sub-task subject prefixed with {list(allowed_own_prefixes)}.",
                )
        if "assignee_id" in norm_args and norm_args["assignee_id"] != own_uid:
            raise OpenProjectAPIError(
                f"Role Guardrail Violation: Active role '{active_role}' cannot reassign Sub-task #{wp_id} "
                f"away from user_id={own_uid}.",
                status_code=403,
                error_identifier="mcp:RoleGuardrailViolation",
                recovery_hint=f"Keep assignee_id={own_uid} ('me').",
            )
    elif type_kind == "sub-task" and active_role == "TESTER":
        cur_assignee_id = (current_norm.get("assignee") or {}).get("id")
        is_tester_or_bug = (
            cur_subj_low.startswith(("[tester]", "[qa]", "[bug]"))
            or "[bug]" in cur_subj_low
            or (cur_assignee_id is not None and int(cur_assignee_id) == 8)
        )
        if not is_tester_or_bug:
            allowed_cross_role_fields = {
                "work_package_id", "status_id", "percentage_done", "comment", "lock_version", "notify",
            }
            attempted_forbidden = sorted(
                f for f in norm_args if f not in allowed_cross_role_fields and norm_args[f] is not None
            )
            if attempted_forbidden:
                raise OpenProjectAPIError(
                    f"Role Guardrail Violation: Active role 'TESTER' (user_id=8) cannot modify fields "
                    f"{attempted_forbidden} on cross-role Sub-task #{wp_id} ('{current_norm.get('subject')}'). "
                    f"TESTER may only update 'status_id', 'percentage_done', and 'comment' for QA verification/reopen.",
                    status_code=403,
                    error_identifier="mcp:RoleGuardrailViolation",
                    recovery_hint="Remove non-status fields and only pass 'status_id' (e.g. 'In progress' to reopen) and 'comment'.",
                )
        else:
            if "subject" in norm_args and norm_args["subject"] is not None:
                if not new_subj_low.startswith(("[tester]", "[qa]", "[bug]")):
                    raise OpenProjectAPIError(
                        f"Role Guardrail Violation: Active role 'TESTER' cannot rename Sub-task #{wp_id} "
                        f"to '{norm_args['subject']}'. Subject must start with ['[tester]', '[qa]', '[bug]'].",
                        status_code=403,
                        error_identifier="mcp:RoleGuardrailViolation",
                        recovery_hint="Keep the Sub-task subject prefixed with '[Tester]', '[QA]', or '[Bug]'.",
                    )
            if "assignee_id" in norm_args:
                if "[bug]" in cur_subj_low or "[bug]" in new_subj_low:
                    if norm_args["assignee_id"] not in (6, 7):
                        raise OpenProjectAPIError(
                            f"Role Guardrail Violation: [Bug] Sub-task #{wp_id} must be assigned to BE (user_id=6) "
                            f"or FE (user_id=7), cannot assign to '{norm_args['assignee_id']}'.",
                            status_code=403,
                            error_identifier="mcp:RoleGuardrailViolation",
                            recovery_hint="Set assignee_id='BE' (6) or assignee_id='FE' (7).",
                        )
                elif norm_args["assignee_id"] != 8:
                    raise OpenProjectAPIError(
                        f"Role Guardrail Violation: Active role 'TESTER' cannot reassign [Tester] Sub-task #{wp_id} "
                        f"away from user_id=8.",
                        status_code=403,
                        error_identifier="mcp:RoleGuardrailViolation",
                        recovery_hint="Keep assignee_id=8 ('me').",
                    )

    # Check 3: Status transition rules (3-Tier + 5-Role Guardrails + Pre-Transition Child Gates)
    if norm_args.get("status_id") is not None:
        raw_status = str(norm_args["status_id"]).strip().lower()
        subtask_forbidden = {
            "ba in progress", "ba review", "dev in progress",
            "ready for test", "testing", "rework", "in review",
            "15", "16", "17", "18", "19", "20", "10", "9", "14",
        }

        resolved_s_id = client.resolve_status_id(norm_args["status_id"])
        target_status_key = _canonical_status_key(raw_status, resolved_status_id=resolved_s_id)

        # Role Guardrail 3: Closing Epic or Task directly to Done is restricted to PM
        if type_kind in ("epic", "task") and target_status_key == "done" and active_role != "PM":
            raise OpenProjectAPIError(
                f"Role Guardrail Violation: Active role '{active_role}' cannot close {type_kind.title()} #{wp_id} "
                f"directly to 'Done'. Only 'PM' (Gatekeeper - Nguyễn Trung Nghĩa, user_id=4) is authorized to "
                f"execute 'Approve & Close' (Epic) or 'Pass & Complete' (Task) to 'Done'.",
                status_code=403,
                error_identifier="mcp:RoleGuardrailViolation",
                recovery_hint=(
                    f"Complete your own Tier 3 Sub-task (status_id=12 'Done') and post a 3-part handoff comment "
                    f"via op_add_work_package_comment(work_package_id={wp_id}, comment=...) on parent {type_kind.title()} #{wp_id} "
                    f"so PM (Nguyễn Trung Nghĩa, user_id=4) transitions #{wp_id} to 'Done'."
                ),
            )

        # Role Guardrail 4: Non-PM cannot transition Epic or Task statuses (100% owned by PM)
        if type_kind in ("epic", "task") and active_role != "PM":
            raise OpenProjectAPIError(
                f"Role Transition Violation: Active role '{active_role}' cannot transition Tier {'1 Epic' if type_kind == 'epic' else '2 parent Task'} "
                f"#{wp_id} (current='{cur_status_key}') to '{target_status_key}'. "
                f"Tier 1 'Epic' (type_id=5) and Tier 2 'Task' (type_id=1) work packages are 100% owned and transitioned "
                f"by 'PM' (Nguyễn Trung Nghĩa, user_id=4). Role '{active_role}' may only transition their Tier 3 'Sub-task' (type_id=8) items.",
                status_code=403,
                error_identifier="mcp:RoleTransitionNotAllowed",
                recovery_hint=(
                    f"Update your Tier 3 Sub-task (type_id=8) to 'Done' (status_id=12) and call "
                    f"op_add_work_package_comment(work_package_id={wp_id}, comment=...) with a 3-part handoff comment "
                    f"on parent Task #{wp_id} to request PM (user_id=4) to transition #{wp_id}."
                ),
            )

        # 3-Tier Rule 1: 'In review' (status 18 / 20) is strictly reserved for Epic (Tier 1)
        if (raw_status in ("in review", "18", "20") or target_status_key == "in review") and type_kind != "epic":
            raise OpenProjectAPIError(
                f"Workflow Guardrail: Status 'In review' is restricted exclusively to Epic (Tier 1), "
                f"cannot apply to #{wp_id} (type='{wp_type_name}'). "
                f"For Task (Tier 2), use 'BA Review' or 'Ready for test' / 'Testing'. "
                f"For Sub-task (Tier 3), use 'READY' -> 'In progress' -> 'Done'.",
                status_code=422,
                error_identifier="mcp:InvalidTierStatusTransition",
                recovery_hint="Use 'BA Review' or 'Ready for test' for Task (type_id=1), or 'In progress' / 'Done' for Sub-task (type_id=8).",
            )

        # 3-Tier Rule 2: Sub-task (Tier 3) only uses READY, In progress, Done
        if type_kind == "sub-task" and raw_status in subtask_forbidden:
            raise OpenProjectAPIError(
                f"Workflow Guardrail: Sub-task #{wp_id} only supports the 3-step workflow "
                f"('READY' -> 'In progress' -> 'Done'), cannot transition to '{norm_args['status_id']}'.",
                status_code=422,
                error_identifier="mcp:SubtaskWorkflowViolation",
                recovery_hint="Transition the Sub-task using only 'READY' (1), 'In progress' (7), or 'Done' (12).",
            )

        if type_kind == "epic" and target_status_key not in ("ready", "in progress", "in review", "done"):
            raise OpenProjectAPIError(
                f"Workflow Guardrail: Tier 1 Epic #{wp_id} only supports ('READY' -> 'In progress' -> 'In review' -> 'Done'), "
                f"cannot transition to Task status '{norm_args['status_id']}'.",
                status_code=422,
                error_identifier="mcp:InvalidTierStatusTransition",
                recovery_hint="Transition the Epic using only 'READY' (1), 'In progress' (7), 'In review' (18), or 'Done' (12).",
            )

        if type_kind == "sub-task":
            if target_status_key not in ("ready", "in progress", "done"):
                raise OpenProjectAPIError(
                    f"Workflow Guardrail: Sub-task #{wp_id} only supports ('READY' -> 'In progress' -> 'Done'), "
                    f"cannot transition to '{norm_args['status_id']}'.",
                    status_code=422,
                    error_identifier="mcp:SubtaskWorkflowViolation",
                    recovery_hint="Transition the Sub-task using only 'READY' (1), 'In progress' (7), or 'Done' (12).",
                )
            valid_sub_sources = _SUBTASK_VALID_TRANSITIONS.get(target_status_key, set())
            if cur_status_key and cur_status_key not in valid_sub_sources:
                raise OpenProjectAPIError(
                    f"Workflow Guardrail: Sub-task #{wp_id} cannot jump directly from '{cur_status_key}' "
                    f"to '{target_status_key}'. Allowed Sub-task transitions: 'READY' -> 'In progress' -> 'Done' "
                    f"and 'Done' -> 'In progress' (Reopen Task).",
                    status_code=422,
                    error_identifier="mcp:SubtaskWorkflowViolation",
                    recovery_hint="Transition the Sub-task to 'In progress' (7) first before moving to 'Done' (12) or reopening.",
                )

        # Pre-Transition Child State Gates (when parent Epic/Task has children in _links.children)
        child_refs = current_norm.get("children") or []
        if type_kind in ("epic", "task") and child_refs and target_status_key in ("done", "ready for test", "ba review"):
            is_doc_fast_track = type_kind == "task" and cur_status_key == "ba review" and target_status_key == "done"
            if not is_doc_fast_track:
                children_norm = _fetch_children_for_gate(client, wp_id, child_refs)
                if target_status_key == "done":
                    incomplete = [
                        f"#{c.get('id')} {c.get('subject')} ({(c.get('status') or {}).get('name')})"
                        for c in children_norm
                        if _canonical_status_key(
                            (c.get("status") or {}).get("name"),
                            resolved_status_id=(c.get("status") or {}).get("id"),
                        )
                        != "done"
                    ]
                    if incomplete:
                        raise OpenProjectAPIError(
                            f"Pre-Transition Gate Blocked: Cannot close {type_kind.title()} #{wp_id} to 'Done' "
                            f"while {len(incomplete)} child work package(s) are not 'Done': {', '.join(incomplete)}.",
                            status_code=422,
                            error_identifier="mcp:PrerequisiteChildrenIncomplete",
                            recovery_hint=f"Call op_list_subtasks(parent_id={wp_id}) and transition all incomplete child items to 'Done' before closing #{wp_id}.",
                        )
                elif target_status_key == "ready for test" and type_kind == "task":
                    incomplete_dev = [
                        f"#{c.get('id')} {c.get('subject')} ({(c.get('status') or {}).get('name')})"
                        for c in children_norm
                        if (
                            str(c.get("subject") or "").strip().lower().startswith(("[be]", "[fe]", "[bug]"))
                            or "[bug]" in str(c.get("subject") or "").strip().lower()
                            or str((c.get("type") or {}).get("name") or "").strip().lower() == "bug"
                        )
                        and _canonical_status_key(
                            (c.get("status") or {}).get("name"),
                            resolved_status_id=(c.get("status") or {}).get("id"),
                        )
                        != "done"
                    ]
                    if incomplete_dev:
                        raise OpenProjectAPIError(
                            f"Pre-Transition Gate Blocked: Cannot transition Task #{wp_id} to 'Ready for test' "
                            f"while Dev/Bug Sub-task(s) are not 'Done': {', '.join(incomplete_dev)}.",
                            status_code=422,
                            error_identifier="mcp:PrerequisiteChildrenIncomplete",
                            recovery_hint=f"Ensure all [BE], [FE], and [Bug] Sub-tasks under Task #{wp_id} are 'Done' before transitioning to 'Ready for test'.",
                        )
                elif target_status_key == "ba review" and type_kind == "task":
                    incomplete_ba = [
                        f"#{c.get('id')} {c.get('subject')} ({(c.get('status') or {}).get('name')})"
                        for c in children_norm
                        if str(c.get("subject") or "").strip().lower().startswith("[ba]")
                        and _canonical_status_key(
                            (c.get("status") or {}).get("name"),
                            resolved_status_id=(c.get("status") or {}).get("id"),
                        )
                        != "done"
                    ]
                    if incomplete_ba:
                        raise OpenProjectAPIError(
                            f"Pre-Transition Gate Blocked: Cannot transition Task #{wp_id} to 'BA Review' "
                            f"while [BA] Sub-task(s) are not 'Done': {', '.join(incomplete_ba)}.",
                            status_code=422,
                            error_identifier="mcp:PrerequisiteChildrenIncomplete",
                            recovery_hint=f"Transition the [BA] Sub-task under Task #{wp_id} to 'Done' first before submitting the parent Task to 'BA Review'.",
                        )

    # Check 4: Non-PM cannot modify any non-comment attributes on Epic or Task (and must provide a non-empty comment)
    if active_role != "PM" and type_kind in ("epic", "task"):
        if non_comment_fields or not str(norm_args.get("comment") or "").strip():
            raise OpenProjectAPIError(
                f"Role Guardrail Violation: Active role '{active_role}' cannot modify attributes {non_comment_fields or ['<empty update>']} "
                f"on Tier {'1 Epic' if type_kind == 'epic' else '2 Task'} #{wp_id} ('{current_norm.get('subject')}'). "
                f"Only 'PM' (Nguyễn Trung Nghĩa, user_id=4) may edit Epic/Task attributes. "
                f"Non-PM roles may only modify their own Tier 3 Sub-tasks (type_id=8) or post a handoff comment on #{wp_id}.",
                status_code=403,
                error_identifier="mcp:RoleGuardrailViolation",
                recovery_hint=(
                    f"To post a handoff note on #{wp_id}, pass only a non-empty 'comment' (or call op_add_work_package_comment(work_package_id={wp_id}, comment=...)). "
                    f"To update progress or effort, target your Tier 3 Sub-task (type_id=8) instead."
                ),
            )

    return norm_args


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
        if aid is not None and str(aid).strip().lower() not in ("", "none", "null", "unassigned"):
            aid = client.resolve_assignee_id(aid)
        else:
            aid = None
        payload["_links"]["assignee"] = {"href": f"/api/v3/users/{aid}" if aid else None}

    if "responsible_id" in args:
        rid = args["responsible_id"]
        if rid is not None and str(rid).strip().lower() not in ("", "none", "null", "unassigned"):
            rid = client.resolve_assignee_id(rid)
        else:
            rid = None
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
        payload["storyPoints"] = _round_openproject_story_points(
            args["story_points"], args.get("subject")
        )

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
            "Supports rich filtering (status, type, priority, assignee by ID/role/name/'me'/'tôi', "
            "author, version, category, parent, keyword search, date ranges, or raw OpenProject API v3 filters), "
            "sorting, and pagination."
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
                "description": "Filter by work package type ID or name (e.g. 'Task', 'Sub-task', 'Epic').",
            },
            "priority_id": {
                "type": ["integer", "string"],
                "description": "Filter by priority ID or name.",
            },
            "assignee_id": {
                "type": ["integer", "string"],
                "description": (
                    "Filter by assignee user ID (4..8), 'me'/'tôi' (active role's user_id), "
                    "role code ('PM', 'BA', 'BE', 'FE', 'TESTER'), member name ('Nghĩa', 'Trung', 'Hiếu', 'Thành', 'Vinh'), "
                    "or 'unassigned'."
                ),
            },
            "only_my_tasks": {
                "type": "boolean",
                "description": "If true, automatically filter work packages assigned to the active role's user_id.",
                "default": False,
            },
            "author_id": {"type": ["integer", "string"], "description": "Filter by author user ID, role, name, or 'me'."},
            "responsible_id": {"type": ["integer", "string"], "description": "Filter by responsible user ID, role, or name."},
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

        active_role = client.get_effective_role()

        status_id = args.get("status_id")
        if status_id is not None and not str(status_id).isdigit():
            status_id = client.resolve_status_id(status_id)

        type_id = args.get("type_id")
        if type_id is not None and not str(type_id).isdigit():
            type_id = client.resolve_type_id(type_id, project_id=proj_id)

        priority_id = args.get("priority_id")
        if priority_id is not None and not str(priority_id).isdigit():
            priority_id = client.resolve_priority_id(priority_id)

        raw_assignee = args.get("assignee_id")
        if raw_assignee is None and bool(args.get("only_my_tasks", False)):
            raw_assignee = "me"

        if raw_assignee is not None:
            if str(raw_assignee).strip().lower() in ("none", "null", "unassigned"):
                resolved_assignee: Optional[int | str] = "unassigned"
            else:
                resolved_assignee = client.resolve_assignee_id(raw_assignee)
        else:
            resolved_assignee = None

        filters_str = build_openproject_filters(
            raw_filters=args.get("raw_filters"),
            project_id=None if proj_id else None,  # If proj_id is given, we use project endpoint
            status_id=status_id,
            status_open=args.get("status_open"),
            type_id=type_id,
            priority_id=priority_id,
            assignee_id=resolved_assignee,
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
            active_role=active_role,
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
            "activeRole": active_role,
            "resolvedAssigneeFilter": resolved_assignee,
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
            "assignee_id": {
                "type": ["integer", "string"],
                "description": "Assignee user ID (4..8), 'me'/'tôi', role code ('PM', 'BA', 'BE', 'FE', 'TESTER'), or member name.",
            },
            "parent_id": {"type": "integer", "description": "Parent work package ID."},
            "start_date": {"type": "string", "description": "Start date (YYYY-MM-DD)."},
            "due_date": {"type": "string", "description": "Due date (YYYY-MM-DD)."},
            "estimated_hours": {"type": "number", "description": "Estimated hours."},
            "story_points": {
                "type": ["integer", "number", "null"],
                "description": "Agile Story Points (accepts integer or fractional SP like 1.5, 3.5; auto-rounded for OpenProject API).",
            },
            "custom_fields": {"type": "object", "description": "Custom fields dictionary."},
        },
        domain="work_packages",
        read_only=True,
        idempotent=True,
    )
    def op_validate_work_package_form(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        wp_id = args.get("work_package_id")
        proj_id = args.get("project_id") or client.config.default_project_id

        if wp_id is not None:
            guarded_args = _enforce_update_role_guardrails(client, wp_id, args)
            payload = _build_wp_payload(client, guarded_args, project_id=proj_id, is_create=False)
            if "lockVersion" not in payload:
                current = client.get(f"/api/v3/work_packages/{wp_id}")
                payload["lockVersion"] = current.get("lockVersion", 0)
            form = client.post(f"/api/v3/work_packages/{wp_id}/form", json_body=payload)
        else:
            guarded_args = _enforce_create_role_guardrails(client, args, project_id=proj_id)
            payload = _build_wp_payload(client, guarded_args, project_id=proj_id, is_create=True)
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
            "Create a new work package (Epic, Task, Sub-task) in a project "
            "(POST /api/v3/projects/{project_id}/work_packages). Enforces 5-Role Guardrails: "
            "Epics/Tasks default to PM (user_id=4) and can only be created by PM; [Bug] Sub-tasks default to 0 SP."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Target Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "subject": {"type": "string", "description": "Title/subject of the work package."},
            "type_id": {
                "type": ["integer", "string"],
                "description": "Work package type ID or name (e.g. 'Epic' (5), 'Task' (1), 'Sub-task' (8)).",
            },
            "status_id": {
                "type": ["integer", "string"],
                "description": "Initial status ID or name (e.g. 'READY', 'In progress').",
            },
            "priority_id": {
                "type": ["integer", "string"],
                "description": "Priority ID or name (e.g. 'Low', 'Normal', 'High', 'Immediate').",
            },
            "description": {"type": "string", "description": "Markdown description."},
            "parent_id": {"type": "integer", "description": "Parent work package ID for WBS hierarchy / subtasks."},
            "assignee_id": {
                "type": ["integer", "string"],
                "description": (
                    "Assignee user ID (4..8), 'me'/'tôi', role code ('PM', 'BA', 'BE', 'FE', 'TESTER'), "
                    "or member name ('Nghĩa', 'Trung', 'Hiếu', 'Thành', 'Vinh')."
                ),
            },
            "responsible_id": {
                "type": ["integer", "string"],
                "description": "Accountable/responsible user ID, role code, or member name.",
            },
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
            "story_points": {
                "type": ["integer", "number", "null"],
                "description": "Agile Story Points (accepts integer or fractional SP like 1.5, 3.5; auto-rounded for OpenProject API).",
            },
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

        guarded_args = _enforce_create_role_guardrails(client, args, project_id=proj_id)
        payload = _build_wp_payload(client, guarded_args, project_id=proj_id, is_create=True)
        notify = "true" if guarded_args.get("notify", False) else "false"
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
            "Automatically fetches and handles optimistic locking (lockVersion), retries on 409 Conflict, "
            "and enforces 3-Tier & 5-Role Workflow Guardrails (PM exclusively owns and transitions Epic/Task; "
            "BA/BE/FE/TESTER modify/transition their Sub-tasks and post handoff comments on parent Tasks)."
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
                    "New status ID or name following the 3-Tier & 5-Role Workflow: "
                    "Epic (READY, In progress, In review, Done — PM only); "
                    "Task (READY -> BA in progress -> BA Review -> Dev in progress -> Ready for test -> Testing -> Rework -> Done — PM only); "
                    "Sub-task (READY -> In progress -> Done and Done -> In progress — owned by BA, BE, FE, TESTER, PM)."
                ),
            },
            "priority_id": {"type": ["integer", "string"], "description": "New priority ID or name."},
            "assignee_id": {
                "type": ["integer", "string", "null"],
                "description": (
                    "New assignee user ID (4..8), 'me'/'tôi', role code ('PM', 'BA', 'BE', 'FE', 'TESTER'), "
                    "member name ('Nghĩa', 'Trung', 'Hiếu', 'Thành', 'Vinh'), or null to unassign."
                ),
            },
            "responsible_id": {
                "type": ["integer", "string", "null"],
                "description": "New responsible user ID, role code, member name, or null to clear.",
            },
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
            "story_points": {
                "type": ["integer", "number", "null"],
                "description": "Story points (accepts integer or fractional SP like 1.5, 3.5; auto-rounded for OpenProject API).",
            },
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

        guarded_args = _enforce_update_role_guardrails(client, wp_id, args)
        payload = _build_wp_payload(client, guarded_args, is_create=False)
        updated = client.patch_work_package_safe(
            wp_id=wp_id,
            payload=payload,
            notify=bool(guarded_args.get("notify", False)),
        )
        return normalize_work_package(updated, sanitize=client.config.sanitize_untrusted_content)

    @registry.register(
        name="op_delete_work_package",
        description="Delete a work package by ID (DELETE /api/v3/work_packages/{id}). Non-PM roles cannot delete Epic or Task items.",
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
        active_role = client.get_effective_role()
        if active_role != "PM":
            current_wp = client.get(f"/api/v3/work_packages/{wp_id}")
            current_norm = normalize_work_package(current_wp, sanitize=False, include_description=False)
            wp_type_id = (current_norm.get("type") or {}).get("id")
            wp_type_name = str((current_norm.get("type") or {}).get("name") or "").strip().lower()
            type_kind = _canonical_type_kind(wp_type_name, resolved_type_id=wp_type_id)
            if type_kind in ("epic", "task"):
                raise OpenProjectAPIError(
                    f"Role Guardrail Violation: Active role '{active_role}' is not permitted to delete "
                    f"Tier 1 'Epic' or Tier 2 'Task' #{wp_id}. Only 'PM' (Nguyễn Trung Nghĩa, user_id=4) "
                    f"can delete Epics or parent Tasks.",
                    status_code=403,
                    error_identifier="mcp:RoleGuardrailViolation",
                    recovery_hint="Switch to role 'PM' via op_switch_role(role='PM') to delete Epic or Task work packages.",
                )
            if type_kind == "sub-task" and active_role in ("BA", "BE", "FE", "TESTER"):
                own_uid = int(ROLE_PROFILES[active_role]["user_id"])
                cur_assignee_id = (current_norm.get("assignee") or {}).get("id")
                cur_subj_low = str(current_norm.get("subject") or "").strip().lower()
                if active_role == "TESTER":
                    is_tester_or_bug = (
                        cur_subj_low.startswith(("[tester]", "[qa]", "[bug]"))
                        or "[bug]" in cur_subj_low
                        or (cur_assignee_id is not None and int(cur_assignee_id) == own_uid)
                    )
                    if not is_tester_or_bug:
                        raise OpenProjectAPIError(
                            f"Role Guardrail Violation: Active role 'TESTER' (user_id={own_uid}) cannot delete "
                            f"Sub-task #{wp_id} ('{current_norm.get('subject')}') belonging to another role.",
                            status_code=403,
                            error_identifier="mcp:RoleGuardrailViolation",
                            recovery_hint="TESTER may only delete [Tester] or [Bug] Sub-tasks.",
                        )
                else:
                    own_prefix = str(ROLE_PROFILES[active_role]["subtask_prefix"]).lower()
                    if (cur_assignee_id is not None and int(cur_assignee_id) != own_uid) or (
                        cur_subj_low.startswith(_ALL_SUBTASK_ROLE_PREFIXES)
                        and not cur_subj_low.startswith(own_prefix)
                    ):
                        raise OpenProjectAPIError(
                            f"Role Guardrail Violation: Active role '{active_role}' (user_id={own_uid}) cannot delete "
                            f"Sub-task #{wp_id} ('{current_norm.get('subject')}').",
                            status_code=403,
                            error_identifier="mcp:RoleGuardrailViolation",
                            recovery_hint=f"Only delete Sub-tasks with prefix '{own_prefix}' owned by {active_role} (user_id={own_uid}).",
                        )
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
            "it via 'parent_ref' ('EPIC-1') or an existing numeric 'parent_id'. Supports role/member names as assignee_id."
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
                    "assignee_id (ID, 'me', 'PM', 'BA', 'BE', 'FE', 'TESTER', 'Nghĩa', 'Trung', 'Hiếu', 'Thành', 'Vinh'), "
                    "start_date, due_date, estimated_hours, percentage_done, description, schedule_manually."
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
                if parent_ref and str(parent_ref) not in ref_map and not item_copy.get("parent_id"):
                    raise OpenProjectAPIError(
                        f"Unresolved parent_ref '{parent_ref}': parent work package was not created or ref_key was not found earlier in the batch.",
                        status_code=422,
                        error_identifier="mcp:UnresolvedParentRef",
                        recovery_hint="Ensure the parent item defining 'ref_key' appears earlier in 'items' and succeeds.",
                    )
                guarded_item = _enforce_create_role_guardrails(client, item_copy, project_id=proj_id)
                payload = _build_wp_payload(client, guarded_item, project_id=proj_id, is_create=True)
                created = client.post(
                    f"/api/v3/projects/{proj_id}/work_packages",
                    json_body=payload,
                    params={"notify": notify},
                )
                norm = normalize_work_package(created, sanitize=client.config.sanitize_untrusted_content, include_description=False)
                if ref_key and norm.get("id"):
                    ref_map[str(ref_key)] = int(norm["id"])
                created_list.append(norm)
            except OpenProjectAPIError as exc:
                errors.append(
                    {
                        "index": idx,
                        "subject": item.get("subject"),
                        "error": str(exc),
                        "errorIdentifier": exc.error_identifier,
                        "recoveryHint": exc.recovery_hint,
                    }
                )
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
        description=(
            "Batch-update multiple work packages in one call (auto-handling lockVersion and 5-Role Guardrails "
            "for each item: PM owns/transitions Epic & Task; BA/BE/FE/TESTER transition their Sub-tasks and post handoff comments)."
        ),
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
                guarded_item = _enforce_update_role_guardrails(client, wp_id, item)
                payload = _build_wp_payload(client, guarded_item, is_create=False)
                res = client.patch_work_package_safe(wp_id, payload, notify=notify)
                succeeded.append(
                    normalize_work_package(res, sanitize=client.config.sanitize_untrusted_content, include_description=False)
                )
            except OpenProjectAPIError as exc:
                failed.append(
                    {
                        "workPackageId": wp_id,
                        "error": str(exc),
                        "errorIdentifier": exc.error_identifier,
                        "recoveryHint": exc.recovery_hint,
                    }
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
            "(POST /api/v3/custom_actions/{custom_action_id}/execute). "
            "Enforces 5-Role Guardrails: only PM (user_id=4) may execute custom actions on Tier 1 Epic or Tier 2 Task items."
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
        active_role = client.get_effective_role()
        current = client.get(f"/api/v3/work_packages/{wp_id}")
        if active_role != "PM":
            current_norm = normalize_work_package(current, sanitize=False, include_description=False)
            wp_type_id = (current_norm.get("type") or {}).get("id")
            wp_type_name = str((current_norm.get("type") or {}).get("name") or "").strip().lower()
            type_kind = _canonical_type_kind(wp_type_name, resolved_type_id=wp_type_id)
            if type_kind in ("epic", "task"):
                raise OpenProjectAPIError(
                    f"Role Transition Violation: Active role '{active_role}' cannot execute custom actions "
                    f"on Tier {'1 Epic' if type_kind == 'epic' else '2 Task'} #{wp_id}. "
                    f"Only 'PM' (Nguyễn Trung Nghĩa, user_id=4) can execute transitions or custom actions on Epics and Tasks.",
                    status_code=403,
                    error_identifier="mcp:RoleTransitionNotAllowed",
                    recovery_hint=(
                        f"Use op_add_work_package_comment(work_package_id={wp_id}, comment=...) to post a 3-part handoff comment "
                        f"on #{wp_id} so PM (user_id=4) executes the transition."
                    ),
                )
            if type_kind == "sub-task" and active_role in ("BA", "BE", "FE"):
                own_uid = int(ROLE_PROFILES[active_role]["user_id"])
                own_prefix = str(ROLE_PROFILES[active_role]["subtask_prefix"]).lower()
                allowed_own_prefixes = (own_prefix,) if active_role == "BA" else (own_prefix, "[bug]")
                cur_assignee_id = (current_norm.get("assignee") or {}).get("id")
                cur_subj_low = str(current_norm.get("subject") or "").strip().lower()
                if (cur_assignee_id is not None and int(cur_assignee_id) != own_uid) or (
                    cur_subj_low.startswith(_ALL_SUBTASK_ROLE_PREFIXES)
                    and not cur_subj_low.startswith(allowed_own_prefixes)
                ):
                    raise OpenProjectAPIError(
                        f"Role Guardrail Violation: Active role '{active_role}' (user_id={own_uid}) cannot execute "
                        f"custom actions on Sub-task #{wp_id} assigned to user_id={cur_assignee_id}.",
                        status_code=403,
                        error_identifier="mcp:RoleGuardrailViolation",
                        recovery_hint=f"Only execute custom actions on Sub-tasks assigned to {active_role} (user_id={own_uid}).",
                    )
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
        destructive=True,
    )
    def op_import_standard_wbs_csv(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        import csv
        from pathlib import Path

        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        clear_existing = bool(args.get("clear_existing", True))
        client.guard_write_operation(project_ref=proj_id, is_delete=clear_existing)
        active_role = client.get_effective_role()
        if active_role != "PM":
            raise OpenProjectAPIError(
                f"Role Guardrail Violation: Active role '{active_role}' is not permitted to run "
                "op_import_standard_wbs_csv. Only 'PM' (Nguyễn Trung Nghĩa, user_id=4) can import "
                "or reset the 3-Tier WBS hierarchy.",
                status_code=403,
                error_identifier="mcp:RoleGuardrailViolation",
                recovery_hint="Switch to role 'PM' via op_switch_role(role='PM') before importing the WBS CSV.",
            )

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
            if "nghĩa" in uname.lower() or "nghia2592005@gmail.com" in uemail or "nghia" in uemail:
                assignee_map["Nguyễn Trung Nghĩa"] = uid
            elif "trung" in uname.lower() or "nguyenvinhtrung0509@gmail.com" in uemail or "trungnv" in uemail:
                assignee_map["Nguyễn Vĩnh Trung"] = uid
            elif "hiếu" in uname.lower() or "hieubao189@gmail.com" in uemail or "hieuvq" in uemail:
                assignee_map["Vũ Quốc Hiếu"] = uid
            elif "thành" in uname.lower() or "buituanthanh02@gmail.com" in uemail or "thanhbt" in uemail:
                assignee_map["Bùi Tuấn Thành"] = uid
            elif "vinh" in uname.lower() or "vinhluong2894@gmail.com" in uemail or "vinhld" in uemail:
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
            sp_val = _round_openproject_story_points(r["Story Points"] or 0, subject) or 0
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


