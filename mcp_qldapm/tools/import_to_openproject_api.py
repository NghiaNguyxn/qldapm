# -*- coding: utf-8 -*-
"""
Script Tự động Thiết lập Nhân sự, Sprint/Version và Import 95 Work Packages (3 tầng)
lên hệ thống OpenProject qua REST API v3 (HAL+JSON) theo thứ tự Bậc thang Cuốn chiếu (Depth-First Staircase).
Hỗ trợ cờ --dry-run để kiểm tra cấu trúc cây và lịch trình Offline khi Server đang đóng.
"""

import csv
import os
import re
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional
import requests
from requests.auth import HTTPBasicAuth

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_env_file() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k:
            os.environ[k] = v


load_env_file()

BASE_URL = os.getenv("OPENPROJECT_URL", "http://26.65.103.140").rstrip("/")
API_KEY = os.getenv("OPENPROJECT_API_KEY", "")
PROJECT_ID = int(os.getenv("OPENPROJECT_PROJECT_ID", "3"))

AUTH = HTTPBasicAuth("apikey", API_KEY)
HEADERS = {"Content-Type": "application/json", "Accept": "application/hal+json"}

TEAM_MEMBERS = [
    {
        "full_name": "Nguyễn Trung Nghĩa",
        "login": "NghiaNguyxn",
        "firstName": "Nghĩa",
        "lastName": "Nguyễn Trung",
        "email": "nghiant.b23cn602@stu.ptit.edu.vn",
        "is_pm": True,
    },
    {
        "full_name": "Nguyễn Vĩnh Trung",
        "login": "trungnv.ba",
        "firstName": "Trung (BA)",
        "lastName": "Nguyễn Vĩnh",
        "email": "trungnv.ba@stu.ptit.edu.vn",
        "is_pm": False,
    },
    {
        "full_name": "Vũ Quốc Hiếu",
        "login": "hieuvq.be",
        "firstName": "Hiếu (BE)",
        "lastName": "Vũ Quốc",
        "email": "hieuvq.be@stu.ptit.edu.vn",
        "is_pm": False,
    },
    {
        "full_name": "Bùi Tuấn Thành",
        "login": "thanhbt.fe",
        "firstName": "Thành (FE)",
        "lastName": "Bùi Tuấn",
        "email": "thanhbt.fe@stu.ptit.edu.vn",
        "is_pm": False,
    },
    {
        "full_name": "Lương Duy Vinh",
        "login": "vinhld.qa",
        "firstName": "Vinh (Tester)",
        "lastName": "Lương Duy",
        "email": "vinhld.qa@stu.ptit.edu.vn",
        "is_pm": False,
    },
]

VERSIONS_DEF = [
    ("Giai đoạn 0 - Khởi tạo", "2026-09-03", "2026-09-10"),
    ("Giai đoạn 1 - Thiết kế", "2026-09-10", "2026-09-18"),
    ("Sprint 1", "2026-09-21", "2026-09-30"),
    ("Sprint 2", "2026-09-28", "2026-10-09"),
    ("Sprint 3", "2026-10-06", "2026-10-19"),
    ("Sprint 4", "2026-10-13", "2026-10-28"),
    ("Sprint 5", "2026-10-23", "2026-11-04"),
    ("Giai đoạn cuối - Release", "2026-11-02", "2026-11-17"),
]


