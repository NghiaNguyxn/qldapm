"""
OpenProject MCP Server — Enterprise-Grade Model Context Protocol Server for OpenProject API v3.

Supports all 5 MCP Core Primitives:
1. Tools (75+ strongly-typed tools across 10 OpenProject API v3 domains)
2. Resources & Resource Templates (openproject:// URIs for live context injection)
3. Prompts (Standardized PM, Agile, WBS, Gantt & EVM slash workflows)
4. Sampling (Server-to-Client LLM inference requests via sampling/createMessage)
5. Roots (Client-to-Server workspace/project boundary negotiation via roots/list)

Transports:
- stdio (Standard Input/Output JSON-RPC 2.0)
- http / sse (Streamable HTTP & Server-Sent Events for remote/Docker deployment)
"""

__version__ = "2.0.0"
__author__ = "QLDAPM OpenProject MCP Team"
