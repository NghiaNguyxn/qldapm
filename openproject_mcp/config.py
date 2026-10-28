"""
Configuration & Security Guardrails for the OpenProject MCP Server.
Loads environment variables from .env files and enforces defense-in-depth policies.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv


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
