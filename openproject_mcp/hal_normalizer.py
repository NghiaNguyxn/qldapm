"""
HAL+JSON Context-Frugal Normalizer, ISO-8601 Duration Converter,
Filter Builder, and Indirect Prompt Injection Sanitizer for OpenProject API v3.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 1. Indirect Prompt Injection Sanitizer
# ---------------------------------------------------------------------------

def wrap_untrusted_text(text: Optional[str], sanitize: bool = True) -> Optional[str]:
    """
    Wrap user-generated text from OpenProject (descriptions, comments, wiki pages)
    in <untrusted-openproject-content> tags to prevent Indirect Prompt Injection.
    """
    if text is None:
        return None
    cleaned = str(text).strip()
    if not cleaned:
        return ""
    if not sanitize:
        return cleaned
    # Escape closing tag if maliciously embedded inside user content
    safe_inner = cleaned.replace(
        "</untrusted-openproject-content>",
        "&lt;/untrusted-openproject-content&gt;",
    )
    return f"<untrusted-openproject-content>{safe_inner}</untrusted-openproject-content>"


# ---------------------------------------------------------------------------
# 2. ISO-8601 Duration <-> Float Hours Conversion
# ---------------------------------------------------------------------------

_ISO_DURATION_RE = re.compile(
    r"^P(?:(?P<weeks>\d+(?:\.\d+)?)W)?"
    r"(?:(?P<days>\d+(?:\.\d+)?)D)?"
    r"(?:T(?:(?P<hours>\d+(?:\.\d+)?)H)?"
    r"(?:(?P<minutes>\d+(?:\.\d+)?)M)?"
    r"(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$",
    re.IGNORECASE,
)


def iso_duration_to_hours(iso_str: Optional[str], hours_per_day: float = 24.0) -> Optional[float]:
    """
    Convert OpenProject ISO-8601 duration (e.g. 'PT2H30M', 'P1DT4H', 'PT0S')
    into decimal hours.Note: OpenProject stores estimatedTime/spentTime in standard 24h days
    in ISO strings (e.g. P1D = 24h or PT8H = 8h).
    """
    if not iso_str or not isinstance(iso_str, str):
        return None
    m = _ISO_DURATION_RE.match(iso_str.strip())
    if not m:
        return None
    weeks = float(m.group("weeks") or 0.0)
    days = float(m.group("days") or 0.0)
    hours = float(m.group("hours") or 0.0)
    minutes = float(m.group("minutes") or 0.0)
    seconds = float(m.group("seconds") or 0.0)
    total = (
        weeks * 7.0 * hours_per_day
        + days * hours_per_day
        + hours
        + minutes / 60.0
        + seconds / 3600.0
    )
    return round(total, 2)


def hours_to_iso_duration(value: Optional[float | int | str]) -> Optional[str]:
    """
    Convert float/int hours (e.g. 2.5) or an existing ISO-8601 string ('PT2H30M')
    into a valid OpenProject ISO-8601 duration string.
    """
    if value is None:
        return None
    if isinstance(value, str):
        val_str = value.strip()
        if not val_str:
            return None
        if val_str.upper().startswith("P"):
            return val_str.upper()
        value = float(val_str)

    hours_float = max(0.0, float(value))
    whole_hours = int(hours_float)
    minutes = int(round((hours_float - whole_hours) * 60))
    if minutes == 60:
        whole_hours += 1
        minutes = 0
    if whole_hours > 0 and minutes > 0:
        return f"PT{whole_hours}H{minutes}M"
    if whole_hours > 0:
        return f"PT{whole_hours}H"
    if minutes > 0:
        return f"PT{minutes}M"
    return "PT0S"


# ---------------------------------------------------------------------------
# 3. HAL+JSON Link & Embedded Helpers
# ---------------------------------------------------------------------------

def extract_id_from_href(href: Optional[str]) -> Optional[int | str]:
    """Extract numeric or string resource ID from an OpenProject HAL href (e.g. '/api/v3/statuses/7' -> 7)."""
    if not href or not isinstance(href, str):
        return None
    tail = href.rstrip("/").split("/")[-1]
    if not tail:
        return None
    return int(tail) if tail.isdigit() else tail


def extract_link_summary(links: Dict[str, Any], rel: str) -> Optional[Dict[str, Any]]:
    """Extract compact {id, title, href} from a HAL _links[rel] entry."""
    if not isinstance(links, dict):
        return None
    link_obj = links.get(rel)
    if not link_obj or not isinstance(link_obj, dict):
        return None
    href = link_obj.get("href")
    if not href:
        return None
    return {
        "id": extract_id_from_href(href),
        "title": link_obj.get("title"),
        "href": href,
    }


def extract_link_title(links: Dict[str, Any], rel: str) -> Optional[str]:
    """Extract title or ID string from a HAL _links[rel] entry."""
    summary = extract_link_summary(links, rel)
    if not summary:
        return None
    return summary.get("title") or (str(summary["id"]) if summary.get("id") is not None else None)


def extract_link_id(links: Dict[str, Any], rel: str) -> Optional[int | str]:
    """Extract ID from a HAL _links[rel] entry."""
    summary = extract_link_summary(links, rel)
    return summary.get("id") if summary else None


# ---------------------------------------------------------------------------
# 4. Context-Frugal Entity Normalizers (-85% to -95% token reduction)
# ---------------------------------------------------------------------------

def normalize_work_package(
    wp: Dict[str, Any],
    sanitize: bool = True,
    include_description: bool = True,
    include_custom_fields: bool = True,
) -> Dict[str, Any]:
    """Convert a verbose HAL+JSON WorkPackage into a clean, context-frugal dictionary."""
    if not isinstance(wp, dict):
        return {}
    links = wp.get("_links", {}) or {}
    desc_obj = wp.get("description") or {}
    raw_desc = desc_obj.get("raw") if isinstance(desc_obj, dict) else None

    est_iso = wp.get("estimatedTime")
    rem_iso = wp.get("remainingTime")
    spent_iso = wp.get("spentTime")
    derived_est_iso = wp.get("derivedEstimatedTime")

    result: Dict[str, Any] = {
        "id": wp.get("id"),
        "subject": wp.get("subject"),
        "lockVersion": wp.get("lockVersion"),
        "project": {
            "id": extract_link_id(links, "project"),
            "name": extract_link_title(links, "project"),
        },
        "type": {
            "id": extract_link_id(links, "type"),
            "name": extract_link_title(links, "type"),
        },
        "status": {
            "id": extract_link_id(links, "status"),
            "name": extract_link_title(links, "status"),
        },
        "priority": {
            "id": extract_link_id(links, "priority"),
            "name": extract_link_title(links, "priority"),
        },
        "assignee": {
            "id": extract_link_id(links, "assignee"),
            "name": extract_link_title(links, "assignee"),
        } if extract_link_id(links, "assignee") else None,
        "responsible": {
            "id": extract_link_id(links, "responsible"),
            "name": extract_link_title(links, "responsible"),
        } if extract_link_id(links, "responsible") else None,
        "author": {
            "id": extract_link_id(links, "author"),
            "name": extract_link_title(links, "author"),
        } if extract_link_id(links, "author") else None,
        "parent": {
            "id": extract_link_id(links, "parent"),
            "subject": extract_link_title(links, "parent"),
        } if extract_link_id(links, "parent") else None,
        "version": {
            "id": extract_link_id(links, "version"),
            "name": extract_link_title(links, "version"),
        } if extract_link_id(links, "version") else None,
        "category": {
            "id": extract_link_id(links, "category"),
            "name": extract_link_title(links, "category"),
        } if extract_link_id(links, "category") else None,
        "startDate": wp.get("startDate") or wp.get("date"),
        "dueDate": wp.get("dueDate") or wp.get("date"),
        "derivedStartDate": wp.get("derivedStartDate"),
        "derivedDueDate": wp.get("derivedDueDate"),
        "scheduleManually": wp.get("scheduleManually"),
        "percentageDone": wp.get("percentageDone"),
        "derivedPercentageDone": wp.get("derivedPercentageDone"),
        "estimatedHours": iso_duration_to_hours(est_iso),
        "derivedEstimatedHours": iso_duration_to_hours(derived_est_iso),
        "remainingHours": iso_duration_to_hours(rem_iso),
        "spentHours": iso_duration_to_hours(spent_iso),
        "storyPoints": wp.get("storyPoints"),
        "createdAt": wp.get("createdAt"),
        "updatedAt": wp.get("updatedAt"),
    }

    # Children count / links
    children_links = links.get("children")
    if isinstance(children_links, list):
        result["children"] = [
            {"id": extract_id_from_href(c.get("href")), "subject": c.get("title")}
            for c in children_links
            if isinstance(c, dict) and c.get("href")
        ]

    if include_description and raw_desc:
        result["description"] = wrap_untrusted_text(raw_desc, sanitize=sanitize)

    if include_custom_fields:
        custom_fields: Dict[str, Any] = {}
        for k, v in wp.items():
            if k.startswith("customField") and v is not None:
                if isinstance(v, dict) and "raw" in v:
                    custom_fields[k] = v.get("raw")
                else:
                    custom_fields[k] = v
        for k, v in links.items():
            if k.startswith("customField") and v is not None:
                if isinstance(v, dict) and v.get("href"):
                    custom_fields[k] = {
                        "id": extract_id_from_href(v.get("href")),
                        "title": v.get("title"),
                    }
                elif isinstance(v, list):
                    custom_fields[k] = [
                        {"id": extract_id_from_href(item.get("href")), "title": item.get("title")}
                        for item in v
                        if isinstance(item, dict) and item.get("href")
                    ]
        if custom_fields:
            result["customFields"] = custom_fields

    # Remove None values for compactness
    return {k: v for k, v in result.items() if v is not None}


def normalize_project(proj: Dict[str, Any], sanitize: bool = True) -> Dict[str, Any]:
    """Normalize a HAL+JSON Project object."""
    links = proj.get("_links", {}) or {}
    desc_obj = proj.get("description") or {}
    raw_desc = desc_obj.get("raw") if isinstance(desc_obj, dict) else None
    status_exp = proj.get("statusExplanation") or {}
    raw_status_exp = status_exp.get("raw") if isinstance(status_exp, dict) else None

    res = {
        "id": proj.get("id"),
        "identifier": proj.get("identifier"),
        "name": proj.get("name"),
        "active": proj.get("active"),
        "public": proj.get("public"),
        "status": extract_link_title(links, "status") or proj.get("status"),
        "statusExplanation": wrap_untrusted_text(raw_status_exp, sanitize=sanitize) if raw_status_exp else None,
        "parent": {
            "id": extract_link_id(links, "parent"),
            "name": extract_link_title(links, "parent"),
        } if extract_link_id(links, "parent") else None,
        "description": wrap_untrusted_text(raw_desc, sanitize=sanitize) if raw_desc else None,
        "createdAt": proj.get("createdAt"),
        "updatedAt": proj.get("updatedAt"),
    }
    return {k: v for k, v in res.items() if v is not None}


def normalize_relation(rel: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a HAL+JSON Relation between two work packages."""
    links = rel.get("_links", {}) or {}
    res = {
        "id": rel.get("id"),
        "name": rel.get("name"),
        "type": rel.get("type"),
        "reverseType": rel.get("reverseType"),
        "lag": rel.get("lag", 0),
        "description": rel.get("description"),
        "from": {
            "id": extract_link_id(links, "from"),
            "subject": extract_link_title(links, "from"),
        },
        "to": {
            "id": extract_link_id(links, "to"),
            "subject": extract_link_title(links, "to"),
        },
    }
    return {k: v for k, v in res.items() if v is not None}


