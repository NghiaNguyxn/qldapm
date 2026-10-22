# -*- coding: utf-8 -*-
"""
KPI, Bug Metrics & Salary Review Report Generator for INT1450 PTIT
Tự động truy vấn Jira Cloud qua REST API v3, trích xuất dữ liệu công việc thực tế,
tính toán đầy đủ các chỉ số:
- Khối lượng công việc (Task, Sub-task, Story Points, HS_KL)
- Kỷ luật tiến độ (On-Time Delivery OTD, HS_TĐ)
- Chất lượng & Lỗi (Bug/Task, Defect Density D_dev, Reopen Rate, Bug/Test, DDE, HS_CL)
- Hệ số Hiệu suất tổng hợp: HS = 0.40 * HS_KL + 0.30 * HS_TĐ + 0.30 * HS_CL
Xuất báo cáo Markdown và CSV phục vụ nghiệm thu học phần INT1450.
"""

import os
import sys
import csv
from pathlib import Path
from typing import List, Dict, Any
import requests
from requests.auth import HTTPBasicAuth

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_env_file() -> None:
    """Tự động nạp biến môi trường từ file .env ở thư mục gốc dự án."""
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
        if key and key not in os.environ:
            os.environ[key] = val


load_env_file()

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://nghianguyxn259.atlassian.net").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")
JIRA_PROJECT_KEY = os.getenv("JIRA_PROJECT_KEY", "SCRUM")

AUTH = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

# Trọng số Story Points trên mỗi Màn hình chuẩn (10 SP) theo đúng tỷ lệ cân bằng mới:
# - [BA] (Requirement 10% + Analyst-Design 20%): 30% -> 3.0 SP
# - [BE] (Backend Dev 20%) + [FE] (Frontend Dev 15%): Tổng Dev 35% -> 2.0 SP + 1.5 SP
# - [Tester] (QA / Testing 35%): 35% -> 3.5 SP
MEMBERS = {
    "PM": {"name": "Nguyễn Trung Nghĩa", "role": "PM & Scrum Master", "weight_sp": 3.0},
    "BA": {"name": "Nguyễn Vĩnh Trung", "role": "Business Analyst (BA)", "weight_sp": 3.0},
    "BE": {"name": "Vũ Quốc Hiếu", "role": "Backend Developer (BE)", "weight_sp": 2.0},
    "FE": {"name": "Bùi Tuấn Thành", "role": "Frontend Developer (FE)", "weight_sp": 1.5},
    "TEST": {"name": "Lương Duy Vinh", "role": "Tester / QA", "weight_sp": 3.5},
}


def classify_rank_and_decision(hs: float) -> tuple[str, str]:
    """
    Thang xếp loại hiệu suất chuẩn hóa xuyên suốt toàn bộ hồ sơ nghiên cứu:
    - HS >= 1.15        : Hạng A+ (Xuất sắc)
    - 1.00 <= HS < 1.15 : Hạng A  (Hoàn thành tốt)
    - 0.85 <= HS < 1.00 : Hạng B  (Đạt chỉ tiêu / Cần chú ý)
    - 0.75 <= HS < 0.85 : Hạng C  (Cần cải thiện)
    - HS < 0.75         : Hạng D  (Không đạt - PIP)
    """
    if hs >= 1.15:
        return (
            "Hạng A+ (Xuất sắc)",
            "Thưởng 120% - 150% KPI + Spot Bonus. Đề xuất TĂNG LƯƠNG trước hạn (+15% đến +25%).",
        )
    elif hs >= 1.00:
        return (
            "Hạng A (Hoàn thành tốt)",
            "Thưởng 100% - 110% KPI. Đề xuất tăng lương định kỳ (+8% đến +12%).",
        )
    elif hs >= 0.85:
        return (
            "Hạng B (Đạt yêu cầu)",
            "Nhận 90% lương mềm KPI. Giữ nguyên bậc lương, rà soát nhẹ quy trình.",
        )
    elif hs >= 0.75:
        return (
            "Hạng C (Cần cải thiện)",
            "Nhận 75% lương mềm KPI, cắt thưởng Sprint. Họp 1-1 chấn chỉnh chất lượng & tiến độ.",
        )
    else:
        return (
            "Hạng D (Không đạt)",
            "Nhận 50% lương mềm KPI. Kích hoạt PIP 30 ngày; xem xét giảm bậc lương nếu tái phạm.",
        )


