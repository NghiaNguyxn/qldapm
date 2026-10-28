"""
MCP Tool Registry with JSON Schema generation, MCP Tool Annotations,
and structured error handling.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .client import OpenProjectAPIError, OpenProjectClient


@dataclass
class ToolDefinition:
    """Represents a single MCP Tool with JSON Schema and MCP Annotations."""

    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[[OpenProjectClient, Dict[str, Any]], Any]
    domain: str = "general"
    read_only: bool = True
    destructive: bool = False
    idempotent: bool = False

    def to_mcp_schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": f"[{self.domain.upper()}] {self.description}",
            "inputSchema": self.input_schema,
            "annotations": {
                "title": self.name.replace("_", " ").title(),
                "readOnlyHint": self.read_only,
                "destructiveHint": self.destructive,
                "idempotentHint": self.idempotent,
                "openWorldHint": True,
            },
        }


class ToolRegistry:
    """Central catalog of all MCP tools exposed by the OpenProject MCP Server."""

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        properties: Dict[str, Any],
        required: Optional[List[str]] = None,
        *,
        domain: str = "general",
        read_only: bool = True,
        destructive: bool = False,
        idempotent: bool = False,
    ) -> Callable[[Callable[[OpenProjectClient, Dict[str, Any]], Any]], Callable[[OpenProjectClient, Dict[str, Any]], Any]]:
        """Decorator to register an MCP tool."""
        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        def _decorator(func: Callable[[OpenProjectClient, Dict[str, Any]], Any]) -> Callable[[OpenProjectClient, Dict[str, Any]], Any]:
            self._tools[name] = ToolDefinition(
                name=name,
                description=description,
                input_schema=schema,
                handler=func,
                domain=domain,
                read_only=read_only,
                destructive=destructive,
                idempotent=idempotent,
            )
            return func

        return _decorator

    def list_tools(
        self,
        read_only_mode: bool = False,
        enable_delete: bool = True,
        enable_admin: bool = True,
    ) -> List[Dict[str, Any]]:
        """Return MCP-compliant tool schemas filtered by active security policy."""
        output: List[Dict[str, Any]] = []
        for tool in self._tools.values():
            if read_only_mode and not tool.read_only:
                continue
            if not enable_delete and tool.destructive:
                continue
            if not enable_admin and tool.domain == "admin":
                continue
            output.append(tool.to_mcp_schema())
        return output

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self._tools.get(name)

    @property
    def tools(self) -> Dict[str, ToolDefinition]:
        return self._tools

    def execute(self, name: str, client: OpenProjectClient, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a registered tool and format its output as an MCP CallToolResult."""
        tool = self._tools.get(name)
        if not tool:
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "error": True,
                                "message": f"Unknown tool '{name}'. Call tools/list to inspect available tools.",
                            },
                            ensure_ascii=False,
                        ),
                    }
                ],
            }

        args = arguments or {}
        try:
            result = tool.handler(client, args)
            text_out = (
                result
                if isinstance(result, str)
                else json.dumps(result, ensure_ascii=False, indent=2)
            )
            return {
                "isError": False,
                "content": [{"type": "text", "text": text_out}],
            }
        except OpenProjectAPIError as api_err:
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(api_err.to_dict(), ensure_ascii=False, indent=2),
                    }
                ],
            }
        except Exception as exc:
            return {
                "isError": True,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "error": True,
                                "errorIdentifier": "mcp:InternalToolExecutionError",
                                "message": str(exc),
                                "trace": traceback.format_exc(limit=3),
                            },
                            ensure_ascii=False,
                            indent=2,
                        ),
                    }
                ],
            }