def normalize_time_entry(entry: Dict[str, Any], sanitize: bool = True) -> Dict[str, Any]:
    """Normalize a HAL+JSON TimeEntry resource."""
    links = entry.get("_links", {}) or {}
    comment_obj = entry.get("comment") or {}
    raw_comment = comment_obj.get("raw") if isinstance(comment_obj, dict) else None
    hours_iso = entry.get("hours")

    res = {
        "id": entry.get("id"),
        "spentOn": entry.get("spentOn"),
        "hours": iso_duration_to_hours(hours_iso),
        "hoursIso": hours_iso,
        "ongoing": entry.get("ongoing"),
        "comment": wrap_untrusted_text(raw_comment, sanitize=sanitize) if raw_comment else None,
        "project": {
            "id": extract_link_id(links, "project"),
            "name": extract_link_title(links, "project"),
        },
        "workPackage": {
            "id": extract_link_id(links, "workPackage") or extract_link_id(links, "entity"),
            "subject": extract_link_title(links, "workPackage") or extract_link_title(links, "entity"),
        },
        "user": {
            "id": extract_link_id(links, "user"),
            "name": extract_link_title(links, "user"),
        },
        "activity": {
            "id": extract_link_id(links, "activity"),
            "name": extract_link_title(links, "activity"),
        },
        "createdAt": entry.get("createdAt"),
        "updatedAt": entry.get("updatedAt"),
    }
    return {k: v for k, v in res.items() if v is not None}


