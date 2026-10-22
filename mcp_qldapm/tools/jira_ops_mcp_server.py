# -*- coding: utf-8 -*-
"""
Jira, OpenProject & DevOps MCP Server (Dual-Mode: Stdio JSON-RPC 2.0 & CLI Demo)
Môn học: Quản lý Dự án Phần mềm (INT1450) — Học viện Công nghệ Bưu chính Viễn thông (PTIT)
Giải mã kiến trúc: AI -> MCP -> { Jira / OpenProject / Ops } -> Dev update task status

Tính năng cốt lõi:
1. Tích hợp chuẩn giao thức Model Context Protocol (MCP JSON-RPC 2.0 over Stdio) không phụ thuộc thư viện ngoài,
   đồng thời tương thích hoàn toàn với FastMCP SDK nếu môi trường đã cài đặt.
2. Thực thi quy chế Workflow 3 tầng thích nghi linh hoạt:
   - Epic (4 trạng thái): TO DO -> IN PROGRESS -> IN REVIEW -> Done (Approve & Close).
   - Parent Task (8 trạng thái & phân nhánh linh hoạt): TO DO -> BA IN PROGRESS (hoặc nhảy thẳng DEV IN PROGRESS qua 'Start Work') ->
     BA REVIEW (có thể đóng thẳng Done qua 'Complete Task' cho task tài liệu, hoặc sang DEV IN PROGRESS qua 'Approve & Start Dev') ->
     READY FOR TEST ('Submit for Review') -> TESTING ('Start Testing') <-> REWORK ('Reject / Report Bug') -> Done ('Pass & Complete').
   - Sub-task (3 trạng thái tinh gọn): TO DO -('Start Work')-> IN PROGRESS -('Complete Task')-> Done -('Reopen Task')-> IN PROGRESS.
3. Tích hợp Guardrails kiểm soát chất lượng & Restrictions:
   - Rule 1: Tự động kéo Parent Task từ TESTING về REWORK khi tạo Sub-task [Bug].
   - Rule 2 (Child Blocking Condition): Khóa chuyển trạng thái Parent Task / Epic sang Done nếu còn bất kỳ Sub-task / Child Task nào chưa Done.
4. Hỗ trợ Multi-Provider Adapter: Kết nối cả Jira Cloud REST API v3 và OpenProject REST API v3 (HAL+JSON).
"""

