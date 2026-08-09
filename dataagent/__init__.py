"""data-agent-from-scratch — a text-to-SQL agent you build yourself.

The library is deliberately tiny. Chapters own the interesting code; this
package only holds the parts every chapter shares.
"""

from dataagent.config import Settings, load_settings
from dataagent.llm import LLM, Reply, Tool, ToolCall, Usage
from dataagent.warehouse import QueryResult, UnsafeSQL, run_sql, schema_text

__all__ = [
    "LLM",
    "QueryResult",
    "Reply",
    "Settings",
    "Tool",
    "ToolCall",
    "UnsafeSQL",
    "Usage",
    "load_settings",
    "run_sql",
    "schema_text",
]