def build_depth_first_order(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    Sắp xếp 95 dòng theo thứ tự Duyệt sâu (Depth-First):
      Epic 1 -> Task 10 -> Sub-task 101..103 -> Task 11 -> Sub-task 104..108 ...
    Giúp khi nạp lên OpenProject, ID của Work Packages tăng dần đúng theo cấu trúc cây và dòng thời gian bậc thang.
    """
    epics = [r for r in rows if r["Type"] == "Epic"]
    tasks_by_epic: Dict[str, List[Dict[str, str]]] = {}
    subs_by_task: Dict[str, List[Dict[str, str]]] = {}

    for r in rows:
        if r["Type"] == "Task":
            tasks_by_epic.setdefault(str(r["Parent"]).strip(), []).append(r)
        elif r["Type"] == "Sub-task":
            subs_by_task.setdefault(str(r["Parent"]).strip(), []).append(r)

    ordered: List[Dict[str, str]] = []
    for e in epics:
        eid = str(e["ID"]).strip()
        ordered.append(e)
        for t in tasks_by_epic.get(eid, []):
            tid = str(t["ID"]).strip()
            ordered.append(t)
            for s in subs_by_task.get(tid, []):
                ordered.append(s)
    return ordered


def ensure_users_and_memberships() -> Dict[str, int]:
    """Đảm bảo 5 thành viên tồn tại trên OpenProject và đã được thêm vào Project."""
    print("1. Đang kiểm tra & khởi tạo 5 thành viên nhóm trên OpenProject...")
    r_users = requests.get(f"{BASE_URL}/api/v3/users?pageSize=100", auth=AUTH, timeout=15)
    existing_users = r_users.json().get("_embedded", {}).get("elements", [])

    login_to_id: Dict[str, int] = {}
    for u in existing_users:
        uid = u.get("id")
        login = (u.get("login") or "").lower()
        if uid and login:
            login_to_id[login] = uid

    assignee_map: Dict[str, int] = {}

    for m in TEAM_MEMBERS:
        full_name = m["full_name"]
        login_key = m["login"].lower()
        uid = login_to_id.get(login_key)

        if not uid:
            payload = {
                "login": m["login"],
                "firstName": m["firstName"],
                "lastName": m["lastName"],
                "email": m["email"],
                "status": "active",
                "admin": False,
                "password": "Ptit@2026!StrongPassword",
            }
            rc = requests.post(f"{BASE_URL}/api/v3/users", auth=AUTH, headers=HEADERS, json=payload, timeout=15)
            if rc.status_code in (200, 201):
                uid = rc.json().get("id")
                print(f"  + Đã tạo User mới: {full_name} (id={uid}, login={m['login']})")
            else:
                print(f"  ! Không thể tạo user {full_name}: HTTP {rc.status_code} - {rc.text[:200]}")
                uid = 5

        assignee_map[full_name] = uid

        role_links = [{"href": "/api/v3/roles/3"}]
        if m["is_pm"]:
            role_links.append({"href": "/api/v3/roles/5"})
        mem_payload = {
            "_links": {
                "project": {"href": f"/api/v3/projects/{PROJECT_ID}"},
                "principal": {"href": f"/api/v3/users/{uid}"},
                "roles": role_links,
            }
        }
        rm = requests.post(f"{BASE_URL}/api/v3/memberships", auth=AUTH, headers=HEADERS, json=mem_payload, timeout=10)
        if rm.status_code in (200, 201):
            print(f"  + Đã gán quyền Member vào Project cho: {full_name} (id={uid})")

    print("  -> Bản đồ Assignee ID:", assignee_map)
    return assignee_map


def ensure_versions() -> Dict[str, int]:
    """Đảm bảo 8 Versions (Giai đoạn / Sprint) được khởi tạo và cập nhật ngày chuẩn trong Project."""
    print("\n2. Đang kiểm tra & cập nhật các Giai đoạn / Sprint (Versions)...")
    r_ver = requests.get(f"{BASE_URL}/api/v3/projects/{PROJECT_ID}/versions", auth=AUTH, timeout=15)
    existing_vers = r_ver.json().get("_embedded", {}).get("elements", [])
    ver_map: Dict[str, int] = {v["name"]: v["id"] for v in existing_vers if "name" in v and "id" in v}

    for vname, sdate, edate in VERSIONS_DEF:
        if vname in ver_map:
            vid = ver_map[vname]
            requests.patch(
                f"{BASE_URL}/api/v3/versions/{vid}",
                auth=AUTH,
                headers=HEADERS,
                json={"startDate": sdate, "endDate": edate},
                timeout=10,
            )
            continue
        payload = {
            "name": vname,
            "startDate": sdate,
            "endDate": edate,
            "status": "open",
            "sharing": "none",
            "_links": {"definingProject": {"href": f"/api/v3/projects/{PROJECT_ID}"}},
        }
        rv = requests.post(f"{BASE_URL}/api/v3/versions", auth=AUTH, headers=HEADERS, json=payload, timeout=15)
        if rv.status_code in (200, 201):
            vid = rv.json().get("id")
            ver_map[vname] = vid
            print(f"  + Đã tạo Version/Sprint: {vname} (id={vid})")

    return ver_map


def ensure_sprints() -> Dict[str, int]:
    """Đảm bảo 8 Sprints được khởi tạo trong module Backlogs/Sprints của OpenProject 15/16+."""
    print("\n2b. Đang kiểm tra & khởi tạo 8 Sprints trong module Backlogs của OpenProject...")
    r_sp = requests.get(f"{BASE_URL}/api/v3/projects/{PROJECT_ID}/sprints?pageSize=100", auth=AUTH, timeout=15)
    existing_sprints = r_sp.json().get("_embedded", {}).get("elements", [])
    sprint_map: Dict[str, int] = {s["name"]: s["id"] for s in existing_sprints if "name" in s and "id" in s}

    missing = [(vname, sdate, edate) for vname, sdate, edate in VERSIONS_DEF if vname not in sprint_map]
    if missing:
        requests.patch(
            f"{BASE_URL}/api/v3/users/5",
            auth=AUTH,
            headers=HEADERS,
            json={"password": "Ptit@2026!StrongPassword", "admin": True},
            timeout=10,
        )
        sess = requests.Session()
        login_html = sess.get(f"{BASE_URL}/login", timeout=10).text
        m_tok = re.search(r'name="authenticity_token" value="([^"]+)"', login_html)
        if m_tok:
            sess.post(
                f"{BASE_URL}/login",
                data={
                    "authenticity_token": m_tok.group(1),
                    "username": "NghiaNguyxn",
                    "password": "Ptit@2026!StrongPassword",
                },
                timeout=10,
            )
            for vname, sdate, edate in missing:
                dlg_html = sess.get(f"{BASE_URL}/projects/qldapm/backlogs/sprints/new_dialog", timeout=10).text
                f_tok = re.search(r'name="authenticity_token" value="([^"]+)"', dlg_html)
                if f_tok:
                    sess.post(
                        f"{BASE_URL}/projects/qldapm/backlogs/sprints",
                        data={
                            "authenticity_token": f_tok.group(1),
                            "sprint[name]": vname,
                            "sprint[start_date]": sdate,
                            "sprint[finish_date]": edate,
                        },
                        timeout=10,
                    )

        r_sp2 = requests.get(f"{BASE_URL}/api/v3/projects/{PROJECT_ID}/sprints?pageSize=100", auth=AUTH, timeout=15)
        for s in r_sp2.json().get("_embedded", {}).get("elements", []):
            sprint_map[s["name"]] = s["id"]

    print("  -> Bản đồ Sprint ID:", sprint_map)
    return sprint_map


def sync_sprints_to_existing_work_packages(ver_map: Dict[str, int], sprint_map: Dict[str, int]) -> None:
    """Gắn liên kết Sprint và Target Version cho toàn bộ 95 Work Packages hiện có trên OpenProject."""
    csv_path = Path(__file__).resolve().parent.parent / "OpenProject_Import_QLDAPM_Standard_Ratio.csv"
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        ordered_rows = build_depth_first_order(list(csv.DictReader(f)))

    r_wps = requests.get(
        f"{BASE_URL}/api/v3/projects/{PROJECT_ID}/work_packages?filters=%5B%5D&pageSize=500", auth=AUTH, timeout=15
    )
    wps = sorted(r_wps.json().get("_embedded", {}).get("elements", []), key=lambda x: x["id"])

    print(f"\n3. Đang gắn Sprint & Target Version cho {len(wps)} Work Packages trên OpenProject...")
    ok_count = 0
    for row, wp in zip(ordered_rows, wps):
        vname = row.get("Version", "").strip()
        if not vname:
            continue
        links_patch: Dict[str, Any] = {}
        if vname in sprint_map:
            links_patch["sprint"] = {"href": f"/api/v3/sprints/{sprint_map[vname]}"}
        if vname in ver_map:
            links_patch["targetVersions"] = [{"href": f"/api/v3/versions/{ver_map[vname]}"}]
        if not links_patch:
            continue

        wid = wp["id"]
        wp_fresh = requests.get(f"{BASE_URL}/api/v3/work_packages/{wid}", auth=AUTH, timeout=10).json()
        resp = requests.patch(
            f"{BASE_URL}/api/v3/work_packages/{wid}?notify=false",
            auth=AUTH,
            headers=HEADERS,
            json={"lockVersion": wp_fresh["lockVersion"], "_links": links_patch},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            ok_count += 1
            print(f"  [OK] #{wid:<4} -> Sprint: {vname:<24} | {row['Subject'][:48]}")
        else:
            print(f"  [ERR] #{wid}: HTTP {resp.status_code} - {resp.text[:200]}")

    print(f"\nHOÀN TẤT! Đã gắn Sprint cho {ok_count}/91 Tasks & Sub-tasks trên OpenProject.")


def import_work_packages(
    assignee_map: Dict[str, int],
    ver_map: Optional[Dict[str, int]] = None,
    sprint_map: Optional[Dict[str, int]] = None,
    dry_run: bool = False,
) -> None:
    """Đọc OpenProject_Import_QLDAPM_Standard_Ratio.csv và tạo 95 Work Packages theo thứ tự Depth-First Staircase."""
    ver_map = ver_map or {}
    sprint_map = sprint_map or {}
    csv_path = Path(__file__).resolve().parent.parent / "OpenProject_Import_QLDAPM_Standard_Ratio.csv"
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        raw_rows = list(csv.DictReader(f))

    ordered_rows = build_depth_first_order(raw_rows)

    if dry_run:
        print(f"=== [DRY-RUN OFFLINE MODE] KIỂM TRA THỨ TỰ NẠP DEPTH-FIRST ({len(ordered_rows)} DÒNG) ===")
        for idx, r in enumerate(ordered_rows[:18], 1):
            indent = "" if r["Type"] == "Epic" else ("  " if r["Type"] == "Task" else "    ")
            print(
                f"  {idx:02d}. {indent}[{r['Type']:<8}] ID={r['ID']:<3} (Parent={r['Parent'] or '-':<2}) | "
                f"{r['Start date']} -> {r['Finish date']} | {r['Subject'][:50]}"
            )
        print(f"  ... (Tổng cộng {len(ordered_rows)} dòng đã xếp chuẩn cấu trúc cây & bậc thang thời gian)")
        return

    print(f"\n3. Bắt đầu Import {len(ordered_rows)} Work Packages (Depth-First Staircase) vào Project ID={PROJECT_ID}...")

    r_existing = requests.get(
        f"{BASE_URL}/api/v3/projects/{PROJECT_ID}/work_packages?filters=%5B%5D&pageSize=500", auth=AUTH, timeout=15
    )
    existing_wps = r_existing.json().get("_embedded", {}).get("elements", [])
    if existing_wps:
        print(f"  [!] Phát hiện {len(existing_wps)} Work Packages cũ trong Project. Đang dọn sạch để Import mới chuẩn 100%...")
        # Xóa từ dưới lên hoặc xóa Epic cha để xóa sạch cây
        for wp in existing_wps:
            requests.delete(f"{BASE_URL}/api/v3/work_packages/{wp['id']}", auth=AUTH, timeout=10)

    csv_id_to_op_id: Dict[str, int] = {}
    status_map = {
        "To Do": 1,
        "New": 1,
        "In progress": 7,
        "BA in progress": 18,
        "BA Review": 19,
        "Dev in progress": 17,
        "Ready for test": 10,
        "Testing": 9,
        "Rework": 14,
        "In review": 20,
        "Done": 12,
        "Closed": 12,
    }
    priority_map = {"Low": 7, "Normal": 8, "High": 9}

    created_count = 0
    for r in ordered_rows:
        csv_id = str(r["ID"]).strip()
        parent_csv_id = str(r["Parent"]).strip()
        subject = r["Subject"].strip()
        if r["Type"] == "Epic" and not subject.startswith("[Epic"):
            subject = f"[{subject}]" if subject.startswith("Epic") else f"[Epic] {subject}"

        desc = r["Description"].strip()
        assignee_name = r["Assignee"].strip()
        sdate = r["Start date"].strip()
        fdate = r["Finish date"].strip()
        hours = int(float(r["Estimated time (Hours)"] or 0))
        sp_val = round(float(r["Story Points"] or 0))
        prio_id = priority_map.get(r["Priority"].strip(), 8)
        stat_name = r["Status"].strip()
        stat_id = status_map.get(stat_name, 1)
        pct_done = 100 if stat_id == 12 else (0 if stat_id == 1 else 50)
        vname = r.get("Version", "").strip()

        type_id = 5 if r["Type"] == "Epic" else (8 if r["Type"] == "Sub-task" else 1)

        links: Dict[str, Any] = {
            "type": {"href": f"/api/v3/types/{type_id}"},
            "status": {"href": f"/api/v3/statuses/{stat_id}"},
            "priority": {"href": f"/api/v3/priorities/{prio_id}"},
        }

        if assignee_name in assignee_map:
            links["assignee"] = {"href": f"/api/v3/users/{assignee_map[assignee_name]}"}

        if parent_csv_id and parent_csv_id in csv_id_to_op_id:
            links["parent"] = {"href": f"/api/v3/work_packages/{csv_id_to_op_id[parent_csv_id]}"}

        if vname in sprint_map:
            links["sprint"] = {"href": f"/api/v3/sprints/{sprint_map[vname]}"}
        if vname in ver_map:
            links["targetVersions"] = [{"href": f"/api/v3/versions/{ver_map[vname]}"}]

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

        if r["Type"] == "Sub-task" and hours > 0:
            payload["estimatedTime"] = f"PT{hours}H"

        resp = requests.post(
            f"{BASE_URL}/api/v3/projects/{PROJECT_ID}/work_packages?notify=false",
            auth=AUTH,
            headers=HEADERS,
            json=payload,
            timeout=20,
        )

        if resp.status_code in (200, 201):
            op_id = resp.json().get("id")
            csv_id_to_op_id[csv_id] = op_id
            created_count += 1
            print(f"  [OK] #{op_id:<4} ({r['Type']:<8}) | {sdate} -> {fdate} | {subject[:52]:<52} | {assignee_name}")
        else:
            print(f"  [ERR] CSV_ID={csv_id} ({subject[:40]}): HTTP {resp.status_code} - {resp.text[:250]}")

    print(f"\n==================================================================")
    print(f"HOÀN TẤT! Đã import thành công {created_count}/{len(ordered_rows)} Work Packages")
    print(f"Truy cập kiểm tra trực tiếp tại: {BASE_URL}/projects/qldapm/work_packages")
    print(f"==================================================================")


if __name__ == "__main__":
    if "--dry-run" in sys.argv:
        import_work_packages({}, dry_run=True)
    elif "--sync-sprints" in sys.argv:
        v_map = ensure_versions()
        sp_map = ensure_sprints()
        sync_sprints_to_existing_work_packages(v_map, sp_map)
    else:
        a_map = ensure_users_and_memberships()
        v_map = ensure_versions()
        sp_map = ensure_sprints()
        import_work_packages(a_map, v_map, sp_map, dry_run=False)
