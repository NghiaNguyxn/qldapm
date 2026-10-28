"""
MCP Primitive #3: Prompts (prompts/list, prompts/get).
Standardized Slash Workflows for Project Management, Agile/Scrum, WBS Decomposition,
Gantt Schedule Auditing, and Earned Value Management (EVM) in OpenProject.
"""

from __future__ import annotations

from typing import Any, Dict, List


PROMPT_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "op-wbs-architect",
        "description": (
            "Decompose a screen or feature requirement into the team's standard 3-tier WBS "
            "(Epic -> Task [Màn hình] -> 4 Sub-tasks: [BA], [BE], [FE], [Tester]) with estimates, "
            "dates, and FS dependencies, and batch-create them in OpenProject."
        ),
        "arguments": [
            {
                "name": "project_id",
                "description": "Target OpenProject project ID or identifier (default: 3).",
                "required": True,
            },
            {
                "name": "feature_requirement",
                "description": "Description of the screen or module to decompose (e.g. '[Màn hình] Thanh toán POS & QR VNPay').",
                "required": True,
            },
            {
                "name": "epic_parent_id",
                "description": "Optional parent Epic work package ID (e.g. 1, 2, 3, or 4).",
                "required": False,
            },
            {
                "name": "start_date",
                "description": "Planned start date (YYYY-MM-DD).",
                "required": False,
            },
        ],
    },
    {
        "name": "op-daily-standup",
        "description": (
            "Generate a Daily Standup Report for a project: Completed recently, In Progress today, "
            "Overdue/Blocked tasks, and Unassigned items."
        ),
        "arguments": [
            {
                "name": "project_id",
                "description": "OpenProject project ID or identifier.",
                "required": True,
            },
        ],
    },
    {
        "name": "op-sprint-review-evm",
        "description": (
            "Execute a comprehensive Sprint Review, Earned Value Management (EVM: BAC, PV, EV, AC, CPI, SPI, EAC), "
            "and Team Member KPI / Bonus Scorecard analysis."
        ),
        "arguments": [
            {
                "name": "project_id",
                "description": "OpenProject project ID or identifier.",
                "required": True,
            },
            {
                "name": "hourly_rate",
                "description": "Optional hourly cost rate for EVM financial conversion.",
                "required": False,
            },
        ],
    },
    {
        "name": "op-gantt-schedule-audit",
        "description": (
            "Audit the project's Gantt chart, Critical Path (ES/EF/LS/LF/Float), dependency date conflicts, "
            "and WBS 100% Rule compliance, then propose corrective scheduling actions."
        ),
        "arguments": [
            {
                "name": "project_id",
                "description": "OpenProject project ID or identifier.",
                "required": True,
            },
        ],
    },
    {
        "name": "op-bug-triage",
        "description": (
            "Standardized Bug Triage workflow: inspect project types/statuses/members, check for duplicate "
            "issues, create a structured Bug work package, link it to the affected task, and route to an assignee."
        ),
        "arguments": [
            {
                "name": "project_id",
                "description": "OpenProject project ID.",
                "required": True,
            },
            {
                "name": "bug_summary",
                "description": "Symptom or error description of the bug.",
                "required": True,
            },
        ],
    },
]


def list_prompts() -> List[Dict[str, Any]]:
    return PROMPT_DEFINITIONS


