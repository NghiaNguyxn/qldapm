"""
Configuration & Security Guardrails for the OpenProject MCP Server.
Loads environment variables from .env files and enforces defense-in-depth policies.
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

VALID_MEMBER_ROLES = ("PM", "BA", "BE", "FE", "TESTER", "AUTO")

# Standard 3-Tier Types & 10 Workflow Statuses on OpenProject (Project ID 3 - QuanLyCatToc)
STANDARD_TYPE_IDS: Dict[str, int] = {
    "task": 1,
    "nhiệm vụ": 1,
    "epic": 5,
    "sử thi": 5,
    "sub-task": 8,
    "subtask": 8,
}

STANDARD_STATUS_IDS: Dict[str, int] = {
    "ready": 1,
    "to do": 1,
    "todo": 1,
    "new": 1,
    "mới": 1,
    "in progress": 7,
    "đang xử lý": 7,
    "testing": 9,
    "đang kiểm thử": 9,
    "kiểm thử": 9,
    "ready for test": 10,
    "sẵn sàng kiểm thử": 10,
    "đã phát triển": 8,
    "done": 12,
    "closed": 12,
    "completed": 12,
    "đóng cửa": 12,
    "hoàn thành": 12,
    "rework": 14,
    "làm lại": 14,
    "kiểm tra không thành công": 11,
    "dev in progress": 15,
    "đang lập trình": 15,
    "ba in progress": 16,
    "đang phân tích": 16,
    "ba review": 17,
    "duyệt srs": 17,
    "in review": 18,
    "đang rà soát": 18,
}

ROLE_PROFILES: Dict[str, Dict[str, Any]] = {
    "PM": {
        "role": "PM",
        "title": "Project Manager & Scrum Master (Gatekeeper)",
        "member_name": "Nghĩa Nguyễn Trung",
        "full_name_vi": "Nguyễn Trung Nghĩa",
        "user_id": 4,
        "email": "nghia2592005@gmail.com",
        "login": "nghia2592005@gmail.com",
        "subtask_prefix": "[PM]",
        "weight_percent": 100,
        "weight_ratio": "Gatekeeper & Owner of 100% Tier 1 Epics & Tier 2 Tasks (30-20-15-35 coordinator)",
        "description": (
            "Sole owner and gatekeeper of 100% Tier 1 Epics (type_id=5) and Tier 2 Tasks (type_id=1). "
            "Exclusively creates, edits attributes, deletes, and transitions Epic and Task statuses "
            "(protected by Pre-Transition Child State Gates 1, 2, 3) upon receiving 3-part handoff comments from BA, BE, FE, and TESTER."
        ),
        "default_story_points": 3.0,
        "default_estimated_hours_per_screen": 12.0,
        "skill_name": "op-role-pm",
        "skill_relative_path": ".agents/skills/op-role-pm/SKILL.md",
        "owned_tiers": [
            "Tier 1: Epic (type_id=5)",
            "Tier 2: Task (type_id=1)",
            "Tier 3: Sub-task [PM] (type_id=8)",
        ],
        "can_create_epic_or_task": True,
        "can_delete_epic_or_task": True,
        "can_transition_epic_or_task": True,
        "can_close_epic_or_task": True,
        "allowed_epic_transitions": [
            "READY (1) -> In progress (7) [Start Work]",
            "In progress (7) -> In review (18) [Submit for Review]",
            "In review (18) -> Done (12) [Approve & Close — requires 100% child Tasks Done]",
            "In review (18) -> In progress (7)",
            "Done (12) -> In progress (7)",
        ],
        "allowed_task_transitions": [
            "READY (1) -> BA in progress (16) [Start Analysis]",
            "READY (1) -> Dev in progress (15) [Start Work — Technical Task]",
            "READY (1) -> In progress (7)",
            "BA in progress (16) -> BA Review (17) [Submit SRS — requires [BA] Sub-task Done]",
            "BA Review (17) -> BA in progress (16) [Request SRS Fix]",
            "BA Review (17) -> Dev in progress (15) [Approve & Start Dev]",
            "BA Review (17) -> Done (12) [Complete Task — Management/Doc Task]",
            "Dev in progress (15) -> Ready for test (10) [Submit for Review — requires [BE], [FE], [Bug] Sub-tasks Done]",
            "Ready for test (10) -> Testing (9) [Start Testing]",
            "Testing (9) -> Rework (14) [Reject / Report Bug]",
            "Rework (14) -> Dev in progress (15) [Fix Bug / Resume Dev]",
            "Testing (9) -> Done (12) [Pass & Complete — requires 100% Sub-tasks Done]",
            "Done (12) -> Rework (14) [Reopen Task]",
            "In progress (7) -> Done (12)",
        ],
        "allowed_subtask_transitions": [
            "READY (1) -> In progress (7) [Start Work]",
            "In progress (7) -> Done (12) [Complete Task]",
            "Done (12) -> In progress (7) [Reopen Task]",
        ],
        "recommended_tools": [
            "op_get_role_context",
            "op_bulk_create_work_packages",
            "op_create_dependency_chain",
            "op_analyze_gantt_critical_path",
            "op_analyze_project_evm",
            "op_analyze_member_kpi_scorecard",
            "op_analyze_team_workload",
            "op_generate_wbs_tree",
            "op_update_work_package",
        ],
    },
    "BA": {
        "role": "BA",
        "title": "Business Analyst",
        "member_name": "Trung (BA) Nguyễn Vĩnh",
        "full_name_vi": "Nguyễn Vĩnh Trung",
        "user_id": 5,
        "email": "nguyenvinhtrung0509@gmail.com",
        "login": "nguyenvinhtrung0509@gmail.com",
        "subtask_prefix": "[BA]",
        "weight_percent": 30,
        "weight_ratio": "30% (3.0 SP / 10 SP screen = 12h standard effort)",
        "description": (
            "Owns Tier 3 [BA] Sub-tasks (type_id=8, 30% weight = 3.0 SP / 12h per screen). "
            "Transitions only [BA] Sub-tasks (READY -> In progress -> Done and Done -> In progress) "
            "and posts 3-part handoff comments on the parent Task so PM transitions the parent Task."
        ),
        "default_story_points": 3.0,
        "default_estimated_hours_per_screen": 12.0,
        "skill_name": "op-role-ba",
        "skill_relative_path": ".agents/skills/op-role-ba/SKILL.md",
        "owned_tiers": ["Tier 3: Sub-task [BA] (type_id=8)"],
        "can_create_epic_or_task": False,
        "can_delete_epic_or_task": False,
        "can_transition_epic_or_task": False,
        "can_close_epic_or_task": False,
        "allowed_epic_transitions": [],
        "allowed_task_transitions": [],
        "allowed_subtask_transitions": [
            "READY (1) -> In progress (7) [Start Work]",
            "In progress (7) -> Done (12) [Complete Task]",
            "Done (12) -> In progress (7) [Reopen Task — Request SRS Fix]",
        ],
        "recommended_tools": [
            "op_get_role_context",
            "op_list_work_packages",
            "op_get_work_package",
            "op_update_work_package",
            "op_add_work_package_comment",
            "op_log_time_entry",
            "op_upload_attachment",
        ],
    },
    "BE": {
        "role": "BE",
        "title": "Backend Developer",
        "member_name": "Hiếu (BE) Vũ Quốc",
        "full_name_vi": "Vũ Quốc Hiếu",
        "user_id": 6,
        "email": "hieubao189@gmail.com",
        "login": "hieubao189@gmail.com",
        "subtask_prefix": "[BE]",
        "weight_percent": 20,
        "weight_ratio": "20% (2.0 SP / 10 SP screen = 8h standard effort)",
        "description": (
            "Owns Tier 3 [BE] Sub-tasks (type_id=8, 20% weight = 2.0 SP / 8h per screen) and Backend [Bug] Sub-tasks (0 SP). "
            "Transitions only [BE] and Backend [Bug] Sub-tasks (READY -> In progress -> Done and Done -> In progress) "
            "and posts 3-part handoff comments on the parent Task so PM transitions the parent Task."
        ),
        "default_story_points": 2.0,
        "default_estimated_hours_per_screen": 8.0,
        "skill_name": "op-role-be",
        "skill_relative_path": ".agents/skills/op-role-be/SKILL.md",
        "owned_tiers": [
            "Tier 3: Sub-task [BE] (type_id=8)",
            "Tier 3: Sub-task [Bug] assigned to BE (type_id=8, 0 SP)",
        ],
        "can_create_epic_or_task": False,
        "can_delete_epic_or_task": False,
        "can_transition_epic_or_task": False,
        "can_close_epic_or_task": False,
        "allowed_epic_transitions": [],
        "allowed_task_transitions": [],
        "allowed_subtask_transitions": [
            "READY (1) -> In progress (7) [Start Work]",
            "In progress (7) -> Done (12) [Complete Task]",
            "Done (12) -> In progress (7) [Reopen Task — Rework / Bug Fix]",
        ],
        "recommended_tools": [
            "op_get_role_context",
            "op_list_work_packages",
            "op_get_work_package",
            "op_list_subtasks",
            "op_update_work_package",
            "op_log_time_entry",
            "op_add_work_package_comment",
        ],
    },
    "FE": {
        "role": "FE",
        "title": "Frontend Developer",
        "member_name": "Thành (FE) Bùi Tuấn",
        "full_name_vi": "Bùi Tuấn Thành",
        "user_id": 7,
        "email": "buituanthanh02@gmail.com",
        "login": "buituanthanh02@gmail.com",
        "subtask_prefix": "[FE]",
        "weight_percent": 15,
        "weight_ratio": "15% (1.5 SP / 10 SP screen = 6h standard effort)",
        "description": (
            "Owns Tier 3 [FE] Sub-tasks (type_id=8, 15% weight = 1.5 SP / 6h per screen) and Frontend [Bug] Sub-tasks (0 SP). "
            "Transitions only [FE] and Frontend [Bug] Sub-tasks (READY -> In progress -> Done and Done -> In progress) "
            "and posts 3-part handoff comments on the parent Task so PM transitions the parent Task."
        ),
        "default_story_points": 1.5,
        "default_estimated_hours_per_screen": 6.0,
        "skill_name": "op-role-fe",
        "skill_relative_path": ".agents/skills/op-role-fe/SKILL.md",
        "owned_tiers": [
            "Tier 3: Sub-task [FE] (type_id=8)",
            "Tier 3: Sub-task [Bug] assigned to FE (type_id=8, 0 SP)",
        ],
        "can_create_epic_or_task": False,
        "can_delete_epic_or_task": False,
        "can_transition_epic_or_task": False,
        "can_close_epic_or_task": False,
        "allowed_epic_transitions": [],
        "allowed_task_transitions": [],
        "allowed_subtask_transitions": [
            "READY (1) -> In progress (7) [Start Work]",
            "In progress (7) -> Done (12) [Complete Task]",
            "Done (12) -> In progress (7) [Reopen Task — Rework / UI Fix]",
        ],
        "recommended_tools": [
            "op_get_role_context",
            "op_list_work_packages",
            "op_get_work_package",
            "op_list_subtasks",
            "op_update_work_package",
            "op_log_time_entry",
            "op_add_work_package_comment",
        ],
    },
    "TESTER": {
        "role": "TESTER",
        "title": "QA / Tester Engineer",
        "member_name": "Vinh (Tester) Lương Duy",
        "full_name_vi": "Lương Duy Vinh",
        "user_id": 8,
        "email": "vinhluong2894@gmail.com",
        "login": "vinhluong2894@gmail.com",
        "subtask_prefix": "[Tester]",
        "weight_percent": 35,
        "weight_ratio": "35% (3.5 SP / 10 SP screen = 14h standard effort) + [Bug] Sub-tasks (0 SP)",
        "description": (
            "Owns Tier 3 [Tester] Sub-tasks (type_id=8, 35% weight = 3.5 SP / 14h per screen), creates [Bug] Sub-tasks (0 SP) "
            "assigned to BE (6) or FE (7), reopens cross-role Sub-tasks (Done -> In progress) for QA verification, "
            "and posts 3-part handoff comments on the parent Task so PM transitions the parent Task."
        ),
        "default_story_points": 3.5,
        "default_estimated_hours_per_screen": 14.0,
        "skill_name": "op-role-tester",
        "skill_relative_path": ".agents/skills/op-role-tester/SKILL.md",
        "owned_tiers": [
            "Tier 3: Sub-task [Tester] (type_id=8)",
            "Tier 3: Sub-task [Bug] creator & verifier (type_id=8, 0 SP)",
        ],
        "can_create_epic_or_task": False,
        "can_delete_epic_or_task": False,
        "can_transition_epic_or_task": False,
        "can_close_epic_or_task": False,
        "allowed_epic_transitions": [],
        "allowed_task_transitions": [],
        "allowed_subtask_transitions": [
            "READY (1) -> In progress (7) [Start Work]",
            "In progress (7) -> Done (12) [Complete Task / Verify Bug]",
            "Done (12) -> In progress (7) [Reopen Task — QA Post-Check]",
        ],
        "recommended_tools": [
            "op_get_role_context",
            "op_list_work_packages",
            "op_get_work_package",
            "op_list_subtasks",
            "op_create_work_package",
            "op_update_work_package",
            "op_log_time_entry",
            "op_add_work_package_comment",
        ],
    },
}

_ROLE_ALIAS_MAP: Dict[str, str] = {
    "pm": "PM",
    "project_manager": "PM",
    "project manager": "PM",
    "scrum_master": "PM",
    "scrum master": "PM",
    "sm": "PM",
    "manager": "PM",
    "nghĩa": "PM",
    "nghia": "PM",
    "nguyễn trung nghĩa": "PM",
    "nguyen trung nghia": "PM",
    "nghĩa nguyễn trung": "PM",
    "nghia nguyen trung": "PM",
    "nghia2592005@gmail.com": "PM",
    "nghia2592005": "PM",
    "4": "PM",
    "ba": "BA",
    "business_analyst": "BA",
    "business analyst": "BA",
    "analyst": "BA",
    "trung": "BA",
    "nguyễn vĩnh trung": "BA",
    "nguyen vinh trung": "BA",
    "trung (ba) nguyễn vĩnh": "BA",
    "trung (ba) nguyen vinh": "BA",
    "nguyenvinhtrung0509@gmail.com": "BA",
    "nguyenvinhtrung0509": "BA",
    "trungnv.ba@stu.ptit.edu.vn": "BA",
    "5": "BA",
    "be": "BE",
    "backend": "BE",
    "dev_be": "BE",
    "back-end": "BE",
    "hiếu": "BE",
    "hieu": "BE",
    "vũ quốc hiếu": "BE",
    "vu quoc hieu": "BE",
    "hiếu (be) vũ quốc": "BE",
    "hieu (be) vu quoc": "BE",
    "hiếu vũ": "BE",
    "hieu vu": "BE",
    "hieubao189@gmail.com": "BE",
    "hieubao189": "BE",
    "hieuvq.be@stu.ptit.edu.vn": "BE",
    "6": "BE",
    "fe": "FE",
    "frontend": "FE",
    "dev_fe": "FE",
    "front-end": "FE",
    "thành": "FE",
    "thanh": "FE",
    "bùi tuấn thành": "FE",
    "bui tuan thanh": "FE",
    "thành (fe) bùi tuấn": "FE",
    "thanh (fe) bui tuan": "FE",
    "buituanthanh02@gmail.com": "FE",
    "buituanthanh02": "FE",
    "thanhbt.fe@stu.ptit.edu.vn": "FE",
    "7": "FE",
    "tester": "TESTER",
    "qa": "TESTER",
    "qc": "TESTER",
    "test": "TESTER",
    "vinh": "TESTER",
    "lương duy vinh": "TESTER",
    "luong duy vinh": "TESTER",
    "vinh (tester) lương duy": "TESTER",
    "vinh (tester) luong duy": "TESTER",
    "vinh luong": "TESTER",
    "vinh lương": "TESTER",
    "vinhluong2894@gmail.com": "TESTER",
    "vinhluong2894": "TESTER",
    "vinhld.qa@stu.ptit.edu.vn": "TESTER",
    "8": "TESTER",
    "auto": "AUTO",
}

_ORDERED_PHRASE_ALIASES: tuple[tuple[str, str], ...] = (
    ("nghia2592005@gmail.com", "PM"),
    ("nguyenvinhtrung0509@gmail.com", "BA"),
    ("hieubao189@gmail.com", "BE"),
    ("buituanthanh02@gmail.com", "FE"),
    ("vinhluong2894@gmail.com", "TESTER"),
    ("trungnv.ba@stu.ptit.edu.vn", "BA"),
    ("hieuvq.be@stu.ptit.edu.vn", "BE"),
    ("thanhbt.fe@stu.ptit.edu.vn", "FE"),
    ("vinhld.qa@stu.ptit.edu.vn", "TESTER"),
    ("nguyễn trung nghĩa", "PM"),
    ("nguyen trung nghia", "PM"),
    ("nghĩa nguyễn trung", "PM"),
    ("nghia nguyen trung", "PM"),
    ("nguyễn vĩnh trung", "BA"),
    ("nguyen vinh trung", "BA"),
    ("trung (ba) nguyễn vĩnh", "BA"),
    ("trung (ba) nguyen vinh", "BA"),
    ("vũ quốc hiếu", "BE"),
    ("vu quoc hieu", "BE"),
    ("hiếu (be) vũ quốc", "BE"),
    ("hieu (be) vu quoc", "BE"),
    ("hiếu vũ", "BE"),
    ("hieu vu", "BE"),
    ("bùi tuấn thành", "FE"),
    ("bui tuan thanh", "FE"),
    ("thành (fe) bùi tuấn", "FE"),
    ("thanh (fe) bui tuan", "FE"),
    ("lương duy vinh", "TESTER"),
    ("luong duy vinh", "TESTER"),
    ("vinh (tester) lương duy", "TESTER"),
    ("vinh (tester) luong duy", "TESTER"),
    ("vinh luong", "TESTER"),
    ("vinh lương", "TESTER"),
    ("project manager", "PM"),
    ("scrum master", "PM"),
    ("business analyst", "BA"),
    ("back-end", "BE"),
    ("front-end", "FE"),
)

_ORDERED_TOKEN_ALIASES: tuple[tuple[str, str], ...] = (
    ("pm", "PM"),
    ("ba", "BA"),
    ("be", "BE"),
    ("fe", "FE"),
    ("tester", "TESTER"),
    ("qa", "TESTER"),
    ("qc", "TESTER"),
    ("nghĩa", "PM"),
    ("nghia", "PM"),
    ("trung", "BA"),
    ("hiếu", "BE"),
    ("hieu", "BE"),
    ("thành", "FE"),
    ("thanh", "FE"),
    ("vinh", "TESTER"),
    ("backend", "BE"),
    ("frontend", "FE"),
    ("analyst", "BA"),
    ("manager", "PM"),
    ("auto", "AUTO"),
)


def _match_role_by_phrases_or_tokens(cleaned: str) -> Optional[str]:
    """Match a lowercase input string against exact aliases, multi-word phrases, or whole word tokens."""
    if cleaned in _ROLE_ALIAS_MAP:
        return _ROLE_ALIAS_MAP[cleaned]
    for phrase, mapped in _ORDERED_PHRASE_ALIASES:
        if phrase in cleaned:
            return mapped
    tokens = set(re.findall(r"\w+", cleaned))
    for token_key, mapped in _ORDERED_TOKEN_ALIASES:
        if token_key in tokens:
            return mapped
    return None


def normalize_member_role(val: Optional[str], default: str = "AUTO", strict: bool = False) -> str:
    """Normalize a role code, alias, or member name into ('PM', 'BA', 'BE', 'FE', 'TESTER', 'AUTO')."""
    if val is None or str(val).strip() == "":
        return default
    cleaned = str(val).strip().lower()
    matched = _match_role_by_phrases_or_tokens(cleaned)
    if matched is not None:
        return matched
    if strict:
        raise ValueError(
            f"Invalid member role '{val}'. Valid roles are: PM, BA, BE, FE, TESTER, or AUTO."
        )
    return default


def detect_role_from_user_dict(user: Optional[Dict[str, Any]]) -> Optional[str]:
    """Infer the QLDAPM team role ('PM', 'BA', 'BE', 'FE', 'TESTER') from an OpenProject /api/v3/users/me payload."""
    if not isinstance(user, dict):
        return None
    uid = user.get("id")
    if uid is not None and str(uid) in ("4", "5", "6", "7", "8"):
        return _ROLE_ALIAS_MAP[str(uid)]

    combined = " ".join(
        str(user.get(field) or "")
        for field in ("login", "email", "name", "firstName", "lastName")
    ).strip().lower()
    if not combined:
        return None
    matched = _match_role_by_phrases_or_tokens(combined)
    if matched in ROLE_PROFILES:
        return matched
    return None


def resolve_member_user_id(identifier: Any, active_role: str = "PM") -> Optional[int | str]:
    """
    Resolve an assignee/user reference ('me', 'tôi', 'PM', 'BA', 'BE', 'FE', 'TESTER',
    'Nghĩa', 'Trung', 'Hiếu', 'Thành', 'Vinh', or numeric user_id) to an OpenProject user_id.
    """
    if identifier is None:
        return None
    if isinstance(identifier, int):
        return identifier
    raw = str(identifier).strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)

    low = raw.lower()
    if low in ("none", "null", "unassigned"):
        return "unassigned"

    if low in ("me", "tôi", "toi", "my", "mine", "của tôi", "cua toi", "self", "default", "current_role", "active_role"):
        role_key = active_role if active_role in ROLE_PROFILES else "PM"
        return int(ROLE_PROFILES[role_key]["user_id"])

    matched_role = _match_role_by_phrases_or_tokens(low)
    if matched_role in ROLE_PROFILES:
        return int(ROLE_PROFILES[matched_role]["user_id"])

    return None


def get_role_profile(role_code: str) -> Dict[str, Any]:
    """Return a rich copy of a role's profile with resolved workspace paths."""
    norm = normalize_member_role(role_code, default="PM")
    if norm not in ROLE_PROFILES:
        norm = "PM"
    profile = dict(ROLE_PROFILES[norm])
    workspace_root = Path(__file__).resolve().parent.parent
    abs_skill = (workspace_root / profile["skill_relative_path"]).resolve()
    profile["skill_absolute_path"] = str(abs_skill).replace("\\", "/")
    profile["agents_md_path"] = str((workspace_root / "AGENTS.md").resolve()).replace("\\", "/")
    return profile


