"""
Domain 4: Relations, Dependencies & Gantt Critical Path Method (CPM) Engine
(List/Create/Update/Delete Relations, Dependency Chain Builder, Gantt Schedule & Critical Path Analyzer).
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Set, Tuple

from ..client import OpenProjectClient
from ..hal_normalizer import build_openproject_filters, normalize_relation, normalize_work_package
from ..registry import ToolRegistry

VALID_RELATION_TYPES = (
    "relates",
    "duplicates",
    "duplicated",
    "blocks",
    "blocked",
    "precedes",
    "follows",
    "includes",
    "partof",
    "requires",
    "required",
)


def _parse_iso_date(d_str: Optional[str]) -> Optional[date]:
    if not d_str or not isinstance(d_str, str):
        return None
    try:
        return datetime.strptime(d_str[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def register_tools(registry: ToolRegistry) -> None:

    @registry.register(
        name="op_list_relations",
        description=(
            "List work package relations/dependencies (/api/v3/relations). "
            "Can filter by involved work_package_id, from_id, to_id, or relation type."
        ),
        properties={
            "work_package_id": {
                "type": "integer",
                "description": "Filter relations involving this work package ID (either as source or target).",
            },
            "from_id": {"type": "integer", "description": "Filter by source ('from') work package ID."},
            "to_id": {"type": "integer", "description": "Filter by target ('to') work package ID."},
            "relation_type": {
                "type": "string",
                "description": f"Optional relation type filter: {', '.join(VALID_RELATION_TYPES)}.",
            },
        },
        domain="relations_gantt",
        read_only=True,
        idempotent=True,
    )
    def op_list_relations(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        filters: List[Dict[str, Any]] = []
        if args.get("work_package_id"):
            filters.append({"involved": {"operator": "=", "values": [str(args["work_package_id"])]}})
        if args.get("from_id"):
            filters.append({"from": {"operator": "=", "values": [str(args["from_id"])]}})
        if args.get("to_id"):
            filters.append({"to": {"operator": "=", "values": [str(args["to_id"])]}})
        if args.get("relation_type"):
            filters.append({"type": {"operator": "=", "values": [str(args["relation_type"])]}})

        params: Dict[str, Any] = {}
        if filters:
            params["filters"] = json.dumps(filters)

        elements, total = client.fetch_all_elements("/api/v3/relations", params=params, max_items=300)
        return {
            "total": total,
            "relations": [normalize_relation(r) for r in elements],
        }

    @registry.register(
        name="op_create_relation",
        description=(
            "Create a dependency/relation between two work packages "
            "(POST /api/v3/work_packages/{from_id}/relations). "
            "Supported types: precedes, follows, blocks, blocked, relates, duplicates, duplicated, includes, partof, requires, required."
        ),
        properties={
            "from_id": {"type": "integer", "description": "Source work package ID."},
            "to_id": {"type": "integer", "description": "Target work package ID."},
            "relation_type": {
                "type": "string",
                "description": "Relation type (e.g. 'precedes' means from_id precedes to_id; 'follows' means from_id follows to_id).",
                "default": "precedes",
            },
            "lag": {
                "type": "integer",
                "description": "Lag in working days between predecessor finish and successor start (for precedes/follows, default 0).",
                "default": 0,
            },
            "description": {"type": "string", "description": "Optional description of the dependency."},
        },
        required=["from_id", "to_id"],
        domain="relations_gantt",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_relation(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        from_id = int(args["from_id"])
        to_id = int(args["to_id"])
        rel_type = str(args.get("relation_type", "precedes")).strip().lower()

        payload: Dict[str, Any] = {
            "type": rel_type,
            "_links": {
                "from": {"href": f"/api/v3/work_packages/{from_id}"},
                "to": {"href": f"/api/v3/work_packages/{to_id}"},
            },
        }
        if args.get("lag") is not None and rel_type in ("precedes", "follows"):
            payload["lag"] = int(args["lag"])
        if args.get("description"):
            payload["description"] = str(args["description"])

        created = client.post(f"/api/v3/work_packages/{from_id}/relations", json_body=payload)
        return normalize_relation(created)

    @registry.register(
        name="op_update_relation",
        description="Update an existing relation's type, lag days, or description (PATCH /api/v3/relations/{id}).",
        properties={
            "relation_id": {"type": "integer", "description": "Relation ID."},
            "relation_type": {"type": "string", "description": "Updated relation type."},
            "lag": {"type": "integer", "description": "Updated lag in working days."},
            "description": {"type": "string", "description": "Updated description."},
        },
        required=["relation_id"],
        domain="relations_gantt",
        read_only=False,
        destructive=False,
        idempotent=True,
    )
    def op_update_relation(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        rel_id = args["relation_id"]
        payload: Dict[str, Any] = {}
        if args.get("relation_type"):
            payload["type"] = str(args["relation_type"])
        if args.get("lag") is not None:
            payload["lag"] = int(args["lag"])
        if args.get("description") is not None:
            payload["description"] = str(args["description"])
        updated = client.patch(f"/api/v3/relations/{rel_id}", json_body=payload)
        return normalize_relation(updated)

    @registry.register(
        name="op_delete_relation",
        description="Delete a work package relation by ID (DELETE /api/v3/relations/{id}).",
        properties={
            "relation_id": {"type": "integer", "description": "Relation ID to delete."},
        },
        required=["relation_id"],
        domain="relations_gantt",
        read_only=False,
        destructive=True,
        idempotent=True,
    )
    def op_delete_relation(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation(is_delete=True)
        return client.delete(f"/api/v3/relations/{args['relation_id']}")

    @registry.register(
        name="op_create_dependency_chain",
        description=(
            "Link an ordered list of work package IDs into a sequential Finish-to-Start ('precedes') "
            "dependency chain: wp[0] -> wp[1] -> wp[2] ... with optional lag days."
        ),
        properties={
            "work_package_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Ordered list of at least 2 work package IDs to link sequentially.",
            },
            "lag": {
                "type": "integer",
                "description": "Lag in working days between consecutive tasks (default 0).",
                "default": 0,
            },
        },
        required=["work_package_ids"],
        domain="relations_gantt",
        read_only=False,
        destructive=False,
        idempotent=False,
    )
    def op_create_dependency_chain(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
        client.guard_write_operation()
        wp_ids = [int(x) for x in (args.get("work_package_ids") or [])]
        if len(wp_ids) < 2:
            raise ValueError("work_package_ids must contain at least 2 IDs.")
        lag = int(args.get("lag", 0))

        created_links: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for i in range(len(wp_ids) - 1):
            pred, succ = wp_ids[i], wp_ids[i + 1]
            try:
                res = client.post(
                    f"/api/v3/work_packages/{pred}/relations",
                    json_body={
                        "type": "precedes",
                        "lag": lag,
                        "_links": {
                            "from": {"href": f"/api/v3/work_packages/{pred}"},
                            "to": {"href": f"/api/v3/work_packages/{succ}"},
                        },
                    },
                )
                created_links.append(normalize_relation(res))
            except Exception as exc:
                errors.append({"from": pred, "to": succ, "error": str(exc)})

        return {
            "chain": wp_ids,
            "createdCount": len(created_links),
            "relations": created_links,
            "errors": errors,
        }

    @registry.register(
        name="op_analyze_gantt_critical_path",
        description=(
            "Audit a project's Gantt schedule and compute the Critical Path Method (CPM) network: "
            "calculates Early Start (ES), Early Finish (EF), Late Start (LS), Late Finish (LF), "
            "Total Float, Free Float, identifies Critical Path tasks (Total Float = 0), "
            "and detects schedule conflicts or unscheduled tasks."
        ),
        properties={
            "project_id": {
                "type": ["integer", "string"],
                "description": "Project ID or identifier (defaults to OPENPROJECT_PROJECT_ID).",
            },
        },
        domain="relations_gantt",
        read_only=True,
        idempotent=True,
    )
    def op_analyze_gantt_critical_path(client: OpenProjectClient, args: Dict[str, Any]) -> Dict[str, Any]:
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
        wp_by_id: Dict[int, Dict[str, Any]] = {int(w["id"]): w for w in wps if w.get("id")}

        # Fetch all relations involving project work packages
        raw_rels, _ = client.fetch_all_elements("/api/v3/relations", max_items=500)
        rels = [normalize_relation(r) for r in raw_rels]

        # Build directed graph of Precedes (u -> v with lag)
        adj: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        preds: Dict[int, List[Tuple[int, int]]] = defaultdict(list)
        in_degree: Dict[int, int] = {wid: 0 for wid in wp_by_id}
        seen_edges: Set[Tuple[int, int]] = set()
        date_conflicts: List[Dict[str, Any]] = []

        for r in rels:
            r_type = r.get("type")
            u_id = (r.get("from") or {}).get("id")
            v_id = (r.get("to") or {}).get("id")
            lag = int(r.get("lag") or 0)
            if not u_id or not v_id:
                continue
            u_id, v_id = int(u_id), int(v_id)
            if u_id not in wp_by_id or v_id not in wp_by_id:
                continue

            if r_type == "precedes":
                pred_id, succ_id = u_id, v_id
            elif r_type == "follows":
                pred_id, succ_id = v_id, u_id
            else:
                continue

            if (pred_id, succ_id) not in seen_edges:
                seen_edges.add((pred_id, succ_id))
                adj[pred_id].append((succ_id, lag))
                preds[succ_id].append((pred_id, lag))
                in_degree[succ_id] = in_degree.get(succ_id, 0) + 1

                # Check calendar date conflict
                p_due = _parse_iso_date(wp_by_id[pred_id].get("dueDate") or wp_by_id[pred_id].get("derivedDueDate"))
                s_start = _parse_iso_date(wp_by_id[succ_id].get("startDate") or wp_by_id[succ_id].get("derivedStartDate"))
                if p_due and s_start:
                    gap_days = (s_start - p_due).days - 1
                    if gap_days < lag:
                        date_conflicts.append({
                            "predecessorId": pred_id,
                            "predecessorSubject": wp_by_id[pred_id].get("subject"),
                            "predecessorDueDate": str(p_due),
                            "successorId": succ_id,
                            "successorSubject": wp_by_id[succ_id].get("subject"),
                            "successorStartDate": str(s_start),
                            "requiredLagDays": lag,
                            "actualGapDays": gap_days,
                        })

        # Compute duration in calendar days for each work package
        duration: Dict[int, int] = {}
        unscheduled: List[Dict[str, Any]] = []
        for wid, w in wp_by_id.items():
            sd = _parse_iso_date(w.get("startDate") or w.get("derivedStartDate"))
            dd = _parse_iso_date(w.get("dueDate") or w.get("derivedDueDate"))
            if sd and dd and dd >= sd:
                duration[wid] = max(1, (dd - sd).days + 1)
            elif sd or dd:
                duration[wid] = 1
            else:
                duration[wid] = max(1, int(round((w.get("estimatedHours") or 8.0) / 8.0)))
                unscheduled.append({"id": wid, "subject": w.get("subject"), "type": (w.get("type") or {}).get("name")})

        # Topological sort (Kahn's algorithm) for Forward/Backward Pass
        q = deque([wid for wid, deg in in_degree.items() if deg == 0])
        topo_order: List[int] = []
        while q:
            u = q.popleft()
            topo_order.append(u)
            for v, _ in adj[u]:
                in_degree[v] -= 1
                if in_degree[v] == 0:
                    q.append(v)

        has_cycle = len(topo_order) < len(wp_by_id)

        # Forward Pass (ES, EF)
        es: Dict[int, int] = {wid: 0 for wid in wp_by_id}
        ef: Dict[int, int] = {wid: duration[wid] for wid in wp_by_id}
        for u in topo_order:
            ef[u] = es[u] + duration[u]
            for v, lag in adj[u]:
                if ef[u] + lag > es[v]:
                    es[v] = ef[u] + lag
                    ef[v] = es[v] + duration[v]

        project_duration = max(ef.values()) if ef else 0

        # Backward Pass (LS, LF)
        lf: Dict[int, int] = {wid: project_duration for wid in wp_by_id}
        ls: Dict[int, int] = {wid: project_duration - duration[wid] for wid in wp_by_id}
        for u in reversed(topo_order):
            if adj[u]:
                lf[u] = min(ls[v] - lag for v, lag in adj[u])
            ls[u] = lf[u] - duration[u]

        cpm_nodes: List[Dict[str, Any]] = []
        critical_path_ids: List[int] = []
        for wid in topo_order:
            tf = ls[wid] - es[wid]
            ff = min((es[v] - lag - ef[wid] for v, lag in adj[wid]), default=tf)
            is_critical = (tf == 0) and (bool(adj[wid]) or bool(preds[wid]))
            if is_critical:
                critical_path_ids.append(wid)
            if adj[wid] or preds[wid]:
                cpm_nodes.append({
                    "id": wid,
                    "subject": wp_by_id[wid].get("subject"),
                    "durationDays": duration[wid],
                    "ES": es[wid],
                    "EF": ef[wid],
                    "LS": ls[wid],
                    "LF": lf[wid],
                    "totalFloat": tf,
                    "freeFloat": ff,
                    "isCritical": is_critical,
                })

        return {
            "projectId": proj_id,
            "totalWorkPackages": len(wp_by_id),
            "totalDependencyLinks": len(seen_edges),
            "hasCircularDependency": has_cycle,
            "estimatedNetworkDurationDays": project_duration,
            "criticalPathIds": critical_path_ids,
            "criticalPathCount": len(critical_path_ids),
            "cpmNetworkNodes": cpm_nodes,
            "scheduleDateConflicts": date_conflicts,
            "unscheduledWorkPackages": unscheduled[:30],
        }
