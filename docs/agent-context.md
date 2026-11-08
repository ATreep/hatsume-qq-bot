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
- Background Agent state includes a bounded lifecycle phase/progress summary, a shared workspace marker, terminal status, and completion timestamps. Final history records include status, summary, verification fields, changed-file names, and remaining-issue summaries; raw workspace paths and full tool output are not user-facing reports.
- If 初芽 ends without attempting `send_text`, its final output is retained in
  context and included in a system reminder requiring `send_text`, followed by one
  additional invocation. An empty `text` preserves silent operation. This retry
  is independent of the dynamic MCP continuation; if the retry also ends without
  calling `send_text`, it logs a warning and stops. An attempted call satisfies
  the rule even if sending fails; this is not a delivery guarantee.
- `send_text` has no fixed per-`ai_node` invocation quota: third and later
  calls still attempt delivery, and silent calls or failed sends do not exhaust
  a text-send allowance. The per-invocation counter is diagnostic only. Existing
  reply-target validation, send-channel errors, media quotas, the seven-round
  delegation reminder, and the graph recursion limit remain unchanged.
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

初芽不直接持有 `shell_executor`；所有沙盒命令必须通过 `agent_dispatch` 派发给 `coding_agent` 或 `background_shell`。`coding_agent` 调用 `shell_executor` 时保持同步等待，以便继续根据命令输出作出下一步决策；`background_shell` 负责长时间或交互式命令的后台执行与通知。

Focused checks (use local Python, never the project `.venv`):

```sh
python3 -m unittest discover -s tests -p test_agent_context.py
python3 -m unittest discover -s tests -p test_send_text.py
python3 -m unittest discover -s tests -p test_web_researcher.py
python3 -m unittest discover -s tests -p test_shell_agent_limits.py
```

初芽的 `send_text.reply_to_message_id` 候选在每次模型可见上下文刷新时重建：只保留当前轮当前 HumanMessage 的顶层消息，以及仍可见的初芽发送结果。辅助聊天记录、被压缩掉的历史消息和不再存在于当前上下文的 AI 消息不会进入集合；提交这些 ID 时工具返回错误而不是静默降级。成功发送的 AI 消息会在工具结果中带有内部 `replyable_message_id` 标记，供后续可见轮次继续回复。

## Runtime event exchanges

Runtime notifications are `AIMessage(receive_event__injected)` + matching
`ToolMessage` pairs, not human turns. Both outer history trimming and context
compaction move cutoffs to complete tool-exchange boundaries. Summaries retain
event provenance and pending actions without attributing them to users. Synthetic
calls do not count toward delegation tool rounds and are not executable tools.
See `human-message-queue-injection.md` for the full producer matrix and delivery limits.
