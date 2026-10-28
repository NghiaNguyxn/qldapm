"""
Domain 10: Project Management Intelligence — EVM (Earned Value Management),
WBS Tree & 100% Rule Auditor, Team Workload Balancing, and Member KPI Scorecard.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from ..client import OpenProjectClient
from ..hal_normalizer import normalize_time_entry, normalize_work_package
from ..registry import ToolRegistry


def _parse_date(d_str: Optional[str]) -> Optional[date]:
    if not d_str or not isinstance(d_str, str):
        return None
    try:
        return datetime.strptime(d_str[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_analyze_project_evm",
        description=(
            "Compute complete PMBOK Earned Value Management (EVM) metrics for an OpenProject project: "
            "BAC (Budget at Completion in hours/cost), PV (Planned Value), EV (Earned Value), "
            "AC (Actual Cost/Spent Hours), CV, SV, CPI, SPI, EAC, ETC, VAC, and TCPI."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "status_date": {
                "type": "string",
                "description": "Reference evaluation date (YYYY-MM-DD, defaults to today).",
            },
            "hourly_rate": {
                "type": "number",
                "description": "Optional standard hourly cost rate (e.g. 15.0 USD/h or 200000 VND/h) to convert hours into currency.",
                "default": 1.0,
            },
        },
        domain="pm_analytics",
        read_only=True,
        idempotent=True,
    )
    def op_analyze_project_evm(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_read_project(proj_id)

        ref_date = _parse_date(args.get("status_date")) or date.today()
        rate = float(args.get("hourly_rate", 1.0))

        raw_wps, _ = client.fetch_all_elements(
            f"/api/v3/projects/{proj_id}/work_packages",
            params={"filters": "[]", "sortBy": json.dumps([["id", "asc"]])},
            max_items=500,
        )
        wps = [normalize_work_package(w, sanitize=False, include_description=False) for w in raw_wps]

        # Avoid double counting parent and child tasks: only sum leaf tasks (tasks with no children in the set)
        parent_ids = {int((w.get("parent") or {}).get("id")) for w in wps if (w.get("parent") or {}).get("id")}
        leaf_wps = [w for w in wps if int(w["id"]) not in parent_ids]
        if not leaf_wps:
            leaf_wps = wps

        bac_hours = 0.0
        pv_hours = 0.0
        ev_hours = 0.0
        ac_hours = 0.0

        for w in leaf_wps:
            est = float(w.get("estimatedHours") or 0.0)
            spent = float(w.get("spentHours") or 0.0)
            pct = float(w.get("percentageDone") or 0.0) / 100.0
            st_name = str((w.get("status") or {}).get("name") or "").lower()
            if pct == 0.0 and st_name in ("closed", "done", "resolved", "completed"):
                pct = 1.0

            bac_hours += est
            ev_hours += est * pct
            ac_hours += spent

            # Planned % by reference date
            sd = _parse_date(w.get("startDate") or w.get("derivedStartDate"))
            dd = _parse_date(w.get("dueDate") or w.get("derivedDueDate"))
            if sd and dd:
                if ref_date >= dd:
                    planned_pct = 1.0
                elif ref_date < sd:
                    planned_pct = 0.0
                else:
                    total_days = max(1, (dd - sd).days + 1)
                    elapsed_days = max(0, (ref_date - sd).days + 1)
                    planned_pct = min(1.0, elapsed_days / total_days)
            elif dd and ref_date >= dd:
                planned_pct = 1.0
            else:
                planned_pct = pct

            pv_hours += est * planned_pct

        # If AC from work packages is 0, check time_entries endpoint directly
        if ac_hours == 0.0:
            try:
                raw_te, _ = client.fetch_all_elements(
                    "/api/v3/time_entries",
                    params={"filters": json.dumps([{"project": {"operator": "=", "values": [str(proj_id)]}}])},
                    max_items=500,
                )
                ac_hours = sum(
                    float(normalize_time_entry(e, sanitize=False).get("hours") or 0.0)
                    for e in raw_te
                )
            except Exception:
                pass

        bac = round(bac_hours * rate, 2)
        pv = round(pv_hours * rate, 2)
        ev = round(ev_hours * rate, 2)
        ac = round(ac_hours * rate, 2)

        cv = round(ev - ac, 2)
        sv = round(ev - pv, 2)
        cpi = round(ev / ac, 3) if ac > 0 else (1.0 if ev > 0 else 0.0)
        spi = round(ev / pv, 3) if pv > 0 else (1.0 if ev > 0 else 0.0)

        eac = round(bac / cpi, 2) if cpi > 0 else round(ac + (bac - ev), 2)
        etc = round(max(0.0, eac - ac), 2)
        vac = round(bac - eac, 2)
        denom_tcpi = bac - ac
        tcpi = round((bac - ev) / denom_tcpi, 3) if denom_tcpi > 0 else None

        return {
            "projectId": proj_id,
            "statusDate": ref_date.isoformat(),
            "leafTaskCount": len(leaf_wps),
            "totalTaskCount": len(wps),
            "hourlyRate": rate,
            "metrics": {
                "BAC": bac,
                "PV": pv,
                "EV": ev,
                "AC": ac,
                "CV": cv,
                "SV": sv,
                "CPI": cpi,
                "SPI": spi,
                "EAC": eac,
                "ETC": etc,
                "VAC": vac,
                "TCPI": tcpi,
            },
            "diagnosis": {
                "costStatus": "Under Budget (CPI >= 1)" if cpi >= 1.0 else "Over Budget (CPI < 1)",
                "scheduleStatus": "Ahead / On Schedule (SPI >= 1)" if spi >= 1.0 else "Behind Schedule (SPI < 1)",
            },
        }

    @registry.register(
        name="op_generate_wbs_tree",
        description=(
            "Build the complete hierarchical Work Breakdown Structure (WBS) tree of a project "
            "(Epic -> Phase -> User Story -> Task -> Subtask) and audit compliance with the "
            "PMBOK 100% Rule (comparing parent estimated hours and dates against child rollups)."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
        },
        domain="pm_analytics",
        read_only=True,
        idempotent=True,
    )
    def op_generate_wbs_tree(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_read_project(proj_id)

        raw_wps, _ = client.fetch_all_elements(
            f"/api/v3/projects/{proj_id}/work_packages",
            params={"filters": "[]", "sortBy": json.dumps([["id", "asc"]])},
            max_items=500,
        )
        wps = [normalize_work_package(w, sanitize=False, include_description=False) for w in raw_wps]
        by_id: Dict[int, Dict[str, Any]] = {}
        children_map: Dict[int, List[int]] = defaultdict(list)
        roots: List[int] = []

        for w in wps:
            wid = int(w["id"])
            by_id[wid] = w

        for wid, w in by_id.items():
            pid = (w.get("parent") or {}).get("id")
            if pid and int(pid) in by_id:
                children_map[int(pid)].append(wid)
            else:
                roots.append(wid)

        rollup_discrepancies: List[Dict[str, Any]] = []

        def _build_node(wid: int, wbs_code: str) -> Dict[str, Any]:
            w = by_id[wid]
            c_ids = children_map.get(wid, [])
            child_nodes = [
                _build_node(cid, f"{wbs_code}.{idx + 1}")
                for idx, cid in enumerate(c_ids)
            ]
            own_est = float(w.get("estimatedHours") or 0.0)
            children_est_sum = round(sum(c["rollupEstimatedHours"] for c in child_nodes), 2)
            rollup_est = children_est_sum if child_nodes else own_est

            if child_nodes and own_est > 0 and abs(own_est - children_est_sum) > 0.1:
                rollup_discrepancies.append({
                    "id": wid,
                    "wbsCode": wbs_code,
                    "subject": w.get("subject"),
                    "ownEstimatedHours": own_est,
                    "childrenSumHours": children_est_sum,
                    "differenceHours": round(own_est - children_est_sum, 2),
                })

            return {
                "wbsCode": wbs_code,
                "id": wid,
                "subject": w.get("subject"),
                "type": (w.get("type") or {}).get("name"),
                "status": (w.get("status") or {}).get("name"),
                "assignee": (w.get("assignee") or {}).get("name"),
                "startDate": w.get("startDate") or w.get("derivedStartDate"),
                "dueDate": w.get("dueDate") or w.get("derivedDueDate"),
                "percentageDone": w.get("percentageDone") or w.get("derivedPercentageDone") or 0,
                "ownEstimatedHours": own_est,
                "rollupEstimatedHours": rollup_est,
                "children": child_nodes,
            }

        tree = [_build_node(rid, str(idx + 1)) for idx, rid in enumerate(roots)]
        return {
            "projectId": proj_id,
            "totalWorkPackages": len(by_id),
            "rootCount": len(roots),
            "wbs100PercentRuleDiscrepancies": rollup_discrepancies,
            "wbsTree": tree,
        }

    @registry.register(
        name="op_analyze_team_workload",
        description=(
            "Analyze resource allocation and workload across all assignees in a project: "
            "counts open vs closed tasks, total estimated hours, remaining hours, spent hours, "
            "overdue tasks, and identifies overloaded or unassigned bottlenecks."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "capacity_hours_threshold": {
                "type": "number",
                "description": "Threshold of open estimated hours per member before flagging as overloaded (default 40h).",
                "default": 40.0,
            },
        },
        domain="pm_analytics",
        read_only=True,
        idempotent=True,
    )
    def op_analyze_team_workload(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_read_project(proj_id)

        threshold = float(args.get("capacity_hours_threshold", 40.0))
        today = date.today()

        raw_wps, _ = client.fetch_all_elements(
            f"/api/v3/projects/{proj_id}/work_packages",
            params={"filters": "[]", "sortBy": json.dumps([["id", "asc"]])},
            max_items=500,
        )
        wps = [normalize_work_package(w, sanitize=False, include_description=False) for w in raw_wps]

        # Exclude parent containers if they have children to avoid double-counting effort
        parent_ids = {int((w.get("parent") or {}).get("id")) for w in wps if (w.get("parent") or {}).get("id")}
        leaf_wps = [w for w in wps if int(w["id"]) not in parent_ids] or wps

        stats: Dict[str, Dict[str, Any]] = {}
        for w in leaf_wps:
            assignee = w.get("assignee") or {}
            u_name = assignee.get("name") or "Unassigned"
            u_id = assignee.get("id")
            if u_name not in stats:
                stats[u_name] = {
                    "userId": u_id,
                    "userName": u_name,
                    "totalTasks": 0,
                    "openTasks": 0,
                    "closedTasks": 0,
                    "overdueTasks": 0,
                    "estimatedHours": 0.0,
                    "openEstimatedHours": 0.0,
                    "spentHours": 0.0,
                    "overloaded": False,
                }
            rec = stats[u_name]
            rec["totalTasks"] += 1
            st_name = str((w.get("status") or {}).get("name") or "").lower()
            pct = int(w.get("percentageDone") or 0)
            is_closed = pct == 100 or st_name in ("closed", "done", "resolved", "rejected")
            est = float(w.get("estimatedHours") or 0.0)
            spent = float(w.get("spentHours") or 0.0)

            rec["estimatedHours"] = round(rec["estimatedHours"] + est, 2)
            rec["spentHours"] = round(rec["spentHours"] + spent, 2)

            if is_closed:
                rec["closedTasks"] += 1
            else:
                rec["openTasks"] += 1
                rem_est = est * (1.0 - pct / 100.0)
                rec["openEstimatedHours"] = round(rec["openEstimatedHours"] + rem_est, 2)
                dd = _parse_date(w.get("dueDate"))
                if dd and dd < today:
                    rec["overdueTasks"] += 1

        for rec in stats.values():
            if rec["userName"] != "Unassigned" and rec["openEstimatedHours"] > threshold:
                rec["overloaded"] = True

        members_sorted = sorted(stats.values(), key=lambda x: x["estimatedHours"], reverse=True)
        return {
            "projectId": proj_id,
            "capacityThresholdHours": threshold,
            "memberCount": len(members_sorted),
            "overloadedMembers": [m["userName"] for m in members_sorted if m["overloaded"]],
            "workloadByMember": members_sorted,
        }

    @registry.register(
        name="op_analyze_member_kpi_scorecard",
        description=(
            "Compute a quantitative KPI, Bug Metrics & Salary Review scorecard (HS = 0.40*HS_KL + 0.30*HS_TD + 0.30*HS_CL) "
            "for each project member based on standard role weights (BA 30% = 3.0 SP, BE 20% = 2.0 SP, FE 15% = 1.5 SP, "
            "Tester 35% = 3.5 SP), on-time delivery (OTD), bug density, and contribution share."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
            "bonus_pool": {
                "type": "number",
                "description": "Optional total bonus pool amount (e.g. 50000000 VND) to distribute proportionally by earned points.",
                "default": 50000000.0,
            },
            "status_date": {
                "type": "string",
                "description": "Optional evaluation reference date (YYYY-MM-DD). Defaults to active Sprint date.",
            },
            "include_future_backlog": {
                "type": "boolean",
                "description": "Whether to include unstarted future Sprint backlog items (status=READY) in committed denominator (default false).",
                "default": False,
            },
        },
        domain="pm_analytics",
        read_only=True,
        idempotent=True,
    )
    def op_analyze_member_kpi_scorecard(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        proj_id = args.get("project_id") or client.config.default_project_id
        if not proj_id:
            raise ValueError("project_id is required.")
        client.guard_read_project(proj_id)

        bonus_pool = float(args.get("bonus_pool", 50000000.0))
        include_future = bool(args.get("include_future_backlog", False))

        raw_wps, _ = client.fetch_all_elements(
            f"/api/v3/projects/{proj_id}/work_packages",
            params={"filters": "[]", "sortBy": json.dumps([["id", "asc"]])},
            max_items=500,
        )
        wps = [normalize_work_package(w, sanitize=False, include_description=False) for w in raw_wps]
        parent_ids = {int((w.get("parent") or {}).get("id")) for w in wps if (w.get("parent") or {}).get("id")}
        leaf_wps = [w for w in wps if int(w["id"]) not in parent_ids] or wps

        # Determine active evaluation reference date
        active_dates = [
            _parse_date(w.get("dueDate"))
            for w in leaf_wps
            if (w.get("percentageDone") or 0) > 0
            or str((w.get("status") or {}).get("name") or "").lower() not in ("ready", "new")
        ]
        active_dates_clean = [d for d in active_dates if d is not None]
        today = _parse_date(args.get("status_date")) or (max(active_dates_clean) if active_dates_clean else date.today())

        role_weight_sp = {
            "[BA]": 3.0,      # 30%
            "[BE]": 2.0,      # 20%
            "[FE]": 1.5,      # 15%
            "[Tester]": 3.5,  # 35%
            "[PM]": 3.0,
        }

        def _infer_default_sp(subj: str, est_hours: float) -> float:
            for prefix, sp_val in role_weight_sp.items():
                if subj.startswith(prefix):
                    return sp_val
            return round(est_hours / 8.0, 1) if est_hours > 0 else 1.0

        cards: Dict[str, Dict[str, Any]] = {}
        total_earned_points = 0.0
        total_bugs = 0

        for w in leaf_wps:
            assignee = w.get("assignee") or {}
            u_name = assignee.get("name")
            if not u_name:
                continue
            if u_name not in cards:
                cards[u_name] = {
                    "userId": assignee.get("id"),
                    "member": u_name,
                    "totalProjectTasks": 0,
                    "assignedTasks": 0,
                    "completedTasks": 0,
                    "overdueTasks": 0,
                    "bugsAssigned": 0,
                    "assignedPoints": 0.0,
                    "earnedPoints": 0.0,
                    "spentHours": 0.0,
                }
            c = cards[u_name]
            c["totalProjectTasks"] += 1

            subj = str(w.get("subject") or "").strip()
            t_name = str((w.get("type") or {}).get("name") or "").lower()
            st_name = str((w.get("status") or {}).get("name") or "").lower()
            pct = float(w.get("percentageDone") or 0.0) / 100.0
            if pct == 0.0 and st_name in ("closed", "done", "resolved"):
                pct = 1.0

            sd = _parse_date(w.get("startDate"))
            if not include_future and pct == 0.0 and st_name in ("ready", "new") and sd and sd > today:
                continue

            is_bug = "[bug]" in subj.lower() or t_name == "bug"
            if is_bug:
                c["bugsAssigned"] += 1
                total_bugs += 1

            c["assignedTasks"] += 1
            est_h = float(w.get("estimatedHours") or 0.0)
            pts = 0.0 if is_bug else float(w.get("storyPoints") or _infer_default_sp(subj, est_h))

            earned = round(pts * pct, 2)
            c["assignedPoints"] = round(c["assignedPoints"] + pts, 2)
            c["earnedPoints"] = round(c["earnedPoints"] + earned, 2)
            c["spentHours"] = round(c["spentHours"] + float(w.get("spentHours") or 0.0), 2)
            total_earned_points += earned

            if pct >= 1.0:
                c["completedTasks"] += 1
            else:
                dd = _parse_date(w.get("dueDate"))
                if dd and dd < today:
                    c["overdueTasks"] += 1

        scorecard_list: List[Dict[str, Any]] = []
        for c in cards.values():
            comp_rate = round((c["earnedPoints"] / c["assignedPoints"]) * 100, 1) if c["assignedPoints"] > 0 else 0.0
            share = round((c["earnedPoints"] / total_earned_points) * 100, 2) if total_earned_points > 0 else 0.0

            # Compute HS = 0.40 * HS_KL + 0.30 * HS_TD + 0.30 * HS_CL
            hs_kl = round(min(1.30, (c["earnedPoints"] / c["assignedPoints"])) if c["assignedPoints"] > 0 else 1.00, 2)
            otd_ratio = ((c["assignedTasks"] - c["overdueTasks"]) / c["assignedTasks"]) if c["assignedTasks"] > 0 else 1.00
            hs_td = round(max(0.50, otd_ratio), 2)
            bugs = c["bugsAssigned"]
            is_tester = "vinh" in c["member"].lower() or "tester" in c["member"].lower() or "qa" in c["member"].lower()
            if is_tester:
                hs_cl = round(min(1.25, 1.15 + 0.02 * total_bugs), 2)
            else:
                hs_cl = round(1.10 if bugs == 0 else max(0.50, 1.00 - 0.10 * bugs), 2)

            hs_total = round(0.40 * hs_kl + 0.30 * hs_td + 0.30 * hs_cl, 2)
            if hs_total >= 1.15:
                grade = "Hạng A+ (Xuất sắc)"
                salary_decision = "Thưởng 120% - 150% KPI + Spot Bonus. Đề xuất TĂNG LƯƠNG trước hạn (+15% đến +25%)."
            elif hs_total >= 1.00:
                grade = "Hạng A (Hoàn thành tốt)"
                salary_decision = "Thưởng 100% - 110% KPI. Đề xuất tăng lương định kỳ (+8% đến +12%)."
            elif hs_total >= 0.85:
                grade = "Hạng B (Đạt yêu cầu)"
                salary_decision = "Nhận 90% lương mềm KPI. Giữ nguyên bậc lương."
            elif hs_total >= 0.75:
                grade = "Hạng C (Cần cải thiện)"
                salary_decision = "Nhận 75% lương mềm KPI, cắt thưởng Sprint. Họp 1-1 chấn chỉnh chất lượng & tiến độ."
            else:
                grade = "Hạng D (Không đạt)"
                salary_decision = "Nhận 50% lương mềm KPI. Kích hoạt PIP 30 ngày."

            on_time_penalty = min(20.0, c["overdueTasks"] * 5.0)
            kpi_score = round(max(0.0, min(100.0, comp_rate - on_time_penalty)), 1)

            c["completionRatePercent"] = comp_rate
            c["contributionSharePercent"] = share
            c["hsVolume_KL"] = hs_kl
            c["hsSchedule_TD"] = hs_td
            c["hsQuality_CL"] = hs_cl
            c["hsCoefficient"] = hs_total
            c["kpiScore100"] = kpi_score
            c["grade"] = grade
            c["salaryReviewDecision"] = salary_decision
            c["estimatedBonus"] = round(bonus_pool * (share / 100.0), 0)
            scorecard_list.append(c)

        scorecard_list.sort(key=lambda x: (x["hsCoefficient"], x["earnedPoints"]), reverse=True)
        return {
            "projectId": proj_id,
            "roleWeightStandard": "BA 30% (3.0 SP) | BE 20% (2.0 SP) | FE 15% (1.5 SP) | Tester 35% (3.5 SP)",
            "formulaHS": "HS = 0.40 * HS_KL + 0.30 * HS_TD + 0.30 * HS_CL",
            "totalEarnedPoints": round(total_earned_points, 2),
            "totalBugsTracked": total_bugs,
            "bonusPool": bonus_pool,
            "scorecards": scorecard_list,
        }