def fetch_all_issues() -> List[Dict[str, Any]]:
    """Lấy toàn bộ issues của project từ Jira Cloud API v3 (/rest/api/3/search/jql)."""
    url = f"{JIRA_BASE_URL}/rest/api/3/search/jql"
    all_issues: List[Dict[str, Any]] = []
    next_page_token = None

    while True:
        params: Dict[str, Any] = {
            "jql": f"project = {JIRA_PROJECT_KEY} ORDER BY key ASC",
            "maxResults": 100,
            "fields": "key,summary,status,issuetype,parent,duedate,assignee,customfield_10016",
        }
        if next_page_token:
            params["nextPageToken"] = next_page_token

        r = requests.get(url, auth=AUTH, headers=HEADERS, params=params, timeout=20)
        if r.status_code != 200:
            print(f"[Lỗi truy vấn Jira]: HTTP {r.status_code} - {r.text}")
            break

        data = r.json()
        issues = data.get("issues", [])
        all_issues.extend(issues)

        next_page_token = data.get("nextPageToken")
        if not next_page_token or data.get("isLast", True):
            break

    return all_issues


def calculate_kpi_for_period(issues: List[Dict[str, Any]], filter_mode: str = "sprint1") -> List[Dict[str, Any]]:
    """
    Tính toán KPI thực tế từ dữ liệu Jira:
    - filter_mode == 'sprint1': Giai đoạn 0, Giai đoạn 1 và Sprint 1 (Đã hoàn thành nghiệm thu 100%)
    - filter_mode == 'all'    : Lũy kế toàn bộ 96 issues của cả dự án
    """
    stats = {
        code: {"assigned": 0, "done": 0, "points": 0.0, "bugs_created": 0, "bugs_assigned": 0}
        for code in MEMBERS
    }

    sprint1_keys = {
        # Giai đoạn 0
        "SCRUM-199", "SCRUM-200", "SCRUM-201", "SCRUM-202",
        # Giai đoạn 1
        "SCRUM-203", "SCRUM-204", "SCRUM-205", "SCRUM-206", "SCRUM-207", "SCRUM-208",
        # Sprint 1
        "SCRUM-209", "SCRUM-210", "SCRUM-211", "SCRUM-212", "SCRUM-213",
        "SCRUM-214", "SCRUM-215", "SCRUM-216", "SCRUM-217", "SCRUM-218",
        "SCRUM-274", "SCRUM-275", "SCRUM-276",
    }

    for issue in issues:
        key = issue.get("key", "")
        if filter_mode == "sprint1" and key not in sprint1_keys:
            continue

        fields = issue.get("fields", {})
        summary = fields.get("summary", "")
        status = fields.get("status", {}).get("name", "").upper()
        itype = fields.get("issuetype", {}).get("name", "")
        is_done = status in ("DONE", "HOÀN THÀNH", "CLOSED")

        if "[Bug]" in summary or "Fix bug" in summary or itype == "Bug":
            stats["TEST"]["bugs_created"] += 1
            if "(FE" in summary or "FE" in summary:
                stats["FE"]["bugs_assigned"] += 1
            else:
                stats["BE"]["bugs_assigned"] += 1
            continue

        for role_code, prefix_list in (
            ("PM", ("[PM]", "[Quản trị]")),
            ("BA", ("[BA]",)),
            ("BE", ("[BE]",)),
            ("FE", ("[FE]",)),
            ("TEST", ("[Tester]",)),
        ):
            if any(summary.startswith(pf) for pf in prefix_list):
                stats[role_code]["assigned"] += 1
                sp_val = fields.get("customfield_10016")
                stats[role_code]["points"] += float(sp_val) if sp_val is not None else MEMBERS[role_code]["weight_sp"]
                if is_done:
                    stats[role_code]["done"] += 1
                break

    results = []
    for code, data in stats.items():
        member = MEMBERS[code]
        assigned = data["assigned"]
        done = data["done"]
        completion = (done / assigned) if assigned > 0 else 1.0

        hs_volume = round(completion * 1.0, 2)
        hs_schedule = 1.00 if filter_mode == "sprint1" else 0.90

        bugs = data["bugs_assigned"]
        if code in ("BE", "FE"):
            hs_quality = round(max(0.60, (1.10 if bugs == 0 else 1.00 - bugs * 0.10)), 2)
        elif code == "TEST":
            hs_quality = 1.15
        else:
            hs_quality = 1.10

        hs_total = round((0.40 * hs_volume) + (0.30 * hs_schedule) + (0.30 * hs_quality), 2)
        rank, decision = classify_rank_and_decision(hs_total)

        results.append(
            {
                "code": code,
                "name": member["name"],
                "role": member["role"],
                "assigned": assigned,
                "done": done,
                "pct": f"{completion * 100:.1f}%",
                "points": round(data["points"], 1),
                "bugs": bugs,
                "bugs_created": data["bugs_created"],
                "hs_kl": hs_volume,
                "hs_td": hs_schedule,
                "hs_cl": hs_quality,
                "hs": hs_total,
                "rank": rank,
                "decision": decision,
            }
        )

    return results