def normalize_activity(act: Dict[str, Any], sanitize: bool = True) -> Dict[str, Any]:
    """Normalize a HAL+JSON Activity / Comment journal entry."""
    links = act.get("_links", {}) or {}
    comment_obj = act.get("comment") or {}
    raw_comment = comment_obj.get("raw") if isinstance(comment_obj, dict) else None
    details = []
    for d in act.get("details", []) or []:
        if isinstance(d, dict) and d.get("raw"):
            details.append(d.get("raw"))

    res = {
        "id": act.get("id"),
        "version": act.get("version"),
        "internal": act.get("internal", False),
        "user": {
            "id": extract_link_id(links, "user"),
            "name": extract_link_title(links, "user"),
        },
        "comment": wrap_untrusted_text(raw_comment, sanitize=sanitize) if raw_comment else None,
        "changes": details if details else None,
        "createdAt": act.get("createdAt"),
        "updatedAt": act.get("updatedAt"),
    }
    return {k: v for k, v in res.items() if v is not None}


def normalize_version(ver: Dict[str, Any], sanitize: bool = True) -> Dict[str, Any]:
    """Normalize a HAL+JSON Version (Sprint / Release / Milestone)."""
    links = ver.get("_links", {}) or {}
    desc_obj = ver.get("description") or {}
    raw_desc = desc_obj.get("raw") if isinstance(desc_obj, dict) else None

    res = {
        "id": ver.get("id"),
        "name": ver.get("name"),
        "status": ver.get("status"),
        "sharing": ver.get("sharing"),
        "startDate": ver.get("startDate"),
        "endDate": ver.get("endDate"),
        "description": wrap_untrusted_text(raw_desc, sanitize=sanitize) if raw_desc else None,
        "definingProject": {
            "id": extract_link_id(links, "definingProject"),
            "name": extract_link_title(links, "definingProject"),
        },
        "createdAt": ver.get("createdAt"),
        "updatedAt": ver.get("updatedAt"),
    }
    return {k: v for k, v in res.items() if v is not None}