import os
import sys
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from requests.auth import HTTPBasicAuth

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def load_env_file() -> None:
    """Tự động nạp biến môi trường từ file .env ở thư mục gốc dự án (Zero-dependency dotenv loader)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key:
            os.environ[key] = val


load_env_file()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://nghianguyxn259.atlassian.net").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "SCRUM")

OPENPROJECT_URL = os.getenv("OPENPROJECT_URL", "http://26.65.103.140/").rstrip("/")
OPENPROJECT_API_KEY = os.getenv("OPENPROJECT_API_KEY", "")
OPENPROJECT_PROJECT_ID = int(os.getenv("OPENPROJECT_PROJECT_ID", "3"))

AUTH = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

OP_AUTH = HTTPBasicAuth("apikey", OPENPROJECT_API_KEY)
OP_HEADERS = {"Content-Type": "application/json", "Accept": "application/hal+json"}
OP_STATUS_NAME_TO_ID = {
    "TO DO": 1,
    "NEW": 1,
    "IN PROGRESS": 7,
    "IN_PROGRESS": 7,
    "BA IN PROGRESS": 18,
    "BA REVIEW": 19,
    "DEV IN PROGRESS": 17,
    "READY FOR TEST": 10,
    "TESTING": 9,
    "REWORK": 14,
    "IN REVIEW": 20,
    "DONE": 12,
    "CLOSED": 12,
}
OP_TYPE_NAME_TO_ID = {
    "EPIC": 5,
    "TASK": 1,
    "SUBTASK": 8,
    "SUB-TASK": 8,
}


def _resolve_op_status_id(status_val: Any) -> int:
    """Ánh xạ tên trạng thái hoặc mã số sang Status ID thực tế trên OpenProject (có đồng bộ động từ API)."""
    if isinstance(status_val, int):
        return status_val
    s_clean = str(status_val).strip()
    if s_clean.isdigit():
        return int(s_clean)
    upper_key = s_clean.upper()
    if upper_key in OP_STATUS_NAME_TO_ID:
        return OP_STATUS_NAME_TO_ID[upper_key]
    try:
        r = requests.get(f"{OPENPROJECT_URL}/api/v3/statuses", auth=OP_AUTH, headers=OP_HEADERS, timeout=5)
        if r.status_code == 200:
            for el in r.json().get("_embedded", {}).get("elements", []):
                if el.get("name", "").strip().upper() == upper_key:
                    OP_STATUS_NAME_TO_ID[upper_key] = int(el["id"])
                    return int(el["id"])
    except Exception:
        pass
    return 7


def _build_adf_comment(text: str) -> Dict[str, Any]:
    """Đóng gói chuỗi văn bản thành chuẩn Atlassian Document Format (ADF) v1."""
    return {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": text}],
                }
            ],
        }
    }


def get_my_assigned_tasks(role_or_query: str = "ALL", include_done: bool = False) -> List[Dict[str, Any]]:
    """
    Lấy danh sách các task/subtask trong dự án theo vai trò ([PM], [BA], [BE], [FE], [Tester], [Bug])
    hoặc theo JQL assignee.
    """
    status_clause = "" if include_done else " AND status != DONE"
    role_clean = role_or_query.strip().upper()
    role_prefix_map = {
        "PM": "[PM]",
        "BA": "[BA]",
        "BE": "[BE]",
        "FE": "[FE]",
        "TEST": "[Tester]",
        "TESTER": "[Tester]",
        "BUG": "[Bug]",
    }

    if role_clean in role_prefix_map:
        prefix = role_prefix_map[role_clean]
        jql = f'project = {JIRA_PROJECT_KEY} AND summary ~ "\\"{prefix}\\""{status_clause} ORDER BY key ASC'
    elif role_clean in ("ALL", "*"):
        jql = f"project = {JIRA_PROJECT_KEY}{status_clause} ORDER BY key ASC"
    elif role_or_query == "currentUser()":
        jql = f"project = {JIRA_PROJECT_KEY} AND assignee = currentUser(){status_clause} ORDER BY key ASC"
    else:
        jql = f'project = {JIRA_PROJECT_KEY} AND summary ~ "\\"{role_or_query}\\""{status_clause} ORDER BY key ASC'

    url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    params = {
        "jql": jql,
        "maxResults": 50,
        "fields": "key,summary,status,duedate,issuetype,parent,assignee",
    }
    r = requests.get(url, auth=AUTH, headers=HEADERS, params=params, timeout=15)
    if r.status_code != 200:
        return [{"error": f"HTTP {r.status_code}: {r.text}"}]

    issues = r.json().get("issues", [])
    result = []
    for i in issues:
        fields = i.get("fields", {})
        result.append(
            {
                "key": i.get("key"),
                "type": fields.get("issuetype", {}).get("name"),
                "summary": fields.get("summary"),
                "status": fields.get("status", {}).get("name"),
                "due_date": fields.get("duedate"),
                "parent_key": fields.get("parent", {}).get("key"),
                "assignee": (fields.get("assignee") or {}).get("displayName", "Unassigned"),
            }
        )
    return result


def _check_subtasks_before_done(issue_key: str) -> Optional[str]:
    """
    Guardrail Rule 2: Kiểm tra xem một Parent Task có còn Sub-task nào chưa DONE hay không.
    Nếu còn Sub-task chưa DONE, chặn không cho đóng Parent Task.
    """
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}?fields=issuetype,subtasks"
    r = requests.get(url, auth=AUTH, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return None
    fields = r.json().get("fields", {})
    subtasks = fields.get("subtasks", [])
    if not subtasks:
        return None

    incomplete = []
    for st in subtasks:
        st_key = st.get("key")
        st_status = st.get("fields", {}).get("status", {}).get("name", "").upper()
        st_summary = st.get("fields", {}).get("summary", "")
        if st_status not in ("DONE", "HOÀN THÀNH", "CLOSED"):
            incomplete.append(f"{st_key} ({st_status}: {st_summary})")

    if incomplete:
        return (
            f"⛔ [WORKFLOW GUARDRAIL - RULE 2]: Bị chặn! Không thể chuyển Task lớn {issue_key} sang 'DONE' "
            f"vì còn {len(incomplete)} Sub-task chưa hoàn thành: {'; '.join(incomplete)}"
        )
    return None


def update_task_status(
    issue_key: str,
    target_status: str,
    comment_text: Optional[str] = None,
    sync_parent_status: Optional[str] = None,
) -> str:
    """
    Tự động chuyển trạng thái của Task hoặc Sub-task trên Jira theo Workflow 2 tầng,
    kèm kiểm tra Guardrail Rule 2 và tự động đồng bộ trạng thái Parent Task nếu được yêu cầu.
    """
    target_clean = target_status.strip().upper()

    # Kiểm tra Guardrail Rule 2 nếu mục tiêu là đóng Task lớn / Epic sang Done
    if target_clean in ("DONE", "PASS & COMPLETE", "COMPLETE TASK", "APPROVE & CLOSE"):
        block_msg = _check_subtasks_before_done(issue_key)
        if block_msg:
            return block_msg

    # 1. Lấy danh sách transitions khả dụng của issue
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/transitions"
    r = requests.get(url, auth=AUTH, headers=HEADERS, timeout=15)
    if r.status_code != 200:
        return f"Lỗi lấy transitions cho {issue_key}: HTTP {r.status_code} - {r.text}"

    transitions = r.json().get("transitions", [])
    matching_transition = None
    for t in transitions:
        to_name = t.get("to", {}).get("name", "").strip().upper()
        trans_name = t.get("name", "").strip().upper()
        if to_name == target_clean or trans_name == target_clean:
            matching_transition = t
            break

    if not matching_transition:
        available = [f"'{t.get('name')}' -> {t.get('to', {}).get('name')}" for t in transitions]
        return (
            f"Không tìm thấy bước chuyển sang '{target_status}' cho {issue_key}. "
            f"Các bước chuyển khả dụng hiện tại: {', '.join(available)}"
        )

    # 2. Thực hiện chuyển trạng thái
    payload = {"transition": {"id": matching_transition["id"]}}
    res = requests.post(url, auth=AUTH, headers=HEADERS, json=payload, timeout=15)
    if res.status_code not in (200, 204):
        return f"Thất bại khi chuyển trạng thái {issue_key}: HTTP {res.status_code} - {res.text}"

    final_status_name = matching_transition.get("to", {}).get("name", target_status)
    msg = f"✅ Đã chuyển thành công {issue_key} sang trạng thái '{final_status_name}'."

    # 3. Thêm comment giải trình tự động nếu có
    if comment_text:
        c_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
        c_payload = _build_adf_comment(f"🤖 [AI-Agent MCP Auto]: {comment_text}")
        requests.post(c_url, auth=AUTH, headers=HEADERS, json=c_payload, timeout=15)
        msg += " (Đã ghi nhận comment báo cáo tiến độ)."

    # 4. Tự động đồng bộ trạng thái Parent Task nếu có yêu cầu (ví dụ Subtask IN PROGRESS -> Parent DEV IN PROGRESS)
    if sync_parent_status:
        issue_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}?fields=parent"
        ir = requests.get(issue_url, auth=AUTH, headers=HEADERS, timeout=15)
        if ir.status_code == 200:
            parent_key = ir.json().get("fields", {}).get("parent", {}).get("key")
            if parent_key:
                parent_res = update_task_status(
                    issue_key=parent_key,
                    target_status=sync_parent_status,
                    comment_text=f"Tự động đồng bộ trạng thái từ Sub-task {issue_key} ({final_status_name}).",
                )
                msg += f" | Đồng bộ Parent ({parent_key}): {parent_res}"

    return msg


def log_work_time(
    issue_key: str,
    hours: float,
    description: str = "Thực hiện lập trình, kiểm thử & hoàn thiện tính năng",
) -> str:
    """Ghi nhận số giờ làm việc thực tế (Time Tracking Worklog) vào Jira Issue."""
    if hours <= 0:
        return "Số giờ làm việc phải lớn hơn 0."

    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/worklog"
    h = int(hours)
    m = int(round((hours - h) * 60))
    if m == 60:
        h += 1
        m = 0
    time_str = f"{h}h {m}m" if (h > 0 and m > 0) else (f"{h}h" if h > 0 else f"{m}m")

    payload = {
        "timeSpent": time_str,
        "comment": _build_adf_comment(f"🤖 [AI-Agent Auto Worklog]: {description}")["body"],
    }
    r = requests.post(url, auth=AUTH, headers=HEADERS, json=payload, timeout=15)
    if r.status_code == 201:
        return f"✅ Đã ghi nhận thành công {time_str} ({hours:.2f} giờ) vào task {issue_key}."
    return f"Lỗi ghi nhận worklog cho {issue_key}: HTTP {r.status_code} - {r.text}"


def create_bug_subtask(
    parent_key: str,
    bug_title: str,
    error_detail: str,
    severity: str = "Major",
    assignee_role: str = "BE",
) -> str:
    """
    Tự động tạo Sub-task [Bug] khi kiểm thử hoặc CI/CD phát hiện lỗi,
    đồng thời kích hoạt Rule 1: Tự động kéo Parent Task từ TESTING về REWORK.
    """
    p_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{parent_key}?fields=project,status,summary"
    pr = requests.get(p_url, auth=AUTH, headers=HEADERS, timeout=15)
    if pr.status_code != 200:
        return f"Không tìm thấy Parent Task {parent_key}: HTTP {pr.status_code}"

    p_data = pr.json().get("fields", {})
    project_id = p_data.get("project", {}).get("id")
    parent_status = p_data.get("status", {}).get("name", "").upper()

    role_tag = assignee_role.strip().upper()
    sev_tag = severity.strip().capitalize()
    full_summary = f"[Bug] ({role_tag} - {sev_tag}) {bug_title}"

    url = f"{JIRA_BASE_URL}/rest/api/3/issue"
    payload = {
        "fields": {
            "project": {"id": project_id},
            "parent": {"key": parent_key},
            "issuetype": {"name": "Sub-task"},
            "summary": full_summary,
            "description": _build_adf_comment(
                f"🐞 Báo cáo lỗi tự động từ hệ thống QA / CI-CD Ops:\n"
                f"- Phân loại: {role_tag} | Mức độ nghiêm trọng: {sev_tag}\n"
                f"- Chi tiết lỗi: {error_detail}"
            )["body"],
        }
    }
    r = requests.post(url, auth=AUTH, headers=HEADERS, json=payload, timeout=15)
    if r.status_code != 201:
        return f"Lỗi tạo Bug Sub-task: HTTP {r.status_code} - {r.text}"

    new_bug_key = r.json().get("key")
    msg = f"✅ Đã tạo Bug Sub-task thành công: {new_bug_key} ('{full_summary}') thuộc {parent_key}."

    # Kích hoạt Automation Rule 1: CHỈ KHI Parent đang ở trạng thái TESTING -> tự động kéo về REWORK
    if parent_status == "TESTING":
        rework_res = update_task_status(
            issue_key=parent_key,
            target_status="REWORK",
            comment_text=f"Kích hoạt Rule 1: Phát hiện lỗi mới {new_bug_key} ({full_summary}). Yêu cầu {role_tag} xử lý.",
        )
        msg += f" | 🔄 [Rule 1 Auto-Rework]: {rework_res}"
    else:
        msg += f" | ℹ️ [Rule 1]: Parent {parent_key} đang ở '{parent_status}' (không phải TESTING) nên giữ nguyên trạng thái."

    return msg


def ops_sync_git_commit(
    issue_key: str,
    commit_hash: str,
    branch_name: str,
    commit_message: str = "",
    ci_status: str = "PASS",
) -> str:
    """Đồng bộ thông tin Git Commit, Branch và kết quả CI/CD Pipeline vào Jira Issue."""
    c_url = f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment"
    badge = "✅ CI/CD PASS" if ci_status.upper() == "PASS" else "❌ CI/CD FAIL"
    text = (
        f"🔗 [DevOps Git & CI/CD Sync]\n"
        f"• Branch: {branch_name}\n"
        f"• Commit: {commit_hash} — {commit_message}\n"
        f"• Pipeline Status: {badge}"
    )
    res = requests.post(c_url, auth=AUTH, headers=HEADERS, json=_build_adf_comment(text), timeout=15)
    if res.status_code == 201:
        return f"✅ Đã đồng bộ Git commit {commit_hash} ({branch_name}) vào {issue_key}."
    return f"Lỗi đồng bộ Git commit: HTTP {res.status_code} - {res.text}"


# Bản đồ AccountId thực tế của 5 thành viên nhóm trên Jira Cloud (Project SCRUM)
JIRA_ROLE_TO_ACCOUNT_ID = {
    "PM": "712020:defb4efc-c68f-4249-8723-5ca71f0c4ebf",      # Nguyễn Trung Nghĩa
    "BA": "712020:0837b9cd-2d60-4a63-9089-cb90587a1b77",      # Nguyễn Vĩnh Trung
    "BE": "712020:4c0c3941-8ba6-4d3a-bdc6-7127d5895c47",      # Vũ Quốc Hiếu
    "FE": "712020:9860960f-f481-4267-8ad8-ced0537bfe87",      # Bùi Tuấn Thành
    "TEST": "712020:0e01fa66-ef3d-452c-bc39-a60c98e4a85c",    # Lương Duy Vinh
    "TESTER": "712020:0e01fa66-ef3d-452c-bc39-a60c98e4a85c",  # Lương Duy Vinh
}

# Bản đồ User ID thực tế của 5 thành viên nhóm trên OpenProject (Project QLDAPM id=3)
OP_ROLE_TO_USER_ID = {
    "PM": 5,      # Nguyễn Trung Nghĩa
    "BE": 6,      # Vũ Quốc Hiếu
    "FE": 7,      # Bùi Tuấn Thành
    "TESTER": 8,  # Lương Duy Vinh
    "BA": 9,      # Nguyễn Vĩnh Trung
}


def mcp_configure_workflow(provider: str = "both") -> str:
    """
    MCP Tool Thiết lập, Đồng bộ & Kiểm tra Workflow 3 tầng (Epic, Parent Task, Sub-task)
    kèm các chốt chặn Guardrail (Rule 1 Auto-Rework & Rule 2 Child Blocking) trên Jira Cloud và OpenProject.
    """
    prov = provider.strip().lower()
    report_lines = [
        "⚙️ [MCP WORKFLOW ENGINE] KIỂM TRA & ĐỒNG BỘ QUY TRÌNH WORKFLOW 3 TẦNG (JIRA CLOUD & OPENPROJECT):",
        "  • Tầng 1 - Epic (4 trạng thái): TO DO -> IN PROGRESS -> IN REVIEW -> Done (Khóa Child Blocking).",
        "  • Tầng 2 - Parent Task (8 trạng thái + 2 nhánh tắt): TO DO -> BA IN PROGRESS -> BA REVIEW -> DEV IN PROGRESS -> READY FOR TEST -> TESTING <-> REWORK -> Done.",
        "  • Tầng 3 - Sub-task (3 trạng thái): TO DO -> IN PROGRESS -> Done (Chỉ Assignee, PM Nghĩa, Tester Vinh được quyền chuyển).",
        "  • Guardrail Rule 1 (Auto-Rework): Khi tạo Sub-task [Bug], tự động kéo Parent Task từ TESTING về REWORK (Jira) / In progress (OpenProject).",
        "  • Guardrail Rule 2 (Child Blocking): Chặn đóng Parent Task / Epic sang Done/Closed nếu còn bất kỳ Sub-task con nào chưa hoàn thành.",
    ]

    if prov in ("both", "jira"):
        r_stat = requests.get(
            f"{JIRA_BASE_URL}/rest/api/3/project/{JIRA_PROJECT_KEY}/statuses", auth=AUTH, headers=HEADERS, timeout=10
        )
        if r_stat.status_code == 200:
            by_type = [f"{t['name']}: {[s['name'] for s in t.get('statuses', [])]}" for t in r_stat.json()]
            report_lines.append(
                f"  ✅ [Jira Cloud ({JIRA_PROJECT_KEY})] Đã xác thực Workflow theo từng Issue Type: {' | '.join(by_type[:3])}"
            )
        else:
            report_lines.append(f"  ⚠️ [Jira Cloud] Không thể đọc danh sách trạng thái: HTTP {r_stat.status_code}")

    if prov in ("both", "openproject", "op"):
        r_op = requests.get(f"{OPENPROJECT_URL}/api/v3/statuses", auth=OP_AUTH, headers=OP_HEADERS, timeout=10)
        if r_op.status_code == 200:
            els = r_op.json().get("_embedded", {}).get("elements", [])
            op_names = [f"{s['id']}:{s['name']}" for s in els]
            report_lines.append(
                f"  ✅ [OpenProject (Project ID={OPENPROJECT_PROJECT_ID})] Đã đồng bộ {len(op_names)} trạng thái Workflow: {', '.join(op_names)}"
            )
        else:
            report_lines.append(f"  ⚠️ [OpenProject] Không thể đọc danh sách trạng thái: HTTP {r_op.status_code}")

    return "\n".join(report_lines)


def jira_create_subtask(
    parent_key: str,
    role: str,
    title: str,
    start_date: str = "2026-10-23",
    due_date: str = "2026-10-27",
    story_points: float = 3.0,
    description: str = "",
) -> str:
    """
    MCP Tool Tạo mới 1 Sub-task chuyên môn ([BA], [BE], [FE], [Tester], [PM]) dưới Parent Task trên Jira Cloud,
    tự động gán đúng Assignee theo vai trò, gắn Start Date, Due Date và Story Points.
    """
    role_clean = role.strip().upper()
    prefix_map = {"BA": "[BA]", "BE": "[BE]", "FE": "[FE]", "TEST": "[Tester]", "TESTER": "[Tester]", "PM": "[PM]"}
    prefix = prefix_map.get(role_clean, f"[{role_clean}]")
    full_summary = title.strip() if title.strip().startswith("[") else f"{prefix} {title.strip()}"
    acc_id = JIRA_ROLE_TO_ACCOUNT_ID.get(role_clean, JIRA_ROLE_TO_ACCOUNT_ID["PM"])

    desc_text = description or (
        f"Sub-task thuộc {parent_key} | Vai trò: {prefix} | Story Points: {story_points} SP | "
        f"Lịch trình: {start_date} -> {due_date}"
    )

    payload: Dict[str, Any] = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "parent": {"key": parent_key},
            "issuetype": {"id": "10002"},  # Subtask
            "summary": full_summary,
            "description": _build_adf_comment(desc_text)["body"],
            "assignee": {"accountId": acc_id},
            "customfield_10015": start_date,
            "duedate": due_date,
            "customfield_10016": float(story_points),
        }
    }
    r = requests.post(f"{JIRA_BASE_URL}/rest/api/3/issue", auth=AUTH, headers=HEADERS, json=payload, timeout=15)
    if r.status_code == 201:
        new_key = r.json().get("key")
        return f"✅ [Jira] Đã tạo Sub-task {new_key} ('{full_summary}', {story_points} SP, {start_date} -> {due_date}) dưới {parent_key}."
    return f"Lỗi tạo Sub-task trên Jira dưới {parent_key}: HTTP {r.status_code} - {r.text[:250]}"


def jira_create_task(
    summary: str,
    epic_key: str = "SCRUM-195",
    start_date: str = "2026-10-23",
    due_date: str = "2026-10-30",
    story_points: float = 10.0,
    description: str = "",
    auto_create_4_subtasks: bool = False,
) -> str:
    """
    MCP Tool Tạo mới 1 Parent Task (Màn hình chức năng) trên Jira Cloud gắn dưới Epic.
    Nếu bật `auto_create_4_subtasks=True`, tự động sinh luôn 4 Sub-tasks chuẩn ([BA] 30%, [BE] 15%, [FE] 15%, [Tester] 40%)
    và phân công tự động cho 4 thành viên chuyên môn.
    """
    full_summary = summary.strip() if summary.strip().startswith("[") else f"[Màn hình] {summary.strip()}"
    desc_text = description or f"Task màn hình chức năng thuộc Epic {epic_key}. Tổng điểm: {story_points} SP ({start_date} -> {due_date})."

    payload: Dict[str, Any] = {
        "fields": {
            "project": {"key": JIRA_PROJECT_KEY},
            "parent": {"key": epic_key},
            "issuetype": {"id": "10003"},  # Task
            "summary": full_summary,
            "description": _build_adf_comment(desc_text)["body"],
            "assignee": {"accountId": JIRA_ROLE_TO_ACCOUNT_ID["PM"]},
            "customfield_10015": start_date,
            "duedate": due_date,
            "customfield_10016": float(story_points),
        }
    }
    r = requests.post(f"{JIRA_BASE_URL}/rest/api/3/issue", auth=AUTH, headers=HEADERS, json=payload, timeout=15)
    if r.status_code != 201:
        return f"Lỗi tạo Parent Task trên Jira: HTTP {r.status_code} - {r.text[:250]}"

    task_key = r.json().get("key")
    msg_lines = [f"✅ [Jira] Đã tạo Parent Task {task_key}: '{full_summary}' (Epic: {epic_key}, {story_points} SP, {start_date} -> {due_date})."]

    if auto_create_4_subtasks:
        clean_name = summary.replace("[Màn hình]", "").strip()
        sub_defs = [
            ("BA", f"Phân tích & Thiết kế Use Case, luồng nghiệp vụ màn hình {clean_name}", round(story_points * 0.30, 1)),
            ("BE", f"Lập trình RESTful API & Xử lý CSDL cho màn hình {clean_name}", round(story_points * 0.20, 1)),
            ("FE", f"Lập trình Giao diện UI & Ghép nối API màn hình {clean_name}", round(story_points * 0.15, 1)),
            ("TESTER", f"Thiết kế Test Case, Kiểm thử API/UI & Hồi quy màn hình {clean_name}", round(story_points * 0.35, 1)),
        ]
        for role_code, st_title, st_sp in sub_defs:
            sub_res = jira_create_subtask(
                parent_key=task_key,
                role=role_code,
                title=st_title,
                start_date=start_date,
                due_date=due_date,
                story_points=st_sp,
            )
            msg_lines.append(f"   ↳ {sub_res}")

    return "\n".join(msg_lines)


# ==============================================================================
# CÁC HÀM THỰC THI CHO OPENPROJECT REST API V3 (HAL+JSON) — ĐẦY ĐỦ PARITY VỚI JIRA
# ==============================================================================
def openproject_get_assigned_tasks(role_or_query: str = "ALL", include_closed: bool = False) -> List[Dict[str, Any]]:
    """
    Lấy danh sách các Work Packages trên OpenProject theo vai trò ([PM], [BA], [BE], [FE], [Tester], [Bug])
    hoặc từ khóa tìm kiếm.
    """
    if not OPENPROJECT_API_KEY:
        return [{"error": "Chưa cấu hình OPENPROJECT_API_KEY trong file .env"}]

    url = f"{OPENPROJECT_URL}/api/v3/projects/{OPENPROJECT_PROJECT_ID}/work_packages?filters=%5B%5D&pageSize=500"
    r = requests.get(url, auth=OP_AUTH, headers=OP_HEADERS, timeout=15)
    if r.status_code != 200:
        return [{"error": f"HTTP {r.status_code}: {r.text[:200]}"}]

    elements = sorted(r.json().get("_embedded", {}).get("elements", []), key=lambda x: x.get("id", 0))
    role_clean = role_or_query.strip().upper()
    role_prefix_map = {
        "PM": "[PM]",
        "BA": "[BA]",
        "BE": "[BE]",
        "FE": "[FE]",
        "TEST": "[Tester]",
        "TESTER": "[Tester]",
        "BUG": "[Bug]",
    }
    prefix = role_prefix_map.get(role_clean, "" if role_clean in ("ALL", "*") else role_or_query)

    results: List[Dict[str, Any]] = []
    for wp in elements:
        subject = wp.get("subject", "")
        status_title = wp.get("_links", {}).get("status", {}).get("title", "New")
        if not include_closed and status_title.upper() in ("CLOSED", "DONE"):
            continue
        if prefix and prefix.lower() not in subject.lower():
            continue

        parent_href = wp.get("_links", {}).get("parent", {}).get("href") or ""
        parent_id = int(parent_href.rstrip("/").split("/")[-1]) if parent_href else None
        results.append(
            {
                "id": wp.get("id"),
                "type": wp.get("_links", {}).get("type", {}).get("title"),
                "subject": subject,
                "status": status_title,
                "start_date": wp.get("startDate"),
                "due_date": wp.get("dueDate"),
                "sprint": wp.get("_links", {}).get("sprint", {}).get("title"),
                "parent_id": parent_id,
                "assignee": wp.get("_links", {}).get("assignee", {}).get("title", "Unassigned"),
            }
        )
    return results


def _op_check_children_before_closed(wp_id: int) -> Optional[str]:
    """
    Guardrail Rule 2 (OpenProject): Kiểm tra xem một Parent Work Package (Epic / Task màn hình)
    có còn Sub-task con nào chưa Closed hay không. Nếu còn, chặn không cho đóng Parent.
    """
    get_url = f"{OPENPROJECT_URL}/api/v3/work_packages/{wp_id}"
    gr = requests.get(get_url, auth=OP_AUTH, headers=OP_HEADERS, timeout=10)
    if gr.status_code != 200:
        return None

    children_links = gr.json().get("_links", {}).get("children", [])
    if not children_links:
        return None

    incomplete = []
    for ch in children_links:
        ch_href = ch.get("href", "")
        if not ch_href:
            continue
        cr = requests.get(f"{OPENPROJECT_URL}{ch_href}", auth=OP_AUTH, headers=OP_HEADERS, timeout=10)
        if cr.status_code == 200:
            cdata = cr.json()
            c_status = cdata.get("_links", {}).get("status", {}).get("title", "New")
            if c_status.upper() not in ("CLOSED", "DONE"):
                incomplete.append(f"#{cdata.get('id')} ({c_status}: {cdata.get('subject', '')[:45]})")

    if incomplete:
        return (
            f"⛔ [OPENPROJECT GUARDRAIL - RULE 2]: Bị chặn! Không thể chuyển Work Package cha #{wp_id} sang 'Closed' "
            f"vì còn {len(incomplete)} Sub-task con chưa hoàn thành: {'; '.join(incomplete)}"
        )
    return None


def openproject_update_work_package(
    wp_id: int,
    status_id: Any = 7,
    comment: str = "Cập nhật tự động qua AI Agent MCP",
    sync_parent_status: Optional[str] = None,
) -> str:
    """
    Chuyển trạng thái Work Package trên OpenProject qua REST API v3 (HAL+JSON),
    hỗ trợ truyền mã số (1=New, 7=In progress, 12=Closed) hoặc tên trạng thái ('New', 'In progress', 'Closed'),
    tích hợp Guardrail Rule 2 chặn đóng Task cha khi còn Sub-task chưa Closed và tự động đồng bộ Parent.
    """
    if not OPENPROJECT_API_KEY or OPENPROJECT_API_KEY == "your_openproject_api_key_here":
        return "⚠️ Chưa cấu hình OPENPROJECT_API_KEY thực tế trong file .env."

    resolved_status_id = _resolve_op_status_id(status_id)

    # Kiểm tra Guardrail Rule 2 nếu mục tiêu là đóng Work Package sang Done/Closed (status_id == 12)
    if resolved_status_id == 12:
        block_msg = _op_check_children_before_closed(wp_id)
        if block_msg:
            return block_msg

    get_url = f"{OPENPROJECT_URL}/api/v3/work_packages/{wp_id}"
    gr = requests.get(get_url, auth=OP_AUTH, headers=OP_HEADERS, timeout=10)
    if gr.status_code != 200:
        return f"Lỗi đọc Work Package #{wp_id}: HTTP {gr.status_code}"

    wp_data = gr.json()
    lock_version = wp_data.get("lockVersion", 0)
    pct_done = 100 if resolved_status_id == 12 else (0 if resolved_status_id == 1 else 50)

    payload = {
        "lockVersion": lock_version,
        "percentageDone": pct_done,
        "comment": {"raw": f"🤖 [AI-Agent MCP]: {comment}"},
        "_links": {"status": {"href": f"/api/v3/statuses/{resolved_status_id}"}},
    }
    pr = requests.patch(get_url, auth=OP_AUTH, headers=OP_HEADERS, json=payload, timeout=10)
    if pr.status_code != 200:
        return f"Lỗi cập nhật OpenProject #{wp_id}: HTTP {pr.status_code} - {pr.text[:250]}"

    new_status = pr.json().get("_links", {}).get("status", {}).get("title", str(resolved_status_id))
    msg = f"✅ [OpenProject] Đã chuyển Work Package #{wp_id} sang trạng thái '{new_status}' (Tiến độ: {pct_done}%)."

    if sync_parent_status:
        parent_href = wp_data.get("_links", {}).get("parent", {}).get("href") or ""
        if parent_href:
            parent_id = int(parent_href.rstrip("/").split("/")[-1])
            p_res = openproject_update_work_package(
                wp_id=parent_id,
                status_id=sync_parent_status,
                comment=f"Tự động đồng bộ trạng thái từ Sub-task #{wp_id} ({new_status}).",
            )
            msg += f" | Đồng bộ Parent (#{parent_id}): {p_res}"

    return msg


def openproject_create_bug_subtask(
    parent_wp_id: int,
    bug_title: str,
    error_detail: str,
    severity: str = "Major",
    assignee_role: str = "BE",
) -> str:
    """
    Tự động tạo Sub-task [Bug] dưới Parent Work Package trên OpenProject khi phát hiện lỗi,
    đồng thời kích hoạt Rule 1: Tự động kéo Parent Work Package về 'In progress' (status_id=7).
    """
    if not OPENPROJECT_API_KEY:
        return "⚠️ Chưa cấu hình OPENPROJECT_API_KEY trong file .env."

    p_url = f"{OPENPROJECT_URL}/api/v3/work_packages/{parent_wp_id}"
    pr = requests.get(p_url, auth=OP_AUTH, headers=OP_HEADERS, timeout=10)
    if pr.status_code != 200:
        return f"Không tìm thấy Parent Work Package #{parent_wp_id} trên OpenProject: HTTP {pr.status_code}"

    pdata = pr.json()
    role_tag = assignee_role.strip().upper()
    sev_tag = severity.strip().capitalize()
    role_to_user_id = {"PM": 5, "BE": 6, "FE": 7, "TEST": 8, "TESTER": 8, "BA": 9}
    uid = role_to_user_id.get(role_tag, 6)
    prio_id = 9 if sev_tag in ("Critical", "Major") else 8

    full_subject = f"[Bug] ({role_tag} - {sev_tag}) {bug_title}"
    links: Dict[str, Any] = {
        "type": {"href": "/api/v3/types/8"},
        "status": {"href": "/api/v3/statuses/1"},
        "priority": {"href": f"/api/v3/priorities/{prio_id}"},
        "parent": {"href": f"/api/v3/work_packages/{parent_wp_id}"},
        "assignee": {"href": f"/api/v3/users/{uid}"},
    }
    sprint_link = pdata.get("_links", {}).get("sprint", {}).get("href")
    if sprint_link:
        links["sprint"] = {"href": sprint_link}

    payload = {
        "subject": full_subject,
        "description": {
            "format": "markdown",
            "raw": (
                f"🐞 **Báo cáo lỗi tự động từ hệ thống QA / CI-CD Ops (OpenProject)**:\n"
                f"- Phân loại: `{role_tag}` | Mức độ: `{sev_tag}`\n"
                f"- Chi tiết lỗi: {error_detail}"
            ),
        },
        "scheduleManually": True,
        "startDate": pdata.get("startDate"),
        "dueDate": pdata.get("dueDate"),
        "_links": links,
    }
    create_url = f"{OPENPROJECT_URL}/api/v3/projects/{OPENPROJECT_PROJECT_ID}/work_packages?notify=false"
    cr = requests.post(create_url, auth=OP_AUTH, headers=OP_HEADERS, json=payload, timeout=15)
    if cr.status_code not in (200, 201):
        return f"Lỗi tạo Bug Sub-task trên OpenProject: HTTP {cr.status_code} - {cr.text[:250]}"

    new_id = cr.json().get("id")
    msg = f"✅ [OpenProject] Đã tạo Bug Sub-task #{new_id} ('{full_subject}') dưới Parent #{parent_wp_id}."

    # Kích hoạt Rule 1: CHỈ KHI Parent đang ở trạng thái TESTING -> tự động kéo về 'Rework' (status_id=14)
    parent_status = pdata.get("_links", {}).get("status", {}).get("title", "").upper()
    if parent_status == "TESTING":
        rework_res = openproject_update_work_package(
            wp_id=parent_wp_id,
            status_id="Rework",
            comment=f"Kích hoạt Rule 1 (Auto-Rework): Phát hiện lỗi mới #{new_id} ({full_subject}).",
        )
        msg += f" | 🔄 [Rule 1 Auto-Rework]: {rework_res}"
    else:
        msg += f" | ℹ️ [Rule 1]: Parent #{parent_wp_id} đang ở '{parent_status}' (không phải TESTING) nên giữ nguyên trạng thái."

    return msg


def openproject_log_work_time(
    wp_id: int,
    hours: float,
    comment: str = "Thực hiện lập trình, kiểm thử & hoàn thiện tính năng",
) -> str:
    """Ghi nhận số giờ làm việc thực tế (Time Entry) vào Work Package trên OpenProject."""
    if hours <= 0:
        return "Số giờ làm việc phải lớn hơn 0."

    h = int(hours)
    m = int(round((hours - h) * 60))
    iso_duration = f"PT{h}H{m}M" if (h > 0 and m > 0) else (f"PT{h}H" if h > 0 else f"PT{m}M")

    payload = {
        "hours": iso_duration,
        "comment": {"raw": f"🤖 [AI-Agent Auto Worklog]: {comment}"},
        "_links": {
            "workPackage": {"href": f"/api/v3/work_packages/{wp_id}"},
            "project": {"href": f"/api/v3/projects/{OPENPROJECT_PROJECT_ID}"},
        },
    }
    r = requests.post(f"{OPENPROJECT_URL}/api/v3/time_entries", auth=OP_AUTH, headers=OP_HEADERS, json=payload, timeout=10)
    if r.status_code in (200, 201):
        return f"✅ [OpenProject] Đã ghi nhận thành công {hours:.2f} giờ ({iso_duration}) vào Work Package #{wp_id}."
    return f"Lỗi ghi nhận Time Entry trên OpenProject #{wp_id}: HTTP {r.status_code} - {r.text[:200]}"


def openproject_create_subtask(
    parent_wp_id: int,
    role: str,
    title: str,
    start_date: str = "2026-10-23",
    due_date: str = "2026-10-27",
    story_points: float = 3.0,
    estimated_hours: int = 16,
    description: str = "",
) -> str:
    """
    MCP Tool Tạo mới 1 Sub-task chuyên môn ([BA], [BE], [FE], [Tester], [PM]) dưới Parent Work Package trên OpenProject,
    tự động gán đúng Assignee theo vai trò, kế thừa Sprint từ Task cha, gắn Start Date, Due Date, Story Points & Estimated Hours.
    """
    if not OPENPROJECT_API_KEY:
        return "⚠️ Chưa cấu hình OPENPROJECT_API_KEY trong file .env."

    role_clean = role.strip().upper()
    prefix_map = {"BA": "[BA]", "BE": "[BE]", "FE": "[FE]", "TEST": "[Tester]", "TESTER": "[Tester]", "PM": "[PM]"}
    prefix = prefix_map.get(role_clean, f"[{role_clean}]")
    full_subject = title.strip() if title.strip().startswith("[") else f"{prefix} {title.strip()}"
    uid = OP_ROLE_TO_USER_ID.get(role_clean, 5)

    p_resp = requests.get(f"{OPENPROJECT_URL}/api/v3/work_packages/{parent_wp_id}", auth=OP_AUTH, headers=OP_HEADERS, timeout=10)
    sprint_href = None
    if p_resp.status_code == 200:
        pdata = p_resp.json()
        parent_type_href = pdata.get("_links", {}).get("type", {}).get("href", "")
        parent_type_title = pdata.get("_links", {}).get("type", {}).get("title", "")
        if not parent_type_href.endswith("/1"):
            return (
                f"⛔ [OPENPROJECT GUARDRAIL - RULE 3 (Hierarchy Protection)]: Bị chặn! "
                f"Không thể tạo SubTask (type_id=8) dưới Work Package #{parent_wp_id} vì #{parent_wp_id} đang có kiểu là '{parent_type_title}' "
                f"(Bắt buộc cha của SubTask phải là 'Task' type_id=1)."
            )
        sprint_href = pdata.get("_links", {}).get("sprint", {}).get("href")

    links: Dict[str, Any] = {
        "type": {"href": "/api/v3/types/8"},
        "status": {"href": "/api/v3/statuses/1"},
        "priority": {"href": "/api/v3/priorities/8"},
        "parent": {"href": f"/api/v3/work_packages/{parent_wp_id}"},
        "assignee": {"href": f"/api/v3/users/{uid}"},
    }
    if sprint_href:
        links["sprint"] = {"href": sprint_href}

    desc_text = description or (
        f"Sub-task thuộc Work Package #{parent_wp_id} | Vai trò: {prefix} | "
        f"Story Points: {story_points} SP ({estimated_hours}h) | Lịch trình: {start_date} -> {due_date}"
    )

    payload: Dict[str, Any] = {
        "subject": full_subject,
        "description": {"format": "markdown", "raw": desc_text},
        "scheduleManually": True,
        "startDate": start_date,
        "dueDate": due_date,
        "storyPoints": round(float(story_points)),
        "estimatedTime": f"PT{int(estimated_hours)}H",
        "_links": links,
    }
    cr = requests.post(
        f"{OPENPROJECT_URL}/api/v3/projects/{OPENPROJECT_PROJECT_ID}/work_packages?notify=false",
        auth=OP_AUTH,
        headers=OP_HEADERS,
        json=payload,
        timeout=15,
    )
    if cr.status_code in (200, 201):
        new_id = cr.json().get("id")
        return f"✅ [OpenProject] Đã tạo Sub-task #{new_id} ('{full_subject}', {story_points} SP, {start_date} -> {due_date}) dưới Parent #{parent_wp_id}."
    return f"Lỗi tạo Sub-task trên OpenProject dưới #{parent_wp_id}: HTTP {cr.status_code} - {cr.text[:250]}"


def openproject_create_task(
    subject: str,
    parent_epic_id: int = 206,
    start_date: str = "2026-10-23",
    due_date: str = "2026-10-30",
    story_points: float = 10.0,
    sprint_id: int = 7,
    description: str = "",
    auto_create_4_subtasks: bool = False,
) -> str:
    """
    MCP Tool Tạo mới 1 Parent Task (Màn hình chức năng) trên OpenProject gắn dưới Epic.
    Nếu bật `auto_create_4_subtasks=True`, tự động sinh luôn 4 Sub-tasks chuẩn ([BA] 30%, [BE] 15%, [FE] 15%, [Tester] 40%)
    và phân công tự động cho 4 thành viên chuyên môn.
    """
    if not OPENPROJECT_API_KEY:
        return "⚠️ Chưa cấu hình OPENPROJECT_API_KEY trong file .env."

    # Guardrail Rule 3: Kiểm tra Parent của Task bắt buộc phải là Epic (type_id=5)
    ep_resp = requests.get(f"{OPENPROJECT_URL}/api/v3/work_packages/{parent_epic_id}", auth=OP_AUTH, headers=OP_HEADERS, timeout=10)
    if ep_resp.status_code == 200:
        ep_data = ep_resp.json()
        ep_type_href = ep_data.get("_links", {}).get("type", {}).get("href", "")
        ep_type_title = ep_data.get("_links", {}).get("type", {}).get("title", "")
        if not ep_type_href.endswith("/5"):
            return (
                f"⛔ [OPENPROJECT GUARDRAIL - RULE 3 (Hierarchy Protection)]: Bị chặn! "
                f"Không thể tạo Task (type_id=1) dưới Work Package #{parent_epic_id} vì #{parent_epic_id} đang có kiểu là '{ep_type_title}' "
                f"(Bắt buộc cha của Task phải là 'Epic' type_id=5)."
            )

    full_subject = subject.strip() if subject.strip().startswith("[") else f"[Màn hình] {subject.strip()}"
    desc_text = description or f"Task màn hình chức năng thuộc Epic #{parent_epic_id}. Tổng điểm: {story_points} SP ({start_date} -> {due_date})."

    links: Dict[str, Any] = {
        "type": {"href": "/api/v3/types/1"},
        "status": {"href": "/api/v3/statuses/1"},
        "priority": {"href": "/api/v3/priorities/9"},
        "parent": {"href": f"/api/v3/work_packages/{parent_epic_id}"},
        "assignee": {"href": f"/api/v3/users/{OP_ROLE_TO_USER_ID['PM']}"},
        "sprint": {"href": f"/api/v3/sprints/{sprint_id}"},
    }
    payload: Dict[str, Any] = {
        "subject": full_subject,
        "description": {"format": "markdown", "raw": desc_text},
        "scheduleManually": True,
        "startDate": start_date,
        "dueDate": due_date,
        "storyPoints": round(float(story_points)),
        "_links": links,
    }
    cr = requests.post(
        f"{OPENPROJECT_URL}/api/v3/projects/{OPENPROJECT_PROJECT_ID}/work_packages?notify=false",
        auth=OP_AUTH,
        headers=OP_HEADERS,
        json=payload,
        timeout=15,
    )
    if cr.status_code not in (200, 201):
        return f"Lỗi tạo Parent Task trên OpenProject: HTTP {cr.status_code} - {cr.text[:250]}"

    task_id = cr.json().get("id")
    msg_lines = [f"✅ [OpenProject] Đã tạo Parent Task #{task_id}: '{full_subject}' (Epic #{parent_epic_id}, {story_points} SP, {start_date} -> {due_date})."]

    if auto_create_4_subtasks:
        clean_name = subject.replace("[Màn hình]", "").strip()
        sub_defs = [
            ("BA", f"Phân tích & Thiết kế Use Case, luồng nghiệp vụ màn hình {clean_name}", round(story_points * 0.30, 1), 16),
            ("BE", f"Lập trình RESTful API & Xử lý CSDL cho màn hình {clean_name}", round(story_points * 0.20, 1), 16),
            ("FE", f"Lập trình Giao diện UI & Ghép nối API màn hình {clean_name}", round(story_points * 0.15, 1), 12),
            ("TESTER", f"Thiết kế Test Case, Kiểm thử API/UI & Hồi quy màn hình {clean_name}", round(story_points * 0.35, 1), 28),
        ]
        for role_code, st_title, st_sp, st_hours in sub_defs:
            sub_res = openproject_create_subtask(
                parent_wp_id=task_id,
                role=role_code,
                title=st_title,
                start_date=start_date,
                due_date=due_date,
                story_points=st_sp,
                estimated_hours=st_hours,
            )
            msg_lines.append(f"   ↳ {sub_res}")

    return "\n".join(msg_lines)


# ==============================================================================
# ĐỊNH NGHĨA SCHEMA 14 CÔNG CỤ CHUẨN MODEL CONTEXT PROTOCOL (MCP) CHO JIRA & OPENPROJECT
# ==============================================================================
MCP_TOOLS_SCHEMA = [
    {
        "name": "mcp_configure_workflow",
        "description": (
            "Thiết lập, đồng bộ & kiểm tra quy trình Workflow 3 tầng (Epic, Parent Task, Sub-task) "
            "kèm Guardrail Rule 1 (Auto-Rework) & Rule 2 (Child Blocking) trên Jira Cloud và OpenProject."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "provider": {
                    "type": "string",
                    "enum": ["both", "jira", "openproject"],
                    "default": "both",
                }
            },
        },
    },
    {
        "name": "jira_create_task",
        "description": (
            "Tạo mới 1 Parent Task (Màn hình chức năng) trên Jira Cloud gắn dưới Epic. "
            "Hỗ trợ cờ `auto_create_4_subtasks=True` để tự động bẻ luôn thành 4 Sub-tasks ([BA] 30%, [BE] 15%, [FE] 15%, [Tester] 40%)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "Tên màn hình/task lớn"},
                "epic_key": {"type": "string", "default": "SCRUM-195"},
                "start_date": {"type": "string", "default": "2026-10-23"},
                "due_date": {"type": "string", "default": "2026-10-30"},
                "story_points": {"type": "number", "default": 10.0},
                "description": {"type": "string"},
                "auto_create_4_subtasks": {"type": "boolean", "default": False},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "jira_create_subtask",
        "description": "Tạo mới 1 Sub-task chuyên môn ([BA], [BE], [FE], [Tester], [PM]) gắn dưới Parent Task trên Jira Cloud.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_key": {"type": "string", "description": "Mã Parent Task trên Jira (ví dụ SCRUM-219)"},
                "role": {"type": "string", "enum": ["BA", "BE", "FE", "TESTER", "PM"]},
                "title": {"type": "string", "description": "Tên công việc Sub-task"},
                "start_date": {"type": "string", "default": "2026-10-23"},
                "due_date": {"type": "string", "default": "2026-10-27"},
                "story_points": {"type": "number", "default": 3.0},
                "description": {"type": "string"},
            },
            "required": ["parent_key", "role", "title"],
        },
    },
    {
        "name": "jira_get_my_assigned_tasks",
        "description": "Lấy danh sách các Task/Sub-task trên Jira theo vai trò (PM, BA, BE, FE, TEST, BUG, ALL) hoặc JQL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "role_or_query": {
                    "type": "string",
                    "description": "Mã vai trò ('PM', 'BA', 'BE', 'FE', 'TEST', 'BUG', 'ALL') hoặc từ khóa tìm kiếm",
                    "default": "ALL",
                },
                "include_done": {
                    "type": "boolean",
                    "description": "Có bao gồm các task đã DONE hay không",
                    "default": False,
                },
            },
        },
    },
    {
        "name": "jira_update_task_status",
        "description": (
            "Chuyển trạng thái Task/Sub-task trên Jira theo Workflow 3 tầng chuẩn. "
            "Tự động kiểm tra Guardrail Rule 2 trước khi đóng DONE và đồng bộ Parent Task."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Mã issue trên Jira, ví dụ SCRUM-211"},
                "target_status": {"type": "string", "description": "Trạng thái đích hoặc tên Transition"},
                "comment_text": {"type": "string", "description": "Bình luận báo cáo tiến độ hoặc sản phẩm bàn giao"},
                "sync_parent_status": {
                    "type": "string",
                    "description": "Tùy chọn: Trạng thái muốn đồng bộ lên Parent Task (ví dụ 'DEV IN PROGRESS')",
                },
            },
            "required": ["issue_key", "target_status"],
        },
    },
    {
        "name": "jira_log_work_time",
        "description": "Ghi nhận số giờ làm việc thực tế (Time Tracking Worklog) vào Jira Issue phục vụ tính KPI & EVM.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string", "description": "Mã issue trên Jira, ví dụ SCRUM-211"},
                "hours": {"type": "number", "description": "Số giờ làm việc thực tế, ví dụ 3.5"},
                "description": {"type": "string", "description": "Mô tả chi tiết công việc đã thực hiện"},
            },
            "required": ["issue_key", "hours"],
        },
    },
    {
        "name": "jira_create_bug_subtask",
        "description": (
            "Tự động tạo Sub-task [Bug] dưới Parent Task trên Jira khi kiểm thử phát hiện lỗi "
            "và kích hoạt Rule 1 kéo Parent Task từ TESTING về REWORK."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_key": {"type": "string", "description": "Mã Parent Task đang được kiểm thử"},
                "bug_title": {"type": "string", "description": "Tiêu đề ngắn gọn của lỗi"},
                "error_detail": {"type": "string", "description": "Các bước tái hiện lỗi và log chi tiết"},
                "severity": {"type": "string", "enum": ["Critical", "Major", "Minor"], "default": "Major"},
                "assignee_role": {"type": "string", "enum": ["BE", "FE", "BA"], "default": "BE"},
            },
            "required": ["parent_key", "bug_title", "error_detail"],
        },
    },
    {
        "name": "ops_sync_git_commit",
        "description": "Đồng bộ thông tin Git Commit Hash, Branch và trạng thái CI/CD Pipeline vào Jira Task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_key": {"type": "string"},
                "commit_hash": {"type": "string"},
                "branch_name": {"type": "string"},
                "commit_message": {"type": "string"},
                "ci_status": {"type": "string", "enum": ["PASS", "FAIL"], "default": "PASS"},
            },
            "required": ["issue_key", "commit_hash", "branch_name"],
        },
    },
    {
        "name": "openproject_create_task",
        "description": (
            "Tạo mới 1 Parent Task (Màn hình chức năng) trên OpenProject gắn dưới Epic & Sprint. "
            "Hỗ trợ cờ `auto_create_4_subtasks=True` để tự động bẻ luôn thành 4 Sub-tasks ([BA] 30%, [BE] 15%, [FE] 15%, [Tester] 40%)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "subject": {"type": "string", "description": "Tên màn hình/task lớn"},
                "parent_epic_id": {"type": "integer", "default": 206},
                "start_date": {"type": "string", "default": "2026-10-23"},
                "due_date": {"type": "string", "default": "2026-10-30"},
                "story_points": {"type": "number", "default": 10.0},
                "sprint_id": {"type": "integer", "default": 7},
                "description": {"type": "string"},
                "auto_create_4_subtasks": {"type": "boolean", "default": False},
            },
            "required": ["subject"],
        },
    },
    {
        "name": "openproject_create_subtask",
        "description": "Tạo mới 1 Sub-task chuyên môn ([BA], [BE], [FE], [Tester], [PM]) gắn dưới Parent Work Package trên OpenProject.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_wp_id": {"type": "integer", "description": "ID của Work Package cha trên OpenProject"},
                "role": {"type": "string", "enum": ["BA", "BE", "FE", "TESTER", "PM"]},
                "title": {"type": "string", "description": "Tên công việc Sub-task"},
                "start_date": {"type": "string", "default": "2026-10-23"},
                "due_date": {"type": "string", "default": "2026-10-27"},
                "story_points": {"type": "number", "default": 3.0},
                "estimated_hours": {"type": "integer", "default": 16},
                "description": {"type": "string"},
            },
            "required": ["parent_wp_id", "role", "title"],
        },
    },
    {
        "name": "openproject_get_assigned_tasks",
        "description": "Lấy danh sách các Work Packages trên OpenProject theo vai trò (PM, BA, BE, FE, TEST, BUG, ALL).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "role_or_query": {
                    "type": "string",
                    "description": "Mã vai trò ('PM', 'BA', 'BE', 'FE', 'TEST', 'BUG', 'ALL') hoặc từ khóa",
                    "default": "ALL",
                },
                "include_closed": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "openproject_update_work_package",
        "description": (
            "Cập nhật trạng thái Work Package trên OpenProject qua REST API v3 (HAL+JSON), "
            "tích hợp Guardrail Rule 2 chặn đóng Task cha khi còn Sub-task chưa Done và tự động đồng bộ Parent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "wp_id": {"type": "integer", "description": "ID của Work Package trên OpenProject (ví dụ 195)"},
                "status_id": {
                    "type": "string",
                    "description": (
                        "ID hoặc tên trạng thái (1=To Do, 18=BA in progress, 19=BA Review, "
                        "17=Dev in progress, 10=Ready for test, 9=Testing, 14=Rework, 20=In review, 12=Done)"
                    ),
                },
                "comment": {"type": "string", "description": "Ghi chú cập nhật"},
                "sync_parent_status": {"type": "string", "description": "Tùy chọn đồng bộ trạng thái Parent WP"},
            },
            "required": ["wp_id", "status_id"],
        },
    },
    {
        "name": "openproject_create_bug_subtask",
        "description": (
            "Tự động tạo Sub-task [Bug] (type_id=8) dưới Parent Work Package trên OpenProject "
            "và kích hoạt Rule 1 kéo Parent về 'Rework' (status_id=14) CHỈ KHI Parent đang ở 'Testing'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "parent_wp_id": {"type": "integer", "description": "ID của Work Package màn hình cha trên OpenProject"},
                "bug_title": {"type": "string", "description": "Tiêu đề lỗi"},
                "error_detail": {"type": "string", "description": "Chi tiết lỗi"},
                "severity": {"type": "string", "enum": ["Critical", "Major", "Minor"], "default": "Major"},
                "assignee_role": {"type": "string", "enum": ["BE", "FE", "BA"], "default": "BE"},
            },
            "required": ["parent_wp_id", "bug_title", "error_detail"],
        },
    },
    {
        "name": "openproject_log_work_time",
        "description": "Ghi nhận số giờ làm việc thực tế (Time Entry) vào Work Package trên OpenProject.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wp_id": {"type": "integer", "description": "ID của Work Package trên OpenProject"},
                "hours": {"type": "number", "description": "Số giờ làm việc thực tế"},
                "comment": {"type": "string", "description": "Mô tả công việc đã thực hiện"},
            },
            "required": ["wp_id", "hours"],
        },
    },
]


def handle_mcp_tool_call(name: str, arguments: Dict[str, Any]) -> str:
    """Điều phối lời gọi công cụ từ AI Agent tới hàm thực thi tương ứng (Jira Cloud & OpenProject)."""
    if name == "mcp_configure_workflow":
        return mcp_configure_workflow(provider=arguments.get("provider", "both"))
    elif name == "jira_create_task":
        return jira_create_task(
            summary=arguments["summary"],
            epic_key=arguments.get("epic_key", "SCRUM-195"),
            start_date=arguments.get("start_date", "2026-10-23"),
            due_date=arguments.get("due_date", "2026-10-30"),
            story_points=float(arguments.get("story_points", 10.0)),
            description=arguments.get("description", ""),
            auto_create_4_subtasks=bool(arguments.get("auto_create_4_subtasks", False)),
        )
    elif name == "jira_create_subtask":
        return jira_create_subtask(
            parent_key=arguments["parent_key"],
            role=arguments["role"],
            title=arguments["title"],
            start_date=arguments.get("start_date", "2026-10-23"),
            due_date=arguments.get("due_date", "2026-10-27"),
            story_points=float(arguments.get("story_points", 3.0)),
            description=arguments.get("description", ""),
        )
    elif name == "jira_get_my_assigned_tasks":
        res = get_my_assigned_tasks(
            role_or_query=arguments.get("role_or_query", "ALL"),
            include_done=bool(arguments.get("include_done", False)),
        )
        return json.dumps(res, ensure_ascii=False, indent=2)
    elif name == "jira_update_task_status":
        return update_task_status(
            issue_key=arguments["issue_key"],
            target_status=arguments["target_status"],
            comment_text=arguments.get("comment_text"),
            sync_parent_status=arguments.get("sync_parent_status"),
        )
    elif name == "jira_log_work_time":
        return log_work_time(
            issue_key=arguments["issue_key"],
            hours=float(arguments["hours"]),
            description=arguments.get("description", "Thực hiện lập trình & hoàn thiện tính năng"),
        )
    elif name == "jira_create_bug_subtask":
        return create_bug_subtask(
            parent_key=arguments["parent_key"],
            bug_title=arguments["bug_title"],
            error_detail=arguments["error_detail"],
            severity=arguments.get("severity", "Major"),
            assignee_role=arguments.get("assignee_role", "BE"),
        )
    elif name == "ops_sync_git_commit":
        return ops_sync_git_commit(
            issue_key=arguments["issue_key"],
            commit_hash=arguments["commit_hash"],
            branch_name=arguments["branch_name"],
            commit_message=arguments.get("commit_message", ""),
            ci_status=arguments.get("ci_status", "PASS"),
        )
    elif name == "openproject_create_task":
        return openproject_create_task(
            subject=arguments["subject"],
            parent_epic_id=int(arguments.get("parent_epic_id", 206)),
            start_date=arguments.get("start_date", "2026-10-23"),
            due_date=arguments.get("due_date", "2026-10-30"),
            story_points=float(arguments.get("story_points", 10.0)),
            sprint_id=int(arguments.get("sprint_id", 7)),
            description=arguments.get("description", ""),
            auto_create_4_subtasks=bool(arguments.get("auto_create_4_subtasks", False)),
        )
    elif name == "openproject_create_subtask":
        return openproject_create_subtask(
            parent_wp_id=int(arguments["parent_wp_id"]),
            role=arguments["role"],
            title=arguments["title"],
            start_date=arguments.get("start_date", "2026-10-23"),
            due_date=arguments.get("due_date", "2026-10-27"),
            story_points=float(arguments.get("story_points", 3.0)),
            estimated_hours=int(arguments.get("estimated_hours", 16)),
            description=arguments.get("description", ""),
        )
    elif name == "openproject_get_assigned_tasks":
        res = openproject_get_assigned_tasks(
            role_or_query=arguments.get("role_or_query", "ALL"),
            include_closed=bool(arguments.get("include_closed", False)),
        )
        return json.dumps(res, ensure_ascii=False, indent=2)
    elif name == "openproject_update_work_package":
        return openproject_update_work_package(
            wp_id=int(arguments["wp_id"]),
            status_id=arguments["status_id"],
            comment=arguments.get("comment", "Cập nhật tự động qua AI Agent MCP"),
            sync_parent_status=arguments.get("sync_parent_status"),
        )
    elif name == "openproject_create_bug_subtask":
        return openproject_create_bug_subtask(
            parent_wp_id=int(arguments["parent_wp_id"]),
            bug_title=arguments["bug_title"],
            error_detail=arguments["error_detail"],
            severity=arguments.get("severity", "Major"),
            assignee_role=arguments.get("assignee_role", "BE"),
        )
    elif name == "openproject_log_work_time":
        return openproject_log_work_time(
            wp_id=int(arguments["wp_id"]),
            hours=float(arguments["hours"]),
            comment=arguments.get("comment", "Thực hiện lập trình & hoàn thiện tính năng"),
        )
    else:
        raise ValueError(f"Tool không tồn tại: {name}")


def run_stdio_mcp_server() -> None:
    """
    Vòng lặp máy chủ Model Context Protocol (MCP) chuẩn JSON-RPC 2.0 qua luồng Stdio.
    Tương thích 100% với Antigravity IDE, Claude Desktop, Cursor mà không cần cài thêm package ngoài.
    """
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")
        req_id = req.get("id")
        params = req.get("params") or {}

        # Nếu là notification (không có id), không cần trả về response
        if req_id is None:
            continue

        if method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "ptit-qldapm-jira-ops-mcp",
                        "version": "2.1.0",
                    },
                },
            }
        elif method == "ping":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {}}
        elif method == "tools/list":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": MCP_TOOLS_SCHEMA},
            }
        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments") or {}
            try:
                output_text = handle_mcp_tool_call(tool_name, tool_args)
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": output_text}],
                        "isError": False,
                    },
                }
            except Exception as exc:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Lỗi thực thi MCP Tool '{tool_name}': {exc}"}],
                        "isError": True,
                    },
                }
        else:
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
        sys.stdout.flush()


def run_cli_demo() -> None:
    """Chế độ chạy Demo trực quan trên Terminal cho cả Jira Cloud và OpenProject."""
    print("=" * 85)
    print("🚀 PTIT QLDAPM — DUAL-PROVIDER JIRA CLOUD & OPENPROJECT MCP SERVER (V2.1 LIVE DEMO)")
    print("=" * 85)
    print(f"• Jira Cloud Endpoint : {JIRA_BASE_URL} (Project: {JIRA_PROJECT_KEY})")
    print(f"• OpenProject Endpoint: {OPENPROJECT_URL} (Project ID: {OPENPROJECT_PROJECT_ID})")
    print(f"• Số lượng MCP Tools  : {len(MCP_TOOLS_SCHEMA)} công cụ chuẩn JSON-RPC 2.0 (Tạo/Kiểm tra Workflow, Tạo Task, Tạo Sub-task, Chuyển Status, Log Time)")
    for idx, t in enumerate(MCP_TOOLS_SCHEMA, 1):
        print(f"   {idx:02d}. {t['name']}: {t['description'][:72]}...")

    print("\n" + "-" * 85)
    print("⚙️ [TEST 0 - MCP WORKFLOW ENGINE] Gọi `mcp_configure_workflow(provider='both')`")
    print("-" * 85)
    print(mcp_configure_workflow(provider="both"))

    print("\n" + "-" * 85)
    print("🔍 [TEST 1 - JIRA CLOUD] Gọi `jira_get_my_assigned_tasks(role_or_query='BE', include_done=True)`")
    print("-" * 85)
    be_tasks = get_my_assigned_tasks(role_or_query="BE", include_done=True)
    print(f"-> [Jira] Tìm thấy {len(be_tasks)} Sub-tasks của Backend Developer (Vũ Quốc Hiếu). 3 task đầu:")
    for item in be_tasks[:3]:
        if "error" in item:
            print(f"   [Lỗi]: {item['error']}")
        else:
            print(
                f"   • [{item['key']}] (Parent: {item['parent_key']}) {item['summary'][:52]} "
                f"| Status: {item['status']} | Due: {item['due_date']}"
            )

    print("\n" + "-" * 85)
    print("🛡️ [TEST 2 - JIRA GUARDRAIL RULE 2] Chặn đóng Parent Task trên Jira nếu Sub-task chưa DONE")
    print("-" * 85)
    all_open = get_my_assigned_tasks(role_or_query="ALL", include_done=False)
    sample_parent = next(
        (x["parent_key"] for x in all_open if x.get("parent_key") and "sub" in str(x.get("type", "")).lower()),
        None,
    )
    if sample_parent:
        guard_msg = _check_subtasks_before_done(sample_parent)
        print(f"-> Giả lập lệnh đóng Task lớn {sample_parent} sang DONE:")
        print(f"   {guard_msg or 'Tất cả Sub-task đã DONE, cho phép đóng.'}")

    print("\n" + "-" * 85)
    print("🔍 [TEST 3 - OPENPROJECT] Gọi `openproject_get_assigned_tasks(role_or_query='BE', include_closed=True)`")
    print("-" * 85)
    op_be_tasks = openproject_get_assigned_tasks(role_or_query="BE", include_closed=True)
    print(f"-> [OpenProject] Tìm thấy {len(op_be_tasks)} Sub-tasks của Backend Developer (Vũ Quốc Hiếu). 3 task đầu:")
    for item in op_be_tasks[:3]:
        if "error" in item:
            print(f"   [Lỗi]: {item['error']}")
        else:
            print(
                f"   • [#{item['id']}] (Parent: #{item['parent_id']} | {item['sprint']}) {item['subject'][:48]} "
                f"| Status: {item['status']} | {item['start_date']} -> {item['due_date']}"
            )

    print("\n" + "-" * 85)
    print("🛡️ [TEST 4 - OPENPROJECT GUARDRAIL RULE 2] Chặn đóng Parent WP #193 nếu Sub-task chưa Closed")
    print("-" * 85)
    op_guard_msg = openproject_update_work_package(wp_id=193, status_id="Closed")
    print(f"-> Giả lập lệnh đóng Task màn hình #193 (Authentication) sang Closed:")
    print(f"   {op_guard_msg}")

    print("\n✅ [HOÀN TẤT] MCP Server sẵn sàng phục vụ đồng thời cả Jira Cloud & OpenProject qua JSON-RPC 2.0!")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("--demo", "--test", "-d"):
        run_cli_demo()
    else:
        run_stdio_mcp_server()