def get_prompt(name: str, arguments: Dict[str, Any] | None = None) -> Dict[str, Any]:
    args = arguments or {}
    proj_id = args.get("project_id", "<project_id>")

    if name == "op-wbs-architect":
        req = args.get("feature_requirement", "<feature_requirement>")
        epic_id = args.get("epic_parent_id", "")
        start_d = args.get("start_date", "today")
        return {
            "description": f"3-Tier WBS Architect (Epic -> Task -> 4 Sub-tasks [BA/BE/FE/Tester]) for project {proj_id}",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Act as a Senior Project Manager connected to OpenProject (project_id={proj_id}).\n"
                            f"Screen/Module Requirement to decompose: {req}\n"
                            f"Parent Epic ID (if any): {epic_id or 'Inspect existing Epics first'}\n"
                            f"Target start date: {start_d}\n\n"
                            "Follow the team's exact 3-Tier OpenProject WBS standard:\n"
                            "- Tier 1: `Epic` (type_id='Epic' / 5)\n"
                            "- Tier 2: `Task` (type_id='Task' / 1, e.g. `[Màn hình] ...`, child of the Epic)\n"
                            "- Tier 3: `Sub-task` (type_id='Sub-task' / 8, child of the Task), split into 4 role-based Sub-tasks:\n"
                            "   1. `[BA] Phân tích & Thiết kế ...` (Assigned to BA - Nguyễn Vĩnh Trung)\n"
                            "   2. `[BE] Lập trình API ...` (Assigned to BE - Vũ Quốc Hiếu)\n"
                            "   3. `[FE] Lập trình Giao diện ...` (Assigned to FE - Bùi Tuấn Thành)\n"
                            "   4. `[Tester] Thiết kế Test Case, Kiểm thử ...` (Assigned to Tester - Lương Duy Vinh)\n\n"
                            "Steps to execute:\n"
                            "1. Call `op_get_project` and `op_list_project_assignable_users` to confirm type IDs and member user IDs.\n"
                            "2. Call `op_bulk_create_work_packages` using symbolic `ref_key` (e.g. 'TASK-1') on the parent `Task` and `parent_ref='TASK-1'` on the 4 `Sub-task` items.\n"
                            "3. Call `op_create_dependency_chain` to link the 4 Sub-tasks in sequence ([BA] -> [BE] -> [FE] -> [Tester]).\n"
                            "4. Present a summary table of created work package IDs, types (Epic / Task / Sub-task), assignees, dates, and estimated hours."
                        ),
                    },
                }
            ],
        }

    if name == "op-daily-standup":
        return {
            "description": f"Daily Standup Report for project {proj_id}",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Generate a structured Daily Standup Report for OpenProject project `{proj_id}`:\n"
                            "1. Call `op_list_work_packages` (with `project_id`) and `op_analyze_team_workload`.\n"
                            "2. Group findings into:\n"
                            "   - **Completed / Closed Recently**\n"
                            "   - **In Progress Today** (with assignee & % done)\n"
                            "   - **Overdue / Schedule Risk Bottlenecks** (dueDate < today and still open)\n"
                            "   - **Unassigned / Overloaded Member Alerts**\n"
                            "3. Recommend 3 concrete actions for the Scrum Master / PM today."
                        ),
                    },
                }
            ],
        }

    if name == "op-sprint-review-evm":
        rate = args.get("hourly_rate", 1.0)
        return {
            "description": f"Sprint Review, EVM & KPI Scorecard for project {proj_id}",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Run a full Executive Project Control & Sprint Review for OpenProject project `{proj_id}`:\n"
                            f"1. Call `op_analyze_project_evm` with `project_id='{proj_id}'` and `hourly_rate={rate}`.\n"
                            f"2. Call `op_analyze_member_kpi_scorecard` with `project_id='{proj_id}'`.\n"
                            f"3. Call `op_summarize_time_report` with `project_id='{proj_id}'`.\n"
                            "4. Synthesize an executive Markdown report covering:\n"
                            "   - Earned Value table (`BAC, PV, EV, AC, CV, SV, CPI, SPI, EAC, ETC, VAC, TCPI`)\n"
                            "   - Cost & Schedule health diagnosis\n"
                            "   - Team Member KPI & Bonus Allocation table\n"
                            "   - Corrective recommendations."
                        ),
                    },
                }
            ],
        }

    if name == "op-gantt-schedule-audit":
        return {
            "description": f"Gantt Schedule & Critical Path Audit for project {proj_id}",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Audit the Gantt schedule and WBS integrity of OpenProject project `{proj_id}`:\n"
                            f"1. Call `op_analyze_gantt_critical_path` for `project_id='{proj_id}'`.\n"
                            f"2. Call `op_generate_wbs_tree` for `project_id='{proj_id}'`.\n"
                            "3. Report:\n"
                            "   - Critical Path chain (tasks with Total Float = 0)\n"
                            "   - Any `scheduleDateConflicts` where a successor starts before its predecessor finishes\n"
                            "   - Any `wbs100PercentRuleDiscrepancies` between parent tasks and child subtasks\n"
                            "   - Unscheduled tasks missing start/due dates."
                        ),
                    },
                }
            ],
        }

    if name == "op-bug-triage":
        bug_summary = args.get("bug_summary", "<bug_summary>")
        return {
            "description": f"Bug Triage workflow for project {proj_id}",
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "text",
                        "text": (
                            f"Triage and log the following bug in OpenProject project `{proj_id}`:\n"
                            f"Bug Symptom: {bug_summary}\n\n"
                            "Steps:\n"
                            "1. Call `op_list_work_packages` with `search_text` to check for existing duplicate bugs or related tasks.\n"
                            "2. Call `op_analyze_team_workload` to identify the least overloaded developer.\n"
                            "3. Call `op_create_work_package` with `type_id='Bug'` (or 'Task' if Bug type is not enabled), structured reproduction steps in Markdown description, appropriate priority, and assignee.\n"
                            "4. If a related feature/task exists, call `op_create_relation` with `relation_type='relates'` or `'blocks'`."
                        ),
                    },
                }
            ],
        }

    raise ValueError(f"Unknown prompt '{name}'. Call prompts/list to inspect available prompts.")