def normalize_membership(mem: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a HAL+JSON Project Membership."""
    links = mem.get("_links", {}) or {}
    roles_links = links.get("roles", []) or []
    roles = [
        {"id": extract_id_from_href(r.get("href")), "name": r.get("title")}
        for r in roles_links
        if isinstance(r, dict)
    ]
    res = {
        "id": mem.get("id"),
        "project": {
            "id": extract_link_id(links, "project"),
            "name": extract_link_title(links, "project"),
        },
        "principal": {
            "id": extract_link_id(links, "principal"),
            "name": extract_link_title(links, "principal"),
            "href": (links.get("principal") or {}).get("href"),
        },
        "roles": roles,
        "createdAt": mem.get("createdAt"),
        "updatedAt": mem.get("updatedAt"),
    }
    return {k: v for k, v in res.items() if v is not None}


def normalize_user(user: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a HAL+JSON User / Principal."""
    res = {
        "id": user.get("id"),
        "type": user.get("_type"),
        "name": user.get("name"),
        "login": user.get("login"),
        "firstName": user.get("firstName"),
        "lastName": user.get("lastName"),
        "email": user.get("email"),
        "admin": user.get("admin"),
        "status": user.get("status"),
        "language": user.get("language"),
        "createdAt": user.get("createdAt"),
        "updatedAt": user.get("updatedAt"),
    }
    return {k: v for k, v in res.items() if v is not None}


# ---------------------------------------------------------------------------
# 5. OpenProject API v3 Filter Builder
# ---------------------------------------------------------------------------

def build_openproject_filters(
    *,
    raw_filters: Optional[List[Dict[str, Any]] | str] = None,
    project_id: Optional[int | str] = None,
    status_id: Optional[int | str | List[int | str]] = None,
    status_open: Optional[bool] = None,
    type_id: Optional[int | str | List[int | str]] = None,
    priority_id: Optional[int | str | List[int | str]] = None,
    assignee_id: Optional[int | str | List[int | str]] = None,
    author_id: Optional[int | str] = None,
    responsible_id: Optional[int | str] = None,
    version_id: Optional[int | str] = None,
    category_id: Optional[int | str] = None,
    parent_id: Optional[int | str] = None,
    subject_contains: Optional[str] = None,
    search_text: Optional[str] = None,
    start_date_from: Optional[str] = None,
    start_date_to: Optional[str] = None,
    due_date_from: Optional[str] = None,
    due_date_to: Optional[str] = None,
    updated_since: Optional[str] = None,
) -> Optional[str]:
    """
    Build a JSON-serialized OpenProject API v3 filter array string:
    [{"field": {"operator": "=", "values": ["..."]}}, ...]
    """
    filters: List[Dict[str, Any]] = []

    if raw_filters:
        if isinstance(raw_filters, str):
            try:
                parsed = json.loads(raw_filters)
                if isinstance(parsed, list):
                    filters.extend(parsed)
            except Exception:
                pass
        elif isinstance(raw_filters, list):
            filters.extend(raw_filters)

    def _to_str_list(val: Any) -> List[str]:
        if isinstance(val, (list, tuple, set)):
            return [str(x) for x in val]
        return [str(val)]

    if project_id is not None:
        filters.append({"project": {"operator": "=", "values": _to_str_list(project_id)}})

    if status_open is True:
        filters.append({"status": {"operator": "o", "values": []}})
    elif status_open is False:
        filters.append({"status": {"operator": "c", "values": []}})
    elif status_id is not None:
        filters.append({"status": {"operator": "=", "values": _to_str_list(status_id)}})

    if type_id is not None:
        filters.append({"type": {"operator": "=", "values": _to_str_list(type_id)}})

    if priority_id is not None:
        filters.append({"priority": {"operator": "=", "values": _to_str_list(priority_id)}})

    if assignee_id is not None:
        if str(assignee_id).lower() in ("none", "null", "unassigned"):
            filters.append({"assignee": {"operator": "!*", "values": []}})
        else:
            filters.append({"assignee": {"operator": "=", "values": _to_str_list(assignee_id)}})

    if author_id is not None:
        filters.append({"author": {"operator": "=", "values": _to_str_list(author_id)}})

    if responsible_id is not None:
        filters.append({"responsible": {"operator": "=", "values": _to_str_list(responsible_id)}})

    if version_id is not None:
        filters.append({"version": {"operator": "=", "values": _to_str_list(version_id)}})

    if category_id is not None:
        filters.append({"category": {"operator": "=", "values": _to_str_list(category_id)}})

    if parent_id is not None:
        filters.append({"parent": {"operator": "=", "values": _to_str_list(parent_id)}})

    if subject_contains:
        filters.append({"subject": {"operator": "~", "values": [str(subject_contains)]}})

    if search_text:
        filters.append({"subjectOrId": {"operator": "**", "values": [str(search_text)]}})

    if start_date_from and start_date_to:
        filters.append(
            {"startDate": {"operator": "<>d", "values": [start_date_from, start_date_to]}}
        )

    if due_date_from and due_date_to:
        filters.append(
            {"dueDate": {"operator": "<>d", "values": [due_date_from, due_date_to]}}
        )

    if updated_since:
        filters.append(
            {"updatedAt": {"operator": "<>d", "values": [updated_since, "2099-12-31T23:59:59Z"]}}
        )

    if not filters:
        return None
    return json.dumps(filters, ensure_ascii=False)
