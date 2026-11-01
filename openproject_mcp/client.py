"""
Production HTTP Client for OpenProject REST API v3 (application/hal+json).
Features:
- Persistent httpx.Client connection pooling
- Basic Auth (apikey:<token>) and OAuth2 Bearer Token support
- Automatic retry with exponential backoff on transient network/5xx/429 errors
- Optimistic locking (lockVersion) automatic resolution and 409 Conflict retry
- Form validation helper (/api/v3/work_packages/form, /api/v3/projects/form, etc.)
- Auto-pagination across HAL Collection pages
- Defense-in-depth Project Read/Write Allowlist enforcement
"""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import (
    ROLE_PROFILES,
    STANDARD_STATUS_IDS,
    STANDARD_TYPE_IDS,
    OpenProjectConfig,
    detect_role_from_user_dict,
    get_role_profile,
    normalize_member_role,
    resolve_member_user_id,
)
from .hal_normalizer import extract_id_from_href


class OpenProjectAPIError(Exception):
    """Structured exception raised when OpenProject API v3 returns an error."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        error_identifier: Optional[str] = None,
        details: Optional[Any] = None,
        recovery_hint: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_identifier = error_identifier
        self.details = details
        self.recovery_hint = recovery_hint

    def to_dict(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "error": True,
            "statusCode": self.status_code,
            "errorIdentifier": self.error_identifier,
            "message": self.message,
            "details": self.details,
        }
        if self.recovery_hint:
            result["recoveryHint"] = self.recovery_hint
        return result


class OpenProjectClient:
    """High-reliability HTTP client for OpenProject REST API v3."""

    def __init__(self, config: Optional[OpenProjectConfig] = None) -> None:
        self.config = config or OpenProjectConfig.from_env()
        self._client: Optional[httpx.Client] = None
        # In-memory cache for lookup metadata (statuses, types, priorities)
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._cache_ttl = 120.0  # 2 minutes
        self._runtime_role_override: Optional[str] = None
        self._detected_role: Optional[str] = None
        self._detected_user: Optional[Dict[str, Any]] = None
        self._role_detection_source: str = (
            "env_config" if self.config.member_role in ROLE_PROFILES else "auto_pending"
        )

    def _build_headers(self) -> Dict[str, str]:
        headers = {
            "Accept": "application/hal+json, application/json;q=0.9",
            "Content-Type": "application/json",
            "User-Agent": "OpenProject-MCP-Server/2.0 (Enterprise-APIv3)",
        }
        if self.config.oauth_bearer_token:
            headers["Authorization"] = f"Bearer {self.config.oauth_bearer_token}"
        elif self.config.api_key:
            token = base64.b64encode(f"apikey:{self.config.api_key}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        return headers

    @property
    def http(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=self.config.base_url,
                headers=self._build_headers(),
                timeout=httpx.Timeout(self.config.timeout_seconds),
                verify=self.config.verify_ssl,
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    # ------------------------------------------------------------------
    # Guardrail Enforcement
    # ------------------------------------------------------------------

    def guard_write_operation(self, project_ref: Optional[str | int] = None, is_delete: bool = False, is_admin: bool = False) -> None:
        """Enforce read-only, delete-guard, admin-guard, and project write allowlists."""
        if self.config.read_only:
            raise OpenProjectAPIError(
                "Write operation blocked: OPENPROJECT_READ_ONLY is enabled.",
                status_code=403,
                error_identifier="mcp:ReadOnlyPolicy",
            )
        if is_delete and not self.config.enable_delete_tools:
            raise OpenProjectAPIError(
                "Delete operation blocked: OPENPROJECT_ENABLE_DELETE_TOOLS is false.",
                status_code=403,
                error_identifier="mcp:DeletePolicyBlocked",
            )
        if is_admin and not self.config.enable_admin_tools:
            raise OpenProjectAPIError(
                "Admin operation blocked: OPENPROJECT_ENABLE_ADMIN_TOOLS is false.",
                status_code=403,
                error_identifier="mcp:AdminPolicyBlocked",
            )
        if project_ref is not None and not self.config.is_project_allowed(project_ref, write=True):
            raise OpenProjectAPIError(
                f"Project '{project_ref}' is not in OPENPROJECT_WRITE_PROJECTS allowlist.",
                status_code=403,
                error_identifier="mcp:ProjectWriteNotAllowed",
            )

    def guard_read_project(self, project_ref: Optional[str | int]) -> None:
        """Enforce project read allowlist."""
        if project_ref is not None and not self.config.is_project_allowed(project_ref, write=False):
            raise OpenProjectAPIError(
                f"Project '{project_ref}' is not in OPENPROJECT_READ_PROJECTS allowlist.",
                status_code=403,
                error_identifier="mcp:ProjectReadNotAllowed",
            )

    # ------------------------------------------------------------------
    # Core Request Dispatcher with Retry & Error Parsing
    # ------------------------------------------------------------------

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        files: Optional[Any] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Execute an API v3 HTTP request with automatic retry and HAL Error parsing."""
        if not path.startswith("http") and not path.startswith("/api/v3"):
            path = f"/api/v3/{path.lstrip('/')}"

        clean_params = {k: v for k, v in (params or {}).items() if v is not None}
        last_exc: Optional[Exception] = None

        for attempt in range(self.config.max_retries):
            try:
                if files is not None:
                    # Multipart upload: remove Content-Type: application/json so httpx sets boundary
                    req_headers = {
                        k: v for k, v in self._build_headers().items() if k.lower() != "content-type"
                    }
                    resp = self.http.request(
                        method=method.upper(),
                        url=path,
                        params=clean_params,
                        files=files,
                        data=data,
                        headers=req_headers,
                    )
                else:
                    resp = self.http.request(
                        method=method.upper(),
                        url=path,
                        params=clean_params,
                        json=json_body,
                    )

                if resp.status_code in (429, 502, 503, 504) and attempt < self.config.max_retries - 1:
                    wait = 0.6 * (2 ** attempt)
                    time.sleep(wait)
                    continue

                if resp.status_code == 204 or not resp.content:
                    return {"status": "success", "statusCode": resp.status_code}

                if resp.status_code >= 400:
                    self._raise_hal_error(resp)

                return resp.json()

            except OpenProjectAPIError:
                raise
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < self.config.max_retries - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise OpenProjectAPIError(
                    f"Network connection error to OpenProject ({self.config.base_url}{path}): {exc}",
                    status_code=503,
                    error_identifier="mcp:NetworkError",
                ) from exc

        raise OpenProjectAPIError(
            f"Request failed after {self.config.max_retries} attempts: {last_exc}",
            status_code=503,
        )

    def _raise_hal_error(self, resp: httpx.Response) -> None:
        """Parse OpenProject HAL+JSON Error response (Single or MultipleError) into OpenProjectAPIError."""
        try:
            body = resp.json()
        except Exception:
            raise OpenProjectAPIError(
                f"HTTP {resp.status_code}: {resp.text[:500]}",
                status_code=resp.status_code,
            )

        err_id = body.get("errorIdentifier")
        msg = body.get("message") or f"HTTP {resp.status_code} error"
        embedded_errors = (body.get("_embedded") or {}).get("errors")
        details = None
        if isinstance(embedded_errors, list):
            details = [
                {
                    "errorIdentifier": e.get("errorIdentifier"),
                    "message": e.get("message"),
                    "attribute": (e.get("_embedded") or {}).get("details", {}).get("attribute"),
                }
                for e in embedded_errors
                if isinstance(e, dict)
            ]
            sub_msgs = "; ".join(d["message"] for d in details if d.get("message"))
            if sub_msgs:
                msg = f"{msg} ({sub_msgs})"
        else:
            details = (body.get("_embedded") or {}).get("details")

        raise OpenProjectAPIError(
            message=msg,
            status_code=resp.status_code,
            error_identifier=err_id,
            details=details,
        )

    # ------------------------------------------------------------------
    # Convenience HTTP Verbs & Pagination
    # ------------------------------------------------------------------

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("POST", path, params=params, json_body=json_body)

    def patch(self, path: str, json_body: Optional[Dict[str, Any]] = None, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("PATCH", path, params=params, json_body=json_body)

    def delete(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self.request("DELETE", path, params=params)

    def get_cached(self, key: str, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Fetch and cache relatively static reference data (statuses, types, priorities, roles)."""
        now = time.time()
        if key in self._cache:
            ts, data = self._cache[key]
            if now - ts < self._cache_ttl:
                return data
        data = self.get(path, params=params)
        self._cache[key] = (now, data)
        return data

    def invalidate_cache(self) -> None:
        """Clear cached reference data."""
        self._cache.clear()

    def fetch_all_elements(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        max_items: int = 500,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        Automatically paginate through an OpenProject HAL Collection endpoint
        and return (elements_list, total_count).
        """
        query = dict(params or {})
        page_size = min(int(query.get("pageSize", self.config.default_page_size)), self.config.max_page_size)
        offset = int(query.get("offset", 1))
        query["pageSize"] = page_size

        collected: List[Dict[str, Any]] = []
        total_reported = 0

        while len(collected) < max_items:
            query["offset"] = offset
            data = self.get(path, params=query)
            total_reported = data.get("total", 0)
            elements = (data.get("_embedded") or {}).get("elements") or []
            if not elements:
                break
            collected.extend(elements)
            if len(elements) < page_size or len(collected) >= total_reported:
                break
            offset += 1

        return collected[:max_items], total_reported or len(collected)

    # ------------------------------------------------------------------
    # Optimistic Locking (lockVersion) Helper
    # ------------------------------------------------------------------

    def patch_work_package_safe(
        self,
        wp_id: int | str,
        payload: Dict[str, Any],
        notify: bool = True,
    ) -> Dict[str, Any]:
        """
        Update a work package via PATCH /api/v3/work_packages/{id}, automatically
        fetching lockVersion if missing and retrying once on HTTP 409 Conflict.
        """
        body = dict(payload)
        params = {"notify": "true" if notify else "false"}

        for attempt in range(2):
            if "lockVersion" not in body or body["lockVersion"] is None or attempt > 0:
                current = self.get(f"/api/v3/work_packages/{wp_id}")
                body["lockVersion"] = current.get("lockVersion", 0)
            try:
                return self.patch(f"/api/v3/work_packages/{wp_id}", json_body=body, params=params)
            except OpenProjectAPIError as exc:
                if exc.status_code == 409 and attempt == 0:
                    continue
                raise
        raise OpenProjectAPIError(f"Failed to update work package {wp_id} due to lockVersion conflict.")

    # ------------------------------------------------------------------
    # Team Role Auto-Detection, Switching & Assignee Resolution
    # ------------------------------------------------------------------

    def get_effective_role(self, allow_network: bool = True) -> str:
        """
        Determine the active QLDAPM team member role ('PM', 'BA', 'BE', 'FE', 'TESTER').
        Priority:
        1. Runtime role switch via op_switch_role
        2. Explicit OPENPROJECT_MEMBER_ROLE in .env / OpenProjectConfig
        3. Auto-detection from /api/v3/users/me when OPENPROJECT_MEMBER_ROLE=AUTO
        4. Fallback to 'PM' when offline or unrecognized user
        """
        if self._runtime_role_override and self._runtime_role_override in ROLE_PROFILES:
            self._role_detection_source = "runtime_switch"
            return self._runtime_role_override

        cfg_role = normalize_member_role(self.config.member_role, default="AUTO")
        if cfg_role in ROLE_PROFILES:
            self._role_detection_source = "env_config"
            return cfg_role

        if self._detected_role and self._detected_role in ROLE_PROFILES:
            self._role_detection_source = "api_users_me"
            return self._detected_role

        if allow_network:
            try:
                me = self.get_cached("users:me", "/api/v3/users/me")
                detected = detect_role_from_user_dict(me)
                if detected and detected in ROLE_PROFILES:
                    self._detected_role = detected
                    self._detected_user = me
                    self._role_detection_source = "api_users_me"
                    return detected
            except Exception:
                pass

        self._role_detection_source = "fallback_default_pm"
        return "PM"

    def switch_role(self, new_role: str, persist_to_config: bool = True) -> Dict[str, Any]:
        """Switch the active team member role at runtime ('PM', 'BA', 'BE', 'FE', 'TESTER', or 'AUTO')."""
        try:
            norm = normalize_member_role(new_role, strict=True)
        except ValueError as exc:
            raise OpenProjectAPIError(
                str(exc),
                status_code=400,
                error_identifier="mcp:InvalidParameter",
                recovery_hint="Pass one of the valid QLDAPM role codes: 'PM', 'BA', 'BE', 'FE', 'TESTER', or 'AUTO'.",
            ) from exc
        if norm == "AUTO":
            self._runtime_role_override = None
            self._detected_role = None
            if persist_to_config:
                self.config.member_role = "AUTO"
            self.get_effective_role(allow_network=True)
        else:
            self._runtime_role_override = norm
            self._role_detection_source = "runtime_switch"
            if persist_to_config:
                self.config.member_role = norm
        return self.get_role_context(allow_network=False)

    def get_role_context(
        self,
        role_override: Optional[str] = None,
        allow_network: bool = True,
    ) -> Dict[str, Any]:
        """Build a complete role context payload including user_id, weight, transitions, and SKILL.md path."""
        active_role = self.get_effective_role(allow_network=allow_network)
        if role_override and str(role_override).strip().upper() != "AUTO":
            try:
                target_role = normalize_member_role(role_override, strict=True)
            except ValueError as exc:
                raise OpenProjectAPIError(
                    str(exc),
                    status_code=400,
                    error_identifier="mcp:InvalidParameter",
                    recovery_hint="Use a valid role code ('PM', 'BA', 'BE', 'FE', 'TESTER', 'AUTO') or omit 'role' to inspect the active role.",
                ) from exc
        else:
            target_role = active_role
        profile = get_role_profile(target_role)
        team_roster = [
            {
                "role": r_key,
                "userId": r_val["user_id"],
                "memberName": r_val["member_name"],
                "fullNameVi": r_val["full_name_vi"],
                "email": r_val.get("email", r_val["login"]),
                "login": r_val["login"],
                "subtaskPrefix": r_val["subtask_prefix"],
                "weightRatio": r_val["weight_ratio"],
                "skillRelativePath": r_val["skill_relative_path"],
            }
            for r_key, r_val in ROLE_PROFILES.items()
        ]
        return {
            "activeRole": active_role,
            "inspectedRole": target_role,
            "configuredRoleEnv": self.config.member_role,
            "detectionSource": self._role_detection_source,
            "memberProfile": {
                "role": profile["role"],
                "title": profile["title"],
                "userId": profile["user_id"],
                "memberName": profile["member_name"],
                "fullNameVi": profile["full_name_vi"],
                "email": profile.get("email", profile["login"]),
                "login": profile["login"],
                "subtaskPrefix": profile["subtask_prefix"],
                "weightPercent": profile["weight_percent"],
                "weightRatio": profile["weight_ratio"],
                "description": profile.get("description", ""),
                "defaultStoryPoints": profile["default_story_points"],
                "defaultEstimatedHoursPerScreen": profile["default_estimated_hours_per_screen"],
            },
            "skill": {
                "skillName": profile["skill_name"],
                "skillRelativePath": profile["skill_relative_path"],
                "skillAbsolutePath": profile["skill_absolute_path"],
                "agentsDispatcherPath": profile["agents_md_path"],
            },
            "permissionsAndGuardrails": {
                "ownedTiers": profile["owned_tiers"],
                "canCreateEpicOrTask": profile["can_create_epic_or_task"],
                "canDeleteEpicOrTask": profile["can_delete_epic_or_task"],
                "canTransitionEpicOrTask": profile.get("can_transition_epic_or_task", False),
                "canCloseEpicOrTask": profile["can_close_epic_or_task"],
                "allowedEpicTransitions": profile["allowed_epic_transitions"],
                "allowedTaskTransitions": profile["allowed_task_transitions"],
                "allowedSubtaskTransitions": profile["allowed_subtask_transitions"],
            },
            "recommendedTools": profile["recommended_tools"],
            "teamRoster": team_roster,
        }

    def resolve_assignee_id(
        self,
        assignee_ref: Any,
        default_to_active_role: bool = False,
        allow_network_Role_detect: bool = True,
    ) -> Optional[int | str]:
        """
        Resolve an assignee parameter ('me', 'tôi', 'PM', 'BA', 'BE', 'FE', 'TESTER',
        'Nghĩa', 'Trung', 'Hiếu', 'Thành', 'Vinh', or integer ID) into an OpenProject user_id.
        """
        active_role = self.get_effective_role(allow_network=allow_network_Role_detect)
        if assignee_ref is None:
            if default_to_active_role:
                return int(ROLE_PROFILES[active_role]["user_id"])
            return None

        resolved = resolve_member_user_id(assignee_ref, active_role=active_role)
        if resolved is not None:
            return resolved

        raise OpenProjectAPIError(
            f"Unknown assignee or role reference '{assignee_ref}'. "
            "Valid values: numeric user_id (4..8), 'me'/'tôi', role codes ('PM', 'BA', 'BE', 'FE', 'TESTER'), "
            "or team member names ('Nghĩa', 'Trung', 'Hiếu', 'Thành', 'Vinh').",
            status_code=400,
            error_identifier="mcp:InvalidAssigneeReference",
            recovery_hint="Use 'me', 'PM' (4), 'BA' (5), 'BE' (6), 'FE' (7), 'TESTER' (8), or call op_get_role_context() to view teamRoster.",
        )

    # ------------------------------------------------------------------
    # Name-to-ID Lookup Resolvers (Statuses, Types, Priorities)
    # ------------------------------------------------------------------

    def resolve_status_id(self, status_id_or_name: int | str) -> int:
        if isinstance(status_id_or_name, int) or str(status_id_or_name).isdigit():
            return int(status_id_or_name)
        target = str(status_id_or_name).strip().lower()
        if "statuses" not in self._cache and target in STANDARD_STATUS_IDS:
            return STANDARD_STATUS_IDS[target]

        synonyms_map = {
            "ready": ("ready", "to do", "todo", "new"),
            "to do": ("ready", "to do", "todo", "new"),
            "todo": ("ready", "to do", "todo", "new"),
            "new": ("ready", "new", "to do"),
            "done": ("done", "closed", "completed"),
            "closed": ("done", "closed", "completed"),
        }
        candidate_names = synonyms_map.get(target, (target,))

        try:
            data = self.get_cached("statuses", "/api/v3/statuses")
            elements = (data.get("_embedded") or {}).get("elements") or []
            for cand in candidate_names:
                for s in elements:
                    s_name = str(s.get("name", "")).strip().lower()
                    if s_name == cand:
                        return int(s["id"])
            for cand in candidate_names:
                for s in elements:
                    s_name = str(s.get("name", "")).strip().lower()
                    if cand in s_name:
                        return int(s["id"])
            available = [f"{s.get('id')}:{s.get('name')}" for s in elements]
        except OpenProjectAPIError:
            if target in STANDARD_STATUS_IDS:
                return STANDARD_STATUS_IDS[target]
            raise

        if target in STANDARD_STATUS_IDS:
            return STANDARD_STATUS_IDS[target]
        raise OpenProjectAPIError(
            f"Unknown status '{status_id_or_name}'. Available statuses: {', '.join(available)}",
            status_code=400,
        )

    def resolve_type_id(self, type_id_or_name: int | str, project_id: Optional[int | str] = None) -> int:
        if isinstance(type_id_or_name, int) or str(type_id_or_name).isdigit():
            return int(type_id_or_name)
        target = str(type_id_or_name).strip().lower()
        cache_key = f"types:{project_id or 'global'}"
        if cache_key not in self._cache and target in STANDARD_TYPE_IDS:
            return STANDARD_TYPE_IDS[target]

        target_compact = target.replace("-", "").replace("_", "").replace(" ", "")
        path = f"/api/v3/projects/{project_id}/types" if project_id else "/api/v3/types"
        try:
            data = self.get_cached(cache_key, path)
            elements = (data.get("_embedded") or {}).get("elements") or []
            for t in elements:
                t_name = str(t.get("name", "")).strip().lower()
                t_compact = t_name.replace("-", "").replace("_", "").replace(" ", "")
                if t_name == target or t_compact == target_compact:
                    return int(t["id"])
            for t in elements:
                t_name = str(t.get("name", "")).strip().lower()
                if target in t_name:
                    return int(t["id"])
            available = [f"{t.get('id')}:{t.get('name')}" for t in elements]
        except OpenProjectAPIError:
            if target in STANDARD_TYPE_IDS:
                return STANDARD_TYPE_IDS[target]
            raise

        if target in STANDARD_TYPE_IDS:
            return STANDARD_TYPE_IDS[target]
        raise OpenProjectAPIError(
            f"Unknown work package type '{type_id_or_name}'. Available types: {', '.join(available)}",
            status_code=400,
        )

    def resolve_priority_id(self, priority_id_or_name: int | str) -> int:
        if isinstance(priority_id_or_name, int) or str(priority_id_or_name).isdigit():
            return int(priority_id_or_name)
        target = str(priority_id_or_name).strip().lower()
        data = self.get_cached("priorities", "/api/v3/priorities")
        elements = (data.get("_embedded") or {}).get("elements") or []
        for p in elements:
            if str(p.get("name", "")).strip().lower() == target:
                return int(p["id"])
        for p in elements:
            if target in str(p.get("name", "")).strip().lower():
                return int(p["id"])
        available = [f"{p.get('id')}:{p.get('name')}" for p in elements]
        raise OpenProjectAPIError(
            f"Unknown priority '{priority_id_or_name}'. Available priorities: {', '.join(available)}",
            status_code=400,
        )

    def upload_attachment_file(
        self,
        container_path: str,
        file_path: str,
        description: str = "",
        custom_file_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload a local file as an OpenProject attachment using multipart/form-data."""
        p = Path(file_path).resolve()
        if not p.is_file():
            raise OpenProjectAPIError(f"Attachment file not found: {file_path}", status_code=400)
        file_name = custom_file_name or p.name
        metadata = {"fileName": file_name}
        if description:
            metadata["description"] = {"raw": description}

        with p.open("rb") as fh:
            files = {
                "metadata": (None, json.dumps(metadata), "application/json"),
                "file": (file_name, fh, "application/octet-stream"),
            }
            return self.request("POST", container_path, files=files)
