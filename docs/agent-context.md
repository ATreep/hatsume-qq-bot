# Agent context management

Chat, coding, web research, and background-shell monitoring share the context
policy in `hatsume/plugins/hatsume-plugin/graph/context.py`.

- At approximately **48,000 message tokens**, older messages are replaced by a
  continuation summary. About **12,000 recent tokens** are retained, respecting
  tool-call/result boundaries. Compaction runs before model calls within a loop.
- The summarizer uses the agent's existing model and configured provider/failover
  chain. Up to **64,000 tokens** of older history are supplied to it. The prompt
  asks for a concise record of objectives, constraints, decisions, verified
  results, file references, process state, and next steps.
- A failed or empty summary raises an error without replacing the original
  history. Existing invocation error/retry handling remains in effect.
- Tool text exceeding **16,000 characters** is archived in full under
  `/work/.hatsume-context/<group_id>/output-<random_id>.txt`. The model receives
  a bounded head/tail excerpt with the archive path, recoverable through
  `shell_executor`. MCP text blocks share this budget; non-text media blocks
  remain intact. Archives remain until explicitly removed from the workspace.
- Background shell retains a compactable decision history and supplies each new
  output chunk once. Its notifications and final report also use output archives
  for large logs; monitoring no longer resends the entire accumulated log on
  every decision.
- Chat delegation counts completed tool rounds independently of message history,
  including across MCP tool-loading passes. Compaction does not reset the count
  or cause the seven-round reminder to repeat.
- Coding streams apply LangGraph's message reducer, including removals and
  replacements from summarization. Raw Agent work-history records are separate
  from model context and retain their existing behavior.
- The coding agent's Agent Loop uses protected-message compaction: older
  `AIMessage` work calls and `ToolMessage` results are replaced by a
  continuation summary, while every `SystemMessage` and `HumanMessage` remains
  in the context with its original content and ordering relative to the
  summarized work. Other agents keep the standard compaction policy.

Budgets are centralized constants. The defaults assume models with enough input
capacity for these budgets, normally at least 128k. Adjust them for smaller
models, including the smallest fallback model. Message counts are estimates;
reserve additional capacity for system prompts, tool definitions, summaries,
multimodal input, and generated output. Summarization compresses text history;
it does not resize image/audio/video payloads or prevent an oversized system
prompt or a single oversized user message.

Focused checks (use local Python, never the project `.venv`):

```sh
python3 -m unittest discover -s tests -p test_agent_context.py
python3 -m unittest discover -s tests -p test_web_researcher.py
python3 -m unittest discover -s tests -p test_shell_agent_limits.py
```