def _load_env_files() -> None:
    """Search and load .env from current dir, package dir, mcp_qldapm dir, or workspace root."""
    pkg_dir = Path(__file__).resolve().parent
    workspace_root = pkg_dir.parent
    candidates = [
        Path.cwd() / ".env",
        pkg_dir / ".env",
        workspace_root / ".env",
        workspace_root / "mcp_qldapm" / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            load_dotenv(dotenv_path=env_path, override=False)


@dataclass
class OpenProjectConfig:
    """Runtime configuration and security policies for the OpenProject MCP Server."""

    base_url: str = ""
    api_key: str = ""
    oauth_bearer_token: str = ""
    default_project_id: Optional[str] = None
    member_role: str = "AUTO"

    # Security & Boundary Guardrails (inspired by jtauschl/openproject-ce-mcp)
    read_only: bool = False
    enable_delete_tools: bool = True
    enable_admin_tools: bool = True
    sanitize_untrusted_content: bool = True

    # Project Allowlists: '*' allows all, or comma-separated IDs/identifiers/glob patterns
    read_projects_allowlist: List[str] = field(default_factory=lambda: ["*"])
    write_projects_allowlist: List[str] = field(default_factory=lambda: ["*"])

    # HTTP & Pagination settings
    timeout_seconds: float = 30.0
    max_retries: int = 3
    default_page_size: int = 50
    max_page_size: int = 200
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        self.member_role = normalize_member_role(self.member_role, default="AUTO")

    @classmethod
    def from_env(cls) -> "OpenProjectConfig":
        _load_env_files()

        base_url = (
            os.getenv("OPENPROJECT_URL")
            or os.getenv("OPENPROJECT_BASE_URL")
            or "http://localhost:8080"
        ).rstrip("/")

        api_key = (
            os.getenv("OPENPROJECT_API_KEY")
            or os.getenv("OPENPROJECT_API_TOKEN")
            or ""
        ).strip()

        oauth_token = os.getenv("OPENPROJECT_OAUTH_TOKEN", "").strip()
        default_proj = os.getenv("OPENPROJECT_PROJECT_ID") or os.getenv("OPENPROJECT_DEFAULT_PROJECT")
        raw_role = (
            os.getenv("OPENPROJECT_MEMBER_ROLE")
            or os.getenv("OPENPROJECT_ROLE")
            or "AUTO"
        )

        def _parse_bool(val: Optional[str], default: bool) -> bool:
            if val is None or val.strip() == "":
                return default
            return val.strip().lower() in ("1", "true", "yes", "on")

        def _parse_allowlist(val: Optional[str]) -> List[str]:
            if not val or not val.strip():
                return ["*"]
            return [item.strip() for item in val.split(",") if item.strip()]

        return cls(
            base_url=base_url,
            api_key=api_key,
            oauth_bearer_token=oauth_token,
            default_project_id=str(default_proj).strip() if default_proj else None,
            member_role=normalize_member_role(raw_role, default="AUTO"),
            read_only=_parse_bool(os.getenv("OPENPROJECT_READ_ONLY"), False),
            enable_delete_tools=_parse_bool(os.getenv("OPENPROJECT_ENABLE_DELETE_TOOLS"), True),
            enable_admin_tools=_parse_bool(os.getenv("OPENPROJECT_ENABLE_ADMIN_TOOLS"), True),
            sanitize_untrusted_content=_parse_bool(
                os.getenv("OPENPROJECT_SANITIZE_UNTRUSTED"), True
            ),
            read_projects_allowlist=_parse_allowlist(os.getenv("OPENPROJECT_READ_PROJECTS")),
            write_projects_allowlist=_parse_allowlist(os.getenv("OPENPROJECT_WRITE_PROJECTS")),
            timeout_seconds=float(os.getenv("OPENPROJECT_TIMEOUT", "30.0")),
            max_retries=int(os.getenv("OPENPROJECT_MAX_RETRIES", "3")),
            default_page_size=int(os.getenv("OPENPROJECT_DEFAULT_PAGE_SIZE", "50")),
            max_page_size=int(os.getenv("OPENPROJECT_MAX_PAGE_SIZE", "200")),
            verify_ssl=_parse_bool(os.getenv("OPENPROJECT_VERIFY_SSL"), True),
        )

    def is_project_allowed(self, project_ref: Optional[str | int], write: bool = False) -> bool:
        """Check whether reading or mutating a specific project is permitted by allowlists."""
        if write and self.read_only:
            return False
        if project_ref is None:
            return True
        ref_str = str(project_ref).strip()
        patterns = self.write_projects_allowlist if write else self.read_projects_allowlist
        for pattern in patterns:
            if pattern == "*" or fnmatch.fnmatch(ref_str.lower(), pattern.lower()):
                return True
        return False