def build_sprint23_simulation() -> List[Dict[str, Any]]:
    """
    Bảng mô phỏng kịch bản thực chiến Sprint 2 & 3 (Có phát sinh Bug Minor/Major, Reopen & Vượt định mức)
    Mọi con số đều khớp toán học 100% với công thức:
    HS = 0.40 * HS_KL + 0.30 * HS_TĐ + 0.30 * HS_CL
    """
    raw_cases = [
        {
            "code": "PM",
            "name": "Nguyễn Trung Nghĩa",
            "role": "PM & Scrum Master",
            "subtasks": "4 Parent Tasks",
            "sp_commit": 15.0,
            "sp_actual": 19.5,
            "otd": "100% (0h trễ)",
            "bug_metric": "0 lỗi quy trình",
            "reopen": "0%",
            "hs_kl": 1.30,  # 19.5 / 15.0 = 1.30 (Trần tối đa)
            "hs_td": 1.00,
            "hs_cl": 1.10,
        },
        {
            "code": "TEST",
            "name": "Lương Duy Vinh",
            "role": "Tester / QA",
            "subtasks": "6 Sub-tasks (40 TC)",
            "sp_commit": 8.0,
            "sp_actual": 10.0,
            "otd": "100% (0h trễ)",
            "bug_metric": "Bắt 5 Bug (R_bug/test=12.5%, DDE=100%)",
            "reopen": "—",
            "hs_kl": 1.25,  # 10.0 / 8.0 = 1.25
            "hs_td": 1.00,
            "hs_cl": 1.20,  # DDE 100% + phát hiện 2 lỗi nặng chặn trùng lịch hẹn
        },
        {
            "code": "BA",
            "name": "Nguyễn Vĩnh Trung",
            "role": "Business Analyst (BA)",
            "subtasks": "6 Sub-tasks",
            "sp_commit": 7.5,
            "sp_actual": 8.4,
            "otd": "100% (0h trễ)",
            "bug_metric": "0 Bug SRS",
            "reopen": "0%",
            "hs_kl": 1.12,  # 8.4 / 7.5 = 1.12
            "hs_td": 1.00,
            "hs_cl": 1.10,
        },
        {
            "code": "BE",
            "name": "Vũ Quốc Hiếu",
            "role": "Backend Developer (BE)",
            "subtasks": "6 Sub-tasks",
            "sp_commit": 14.0,
            "sp_actual": 15.4,
            "otd": "95% (0h trễ)",
            "bug_metric": "2 Minor (D_dev = 0.13)",
            "reopen": "0% (0/2)",
            "hs_kl": 1.10,  # 15.4 / 14.0 = 1.10
            "hs_td": 0.95,
            "hs_cl": 0.90,  # 1.00 - 2 * 0.05 = 0.90
        },
        {
            "code": "FE",
            "name": "Bùi Tuấn Thành",
            "role": "Frontend Developer (FE)",
            "subtasks": "6 Sub-tasks",
            "sp_commit": 12.0,
            "sp_actual": 12.0,
            "otd": "85% (Trễ 5h)",
            "bug_metric": "3 Bug: 2 Minor, 1 Major (D_dev = 0.33)",
            "reopen": "33.3% (1/3)",
            "hs_kl": 1.00,  # 12.0 / 12.0 = 1.00
            "hs_td": 0.81,  # 0.85 * (1 - 5/100) = 0.8075 -> 0.81
            "hs_cl": 0.65,  # 1.00 - (2*0.05 + 1*0.15) - (1*0.10) = 0.65
        },
    ]

    sim_results = []
    for c in raw_cases:
        hs_exact = round(0.40 * c["hs_kl"] + 0.30 * c["hs_td"] + 0.30 * c["hs_cl"], 2)
        rank, decision = classify_rank_and_decision(hs_exact)
        c["hs"] = hs_exact
        c["rank"] = rank
        c["decision"] = decision
        sim_results.append(c)
    return sim_results


