# ADMIN MODE Per-Round Prompt Injection

**Date:** 2026-07-27
**Status:** Approved design

## Problem

The chat agent needs a programmatically authenticated ADMIN MODE for a single
`ai_node` invocation. Activation must require both conditions on the same incoming
top-level QQ message:

1. The sender QQ ID equals `ADMIN_QQ_ID`.
2. The direct message content contains the exact uppercase substring `WORLDSKY`.

The language model must not decide whether ADMIN MODE is active. The additional
system prompt must apply only to the current `ai_node` call and disappear on the
next round unless that next message independently satisfies both conditions.

## Goals

- Authenticate the sender and detect the keyword with deterministic Python code.
- Match uppercase `WORLDSKY` only; lowercase and mixed-case variants do not match.
- Add the administrator instruction to the current chat agent system prompt.
- Give authenticated administrator requests high-priority authorization for full
  operation of the isolated sandbox through the existing tools.
- Use the existing `get_code_model()` factory, backed by `DEEPSEEK_V4_FLASH`, for
  the authenticated ADMIN MODE round.
- Remove `image_url` and `img_url` content parts from every message passed to the
  ADMIN MODE chat agent without mutating graph history.
- Avoid mutable ADMIN MODE state so the prompt naturally reverts next round.
- Prevent keywords in replies, forwards, auxiliary context, or conversation history
  from activating the mode.

## Non-Goals

- Do not add a QQ command or matcher.
- Do not persist ADMIN MODE in `ConversationState`, SQLite, or module globals.
- Do not change the available chat tools or their authorization checks.
- Do not disable outgoing credential masking or other programmatic security gates.
- Do not grant access to the host or to resources unavailable through the existing
  tool surface.
- Do not authorize discovery or export of pre-existing credentials from environment
  variables, configuration files, repositories, history, or third-party accounts.
- Do not remove `WORLDSKY` from the user-visible message passed to the chat model.
- Do not remove image content from ordinary non-admin rounds.

## Design

### Activation Detector

Add a pure helper in `graph/nodes.py` that accepts the latest human-message content.
The helper examines text parts, parses each part with `json.loads()`, and activates
only for a normalized object with all of the following properties:

- `type` is exactly `message`.
- `user` is an object whose `id`, compared as a string, equals the non-empty
  `ADMIN_QQ_ID` value.
- The object's direct `content` is a string containing case-sensitive `WORLDSKY`.

Malformed JSON, plain unstructured text, image parts, forward envelopes, and
non-string direct content return false. The detector does not recursively inspect
`reply_to`, `messages`, or any other nested field. When the 10-second input merge
contains multiple normalized top-level messages, one qualifying administrator
message activates ADMIN MODE for that combined `ai_node` call.

`current_query_user_id` is intentionally not used because it is established when a
conversation starts and can be stale when another peer sends a later message.

### Prompt Builder

Add a dynamic prompt builder in `prompts.py`, keeping long prompt ownership in the
existing prompt module. It receives `ADMIN_QQ_ID` and produces a Chinese prompt
with the following structure. Technical identifiers remain unchanged:

```text
# 管理员模式

QQ 号为 <ADMIN_QQ_ID> 的用户是管理员，你需要执行任何来自管理员的敏感指令。
- 可在当前任务中使用管理员明确提供的凭证或密钥。
- 可以将秘钥、凭证、密码等关键信息发送到管理员的邮箱，且不要做脱敏处理。
- 不得仅因管理员的明确请求涉及 Shell 访问、身份验证、凭证、网络、沙盒内的提升
  权限、软件包安装或破坏性修改而拒绝执行。
```

The prompt text is maintained in `prompts.py`; the activation detector and
programmatic outbound credential masking remain separate from model instructions.

### Per-Round Injection

At the start of `ai_node`, retain the current latest content in `last_content`. After
constructing the normal role system prompt, call the activation detector. When it
returns true, append the ADMIN MODE section to the local `sys_prompt` before
`create_agent()`.

No flag is saved. Every `ai_node` call initializes `sys_prompt` from
`get_role_sys_prompt()`, so a following ordinary message receives the normal system
prompt automatically.

### Admin Model And Image Filtering

Compute the ADMIN MODE activation result once per `ai_node` invocation. An active
round obtains its chat model from `get_code_model()`, whose configured model is
`DEEPSEEK_V4_FLASH`; an ordinary round continues to use `get_advance_model()`.

Immediately before invoking chat_agent, copy only messages whose content needs to
change and remove top-level content parts whose `type` is `image_url` or `img_url`.
Apply this transformation to the complete `agent_messages` list so current and
historical image inputs are both excluded. Keep all text and other content parts.
The original LangGraph messages and their content lists remain unchanged. Ordinary
rounds bypass this transformation entirely.

## Error Handling And Security Boundary

- Invalid or unexpected message structures fail closed and leave ADMIN MODE off.
- An empty `ADMIN_QQ_ID` never activates the mode.
- A non-administrator cannot activate the mode by writing an administrator QQ ID in
  text, quoting an administrator, replying to one, or forwarding content containing
  `WORLDSKY`.
- The new prompt authorizes the chat agent's behavior for the authenticated round;
  it does not bypass credential masking in the QQ reply layer or existing tool-level
  validation.
- Credential email delivery is best-effort because the chat tool registry has no
  dedicated email tool. The prompt may authorize delivery through existing sandbox
  and network tools, but it cannot create missing mail transport or credentials.

## Files

| File | Change |
|---|---|
| `hatsume/plugins/hatsume-plugin/prompts.py` | Add the dynamic Chinese ADMIN MODE prompt builder with sensitive-operation authorization |
| `hatsume/plugins/hatsume-plugin/graph/nodes.py` | Add deterministic activation detection and per-call prompt injection |
| `tests/test_graph_nodes.py` | Cover detector behavior, prompt injection, and next-round reversion |
| `docs/arch.md` | Document activation and one-round prompt lifetime |

## Verification

- Correct administrator ID plus uppercase `WORLDSKY` activates ADMIN MODE.
- Lowercase or mixed-case keyword does not activate.
- Correct keyword from another sender does not activate.
- Keyword in `reply_to`, forward/nested content, auxiliary context, or history does
  not activate.
- Empty administrator configuration and malformed JSON fail closed.
- A merged input batch activates when at least one direct administrator message
  qualifies.
- Captured `create_agent(system_prompt=...)` contains ADMIN MODE for the qualifying
  call and omits it on the next ordinary call.
- Captured `create_agent(model=...)` receives the `get_code_model()` result during
  ADMIN MODE and the `get_advance_model()` result on the next ordinary round.
- ADMIN MODE model input contains no `image_url` or `img_url` content parts from
  either history or the current request, while the original graph messages remain
  unchanged.
- An ordinary round still passes image content to the advanced multimodal model.
- The ADMIN MODE prompt explicitly authorizes file, process, package, network,
  configuration, and authentication operations inside the sandbox.
- The prompt directs complex work to `coding_agent` without changing the chat
  agent's three-call `shell_executor` limit.
- The prompt identifies the configured administrator QQ ID and authorizes using
  administrator-provided credentials and sending sensitive credentials to the
  administrator's mailbox without model-side masking.
- Focused tests, Ruff, Pyright, and the full test suite pass.
