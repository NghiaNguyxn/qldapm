# -*- coding: utf-8 -*-
"""
Script Đồng bộ trực tiếp 95 Issues (4 Epics, 19 Tasks, 72 Sub-tasks) từ Jira_Import_QLDAPM_Standard_Ratio.csv
lên Jira Cloud (Project SCRUM: SCRUM-195 -> SCRUM-289) qua Jira REST API v3.
Đảm bảo 100% khớp lịch trình bậc thang cuốn chiếu (Staggered Staircase) và tỷ lệ 5 giai đoạn của Giảng viên.
"""

import csv
import sys
from pathlib import Path
from typing import Dict, Any
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.jira_ops_mcp_server import JIRA_BASE_URL, AUTH, HEADERS, _build_adf_comment

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Bản đồ ánh xạ chính xác 1-1 giữa Issue ID trong CSV chuẩn (95 dòng) và Issue Key trên Jira Cloud (SCRUM-195..289)
CSV_ID_TO_JIRA_KEY: Dict[int, str] = {
    # 4 Epics
    1: "SCRUM-198",
    2: "SCRUM-195",
    3: "SCRUM-196",
    4: "SCRUM-197",
    # 19 Tasks
    10: "SCRUM-199",
    11: "SCRUM-203",
    12: "SCRUM-209",
    13: "SCRUM-214",
    14: "SCRUM-219",
    15: "SCRUM-224",
    16: "SCRUM-229",
    17: "SCRUM-234",
    18: "SCRUM-239",
    19: "SCRUM-244",
    20: "SCRUM-249",
    21: "SCRUM-254",
    22: "SCRUM-259",
    23: "SCRUM-264",
    24: "SCRUM-269",
    25: "SCRUM-274",
    27: "SCRUM-277",
    28: "SCRUM-280",
    26: "SCRUM-283",
    # Sub-tasks của Task 10 (Lập KH=200, RACI=201, BA Khảo sát=202)
    101: "SCRUM-200",
    103: "SCRUM-201",
    102: "SCRUM-202",
    # Sub-tasks của Task 11 (104..108 -> SCRUM-204..208)
    104: "SCRUM-204",
    105: "SCRUM-205",
    106: "SCRUM-206",
    107: "SCRUM-207",
    108: "SCRUM-208",
    # Sub-tasks của Task 12..24 (mỗi màn hình 4 sub-tasks)
    109: "SCRUM-210", 110: "SCRUM-211", 111: "SCRUM-212", 112: "SCRUM-213",
    113: "SCRUM-215", 114: "SCRUM-216", 115: "SCRUM-217", 116: "SCRUM-218",
    117: "SCRUM-220", 118: "SCRUM-221", 119: "SCRUM-222", 120: "SCRUM-223",
    121: "SCRUM-225", 122: "SCRUM-226", 123: "SCRUM-227", 124: "SCRUM-228",
    125: "SCRUM-230", 126: "SCRUM-231", 127: "SCRUM-232", 128: "SCRUM-233",
    129: "SCRUM-235", 130: "SCRUM-236", 131: "SCRUM-237", 132: "SCRUM-238",
    133: "SCRUM-240", 134: "SCRUM-241", 135: "SCRUM-242", 136: "SCRUM-243",
    137: "SCRUM-245", 138: "SCRUM-246", 139: "SCRUM-247", 140: "SCRUM-248",
    141: "SCRUM-250", 142: "SCRUM-251", 143: "SCRUM-252", 144: "SCRUM-253",
    145: "SCRUM-255", 146: "SCRUM-256", 147: "SCRUM-257", 148: "SCRUM-258",
    149: "SCRUM-260", 150: "SCRUM-261", 151: "SCRUM-262", 152: "SCRUM-263",
    153: "SCRUM-265", 154: "SCRUM-266", 155: "SCRUM-267", 156: "SCRUM-268",
    157: "SCRUM-270", 158: "SCRUM-271", 159: "SCRUM-272", 160: "SCRUM-273",
    # Sub-tasks của Task 25, 27, 28, 26
    161: "SCRUM-275", 162: "SCRUM-276",
    163: "SCRUM-278", 164: "SCRUM-279",
    165: "SCRUM-281", 166: "SCRUM-282",
    167: "SCRUM-284", 168: "SCRUM-285", 169: "SCRUM-286", 170: "SCRUM-287", 171: "SCRUM-288", 172: "SCRUM-289",
}


def sync_jira_cloud() -> None:
    csv_path = Path(__file__).resolve().parent.parent / "Jira_Import_QLDAPM_Standard_Ratio.csv"
    with open(csv_path, mode="r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    print(f"Bắt đầu đồng bộ {len(rows)} Issues lên Jira Cloud ({JIRA_BASE_URL})...")
    ok_count = 0
    err_count = 0

    for r in rows:
        csv_id = int(r["Issue ID"])
        jira_key = CSV_ID_TO_JIRA_KEY.get(csv_id)
        if not jira_key:
            print(f"  [SKIP] Không tìm thấy mapping cho CSV ID={csv_id}")
            continue

        summary = r["Summary"].strip()
        desc_raw = r["Description"].strip()
        sdate = r["Start Date"].strip()
        ddate = r["Due Date"].strip()
        sp = float(r["Story Points"] or 0)

        payload: Dict[str, Any] = {
            "fields": {
                "summary": summary,
                "description": _build_adf_comment(desc_raw)["body"],
                "customfield_10015": sdate,
                "duedate": ddate,
                "customfield_10016": sp,
            }
        }

        resp = requests.put(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{jira_key}?notifyUsers=false",
            auth=AUTH,
            headers=HEADERS,
            json=payload,
            timeout=20,
        )

        if resp.status_code in (200, 204):
            ok_count += 1
            print(f"  [OK] {jira_key:<10} ({r['Issue Type']:<8}) | {sdate} -> {ddate} | SP={sp:<4} | {summary[:50]}")
        else:
            err_count += 1
            print(f"  [ERR] {jira_key} (CSV ID={csv_id}): HTTP {resp.status_code} - {resp.text[:200]}")

    print("==================================================================")
    print(f"HOÀN TẤT ĐỒNG BỘ JIRA CLOUD: Thành công {ok_count}/{len(rows)} Issues (Lỗi: {err_count})")
    print("==================================================================")


if __name__ == "__main__":
    sync_jira_cloud()