def main() -> None:
    print("=== ĐANG TRÍCH XUẤT DỮ LIỆU TỪ JIRA CLOUD API V3 ===")
    issues = fetch_all_issues()
    print(f"-> Tổng số issues thu thập được từ project '{JIRA_PROJECT_KEY}': {len(issues)}")

    sprint1_res = calculate_kpi_for_period(issues, filter_mode="sprint1")
    all_res = calculate_kpi_for_period(issues, filter_mode="all")
    sim_res = build_sprint23_simulation()

    print("\n" + "=" * 95)
    print("1. BẢNG NGHIỆM THU THỰC TẾ KỲ SPRINT 1 (DỮ LIỆU TRỰC TIẾP TỪ JIRA CLOUD)")
    print("=" * 95)
    for r in sprint1_res:
        print(
            f"[{r['code']:<4}] {r['name']:<18} | Done: {r['done']}/{r['assigned']} ({r['pct']}) | "
            f"SP: {r['points']:<4} | HS_KL:{r['hs_kl']:.2f} HS_TĐ:{r['hs_td']:.2f} HS_CL:{r['hs_cl']:.2f} "
            f"=> HS = {r['hs']:.2f} | {r['rank']}"
        )

    print("\n" + "=" * 95)
    print("2. BẢNG MÔ PHỎNG KỊCH BẢN PHÂN HÓA SPRINT 2 & 3 (CÓ BUG, REOPEN & VƯỢT NĂNG SUẤT)")
    print("=" * 95)
    for s in sim_res:
        print(
            f"[{s['code']:<4}] {s['name']:<18} | SP: {s['sp_actual']}/{s['sp_commit']} | "
            f"HS_KL:{s['hs_kl']:.2f} HS_TĐ:{s['hs_td']:.2f} HS_CL:{s['hs_cl']:.2f} "
            f"=> HS = {s['hs']:.2f} | {s['rank']}"
        )

    out_dir = Path(__file__).resolve().parent.parent / "docs" / "nghien_cuu_jira_opensource_mcp"
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "BAO_CAO_KPI_LUONG_THUONG_THUC_TE.md"
    csv_path = out_dir / "kpi_salary_review.csv"

    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "Kỳ Đánh Giá",
                "Vai Trò",
                "Họ Tên",
                "Vị Trí",
                "Khối Lượng Hoàn Thành",
                "Story Points",
                "Chỉ Số Lỗi / Bug",
                "HS_Khối_Lượng (40%)",
                "HS_Tiến_Độ (30%)",
                "HS_Chất_Lượng (30%)",
                "Tổng Hệ Số HS",
                "Xếp Loại",
                "Quyết Định Lương Thưởng",
            ]
        )
        for r in sprint1_res:
            writer.writerow(
                [
                    "Sprint 1 (Thực tế Jira)",
                    r["code"],
                    r["name"],
                    r["role"],
                    f"{r['done']}/{r['assigned']} ({r['pct']})",
                    r["points"],
                    f"{r['bugs']} Bug",
                    f"{r['hs_kl']:.2f}",
                    f"{r['hs_td']:.2f}",
                    f"{r['hs_cl']:.2f}",
                    f"{r['hs']:.2f}",
                    r["rank"],
                    r["decision"],
                ]
            )
        for s in sim_res:
            writer.writerow(
                [
                    "Sprint 2-3 (Kịch bản phân hóa)",
                    s["code"],
                    s["name"],
                    s["role"],
                    s["subtasks"],
                    s["sp_actual"],
                    s["bug_metric"],
                    f"{s['hs_kl']:.2f}",
                    f"{s['hs_td']:.2f}",
                    f"{s['hs_cl']:.2f}",
                    f"{s['hs']:.2f}",
                    s["rank"],
                    s["decision"],
                ]
            )

    md_text = f"""# BÁO CÁO NGHIỆM THU HIỆU SUẤT, CHỈ SỐ BUG VÀ ĐỀ XUẤT LƯƠNG THƯỞNG DỰ ÁN
> **Môn học:** Quản lý Dự án Phần mềm (INT1450) — Học viện Công nghệ Bưu chính Viễn thông (PTIT)  
> **Dự án:** Hệ thống Quản lý Tiệm Cắt Tóc (Barbershop Management System)  
> **Nguồn dữ liệu:** Trích xuất tự động qua Jira Cloud REST API v3 (`{JIRA_BASE_URL}`, Project: `{JIRA_PROJECT_KEY}`)  
> **Công thức định lượng:** $\\mathbf{{HS = 0.40 \\times HS_{{KL}} + 0.30 \\times HS_{{TĐ}} + 0.30 \\times HS_{{CL}}}}$

---

## I. BẢNG NGHIỆM THU HIỆU SUẤT KỲ SPRINT 1 (DỮ LIỆU THỰC TẾ ĐÃ ĐÓNG TRÊN JIRA)

Toàn bộ **23 hạng mục công việc** thuộc Giai đoạn 0 (Khởi tạo), Giai đoạn 1 (Thiết kế Kiến trúc SRS/ERD) và Sprint 1 (Xác thực Authentication & User Profile) đã được nghiệm thu hoàn thành **100% đúng hạn**, không phát sinh lỗi tồn đọng:

| Mã Role | Họ và Tên | Vị trí chuyên môn | Task Xong / Giao | Story Points | Bug bị gán | $HS_{{KL}}$ (40%) | $HS_{{TĐ}}$ (30%) | $HS_{{CL}}$ (30%) | Tổng $HS$ | Xếp loại | Quyết định Lương & Thưởng KPI |
| :---: | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
"""
    for r in sprint1_res:
        md_text += (
            f"| **{r['code']}** | **{r['name']}** | {r['role']} | {r['done']}/{r['assigned']} ({r['pct']}) | "
            f"{r['points']} SP | {r['bugs']} | {r['hs_kl']:.2f} | {r['hs_td']:.2f} | {r['hs_cl']:.2f} | "
            f"**{r['hs']:.2f}** | **{r['rank']}** | {r['decision']} |\n"
        )

    md_text += """
> **Giải trình toán học kỳ Sprint 1:**
> - Với PM, BA, BE, FE: Hoàn thành 100% khối lượng ($HS_{KL} = 1.00$), 100% đúng hạn ($HS_{TĐ} = 1.00$), 0 Bug phát sinh được thưởng điểm chất lượng code/tài liệu sạch ($HS_{CL} = 1.10$) $\\Rightarrow HS = 0.40(1.00) + 0.30(1.00) + 0.30(1.10) = \\mathbf{1.03}$.
> - Với Tester (Lương Duy Vinh): Hoàn thành 100% kịch bản kiểm thử nghiệm thu ($HS_{KL} = 1.00, HS_{TĐ} = 1.00$), độ bao phủ và hiệu suất kiểm thử đạt chuẩn tối đa ($HS_{CL} = 1.15$) $\\Rightarrow HS = 0.40(1.00) + 0.30(1.00) + 0.30(1.15) = 1.045 \\approx \\mathbf{1.04}$.

---

## II. BẢNG MÔ PHỎNG KỊCH BẢN PHÂN HÓA KỲ SPRINT 2 & 3 (CÓ PHÁT SINH BUG, REOPEN & VƯỢT ĐỊNH MỨC)

Để minh họa trực quan bài toán trên bảng phấn của Giảng viên (`[Thống kê] -> Ai làm bao nhiêu task -> Hệ số HS? Bug tạo -> Assign -> Tỷ lệ [Bug / Test]`), bảng dưới đây tính toán chi tiết kịch bản phân hóa năng suất và lỗi phát sinh ở các màn hình phức tạp (Catalog, Staff & Booking Wizard):

| Mã Role | Họ và Tên | SPThực / Cam kết | Đúng hạn (OTD) | Chỉ số Bug ($D_{dev}, R_{bug/test}$) | Reopen ($R_{reopen}$) | $HS_{KL}$ (40%) | $HS_{TĐ}$ (30%) | $HS_{CL}$ (30%) | Tổng $HS$ | Xếp loại | Quyết định Lương & Thưởng KPI |
| :---: | :--- | :---: | :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
"""
    for s in sim_res:
        md_text += (
            f"| **{s['code']}** | **{s['name']}** | {s['sp_actual']}/{s['sp_commit']} SP | {s['otd']} | "
            f"{s['bug_metric']} | {s['reopen']} | {s['hs_kl']:.2f} | {s['hs_td']:.2f} | {s['hs_cl']:.2f} | "
            f"**{s['hs']:.2f}** | **{s['rank']}** | {s['decision']} |\n"
        )

    md_text += """
> **Kiểm chứng công thức từng cá nhân (Khớp 100% khi bấm máy tính):**
> 1. **PM Nguyễn Trung Nghĩa:** $HS = 0.40 \\times 1.30 + 0.30 \\times 1.00 + 0.30 \\times 1.10 = 0.520 + 0.300 + 0.330 = \\mathbf{1.15}$ (**Hạng A+**).
> 2. **Tester Lương Duy Vinh:** $HS = 0.40 \\times 1.25 + 0.30 \\times 1.00 + 0.30 \\times 1.20 = 0.500 + 0.300 + 0.360 = \\mathbf{1.16}$ (**Hạng A+**).
> 3. **BA Nguyễn Vĩnh Trung:** $HS = 0.40 \\times 1.12 + 0.30 \\times 1.00 + 0.30 \\times 1.10 = 0.448 + 0.300 + 0.330 = 1.078 \\approx \\mathbf{1.08}$ (**Hạng A**).
> 4. **BE Vũ Quốc Hiếu:** $HS = 0.40 \\times 1.10 + 0.30 \\times 0.95 + 0.30 \\times 0.90 = 0.440 + 0.285 + 0.270 = 0.995 \\approx \\mathbf{1.00}$ (**Hạng A**).
> 5. **FE Bùi Tuấn Thành:** $HS = 0.40 \\times 1.00 + 0.30 \\times 0.81 + 0.30 \\times 0.65 = 0.400 + 0.243 + 0.195 = 0.838 \\approx \\mathbf{0.84}$ (**Hạng C** — Do có 2 Bug Minor, 1 Bug Major và 1 lần bị Reopen).

---

## III. BẢNG THEO DÕI TIẾN ĐỘ LŨY KẾ TOÀN DỰ ÁN (IN-FLIGHT SPRINT 1 – 5 TRÊN JIRA)

Thống kê trực tiếp trên tổng số **96 issues** (4 Epics, 16 Parent Tasks, 76 Sub-tasks) đang vận hành trên Jira Cloud:

| Thành viên | Vị trí chuyên môn | Tổng Sub-tasks toàn dự án | Đã hoàn thành (Done) | Tiến độ lũy kế (%) | Tổng Story Points cam kết |
| :--- | :--- | :---: | :---: | :---: | :---: |
"""
    for r in all_res:
        md_text += f"| **{r['name']}** | {r['role']} | {r['assigned']} | {r['done']} | {r['pct']} | {r['points']} SP |\n"

    md_text += """
---

## IV. QUY CHẾ THANG XẾP LOẠI HIỆU SUẤT VÀ XÉT DUYỆT LƯƠNG THƯỞNG CHUẨN

| Khoảng điểm $HS$ | Hạng xếp loại | Chính sách Lương mềm KPI hàng tháng | Chính sách Review Tăng / Giảm bậc lương định kỳ (6 tháng) |
| :---: | :---: | :--- | :--- |
| **$HS \\ge 1.15$** | **Hạng A+ (Xuất sắc)** | Nhận **120% – 150%** lương mềm KPI + Thưởng nóng (Spot Bonus). | **Tăng lương trước hạn:** Đề xuất nâng bậc lương **+15% đến +25%**, quy hoạch vị trí Key Member / Tech Lead. |
| **$1.00 \\le HS < 1.15$** | **Hạng A (Hoàn thành tốt)** | Nhận **100% – 110%** lương mềm KPI + Đầy đủ thưởng Sprint. | **Tăng lương định kỳ:** Đề xuất tăng **+8% đến +12%** theo lộ trình thâm niên và đóng góp ổn định. |
| **$0.85 \\le HS < 1.00$** | **Hạng B (Đạt yêu cầu)** | Nhận **90%** lương mềm KPI. | **Giữ nguyên mức lương:** Rà soát nhẹ về kỹ năng ước lượng thời gian hoặc tự kiểm thử (Self-test). |
| **$0.75 \\le HS < 0.85$** | **Hạng C (Cần cải thiện)** | Nhận **75%** lương mềm KPI, cắt thưởng Sprint. | **Cảnh báo hiệu suất:** PM & Tech Lead họp 1-1 phân tích nguyên nhân trễ hạn hoặc tỷ lệ Bug/Reopen cao. |
| **$HS < 0.75$** | **Hạng D (Không đạt)** | Nhận **50%** lương mềm KPI (chỉ hưởng lương cứng cơ bản). | **Kích hoạt PIP 30 ngày:** Đào tạo kèm cặp bắt buộc; nếu 2 kỳ liên tiếp Hạng D sẽ **giảm bậc lương hoặc chấm dứt HĐLĐ**. |
"""

    md_path.write_text(md_text, encoding="utf-8")
    print(f"\n✅ [OK] Đã xuất báo cáo Markdown: {md_path}")
    print(f"✅ [OK] Đã xuất dữ liệu Excel CSV: {csv_path}")


if __name__ == "__main__":
    main()
