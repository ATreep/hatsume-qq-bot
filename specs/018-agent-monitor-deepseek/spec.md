# Feature Specification: Agent Monitor & Deepseek Provider

**Feature Branch**: `019-agent-monitor-deepseek`

**Created**: 2026-06-28

**Status**: Draft

**Input**: User description: "Add the following functions. 1. add an agent monitor to record each subagent's running state and the chat agent can view each subagent's state by this tool. Aside, add a limitation to agent allocate. if one agent has been running, these tool cannot allocate this agent again. 2. add a new model provider, which is Deepseek. The get_code_model function should return the Deepseek model. The model base URL is Deepseek's official OpenAI compatible complete API URL, and the model name is Deepseek v4 Pro. And then the Deepseek API key should be recorded in the dotenv file."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Chat Agent Checks Subagent Status (Priority: P1)

The chat agent (初芽) receives a user request that may involve a long-running background task. Before dispatching a new task to a subagent, the chat agent can check whether that subagent is currently busy with another task. After a subagent completes, the chat agent can query its final output to present results to the user.

**Why this priority**: This is the core monitoring capability — without it, the chat agent is blind to subagent state and may allocate duplicate work, confusing users.

**Independent Test**: Can be fully tested by invoking the agent status query mechanism with a known agent name and verifying the response correctly reflects idle, running, or done state with associated task/output details.

**Acceptance Scenarios**:

1. **Given** no subagent has ever been used, **When** the chat agent queries the status of "coding_agent", **Then** the system returns a message indicating the agent has no record and lists available agents.
2. **Given** the "coding_agent" is currently executing a task "fix login bug", **When** the chat agent queries its status, **Then** the system returns "running" status with the task description and start time.
3. **Given** the "coding_agent" has completed a task with result "bug fixed successfully", **When** the chat agent queries its status, **Then** the system returns "done" status with the task description and full output.

---

### User Story 2 - Prevent Duplicate Subagent Allocation (Priority: P1)

When a user requests work that requires dispatching a subagent (e.g., coding_agent), and that same subagent is already processing a prior task, the system prevents a second allocation and informs the chat agent that the subagent is busy.

**Why this priority**: Preventing duplicate allocation is equally critical — running two instances of the same agent on different tasks causes resource conflicts and unpredictable behavior.

**Independent Test**: Can be tested by simulating a running agent state and attempting a second allocation, verifying the system rejects it with a clear "agent busy" message.

**Acceptance Scenarios**:

1. **Given** the "coding_agent" is currently running, **When** the chat agent attempts to allocate "coding_agent" for a new task, **Then** the system returns an error message "Agent 'coding_agent' 正在执行中，请等待完成后再分配。"
2. **Given** the "coding_agent" is idle (not running), **When** the chat agent allocates "coding_agent" for a task, **Then** the system accepts the allocation and the agent begins executing with state set to "running".
3. **Given** the "coding_agent" has completed (state "done"), **When** the chat agent allocates "coding_agent" for a new task, **Then** the system accepts the allocation normally (state transitions from done to running).

---

### User Story 3 - Deepseek Powers Code-Related Tasks (Priority: P2)

When the system needs to generate code, execute HTML rendering, or run the coding agent, it uses the Deepseek model provider (deepseek-chat / V4 Pro) through Deepseek's official API endpoint, configured via an environment variable for the API key.

**Why this priority**: This is a provider configuration change that enables code-related features to use a different, potentially better model. It is P2 because code tasks still function with the existing provider if Deepseek is unavailable.

**Independent Test**: Can be tested by invoking the code model factory function and verifying the returned model instance is configured with Deepseek's base URL, model name "deepseek-chat", and an API key sourced from the DEEPSEEK_API_KEY environment variable.

**Acceptance Scenarios**:

1. **Given** the `DEEPSEEK_API_KEY` environment variable is set to "sk-test-123", **When** the system creates a code model via `get_code_model()`, **Then** the model uses `https://api.deepseek.com/v1` as base URL, "deepseek-chat" as model name, and the API key resolves to "sk-test-123".
2. **Given** the `DEEPSEEK_API_KEY` environment variable is empty, **When** the system creates a code model, **Then** the model is still created with Deepseek configuration (authentication failure is handled by the API at request time).
3. **Given** the `.env.prod` configuration file, **When** an administrator inspects it, **Then** a `DEEPSEEK_API_KEY=` entry exists for manual key configuration.

---

### Edge Cases

- **Agent crash during execution**: If the subagent handler raises an exception, the state is still set to "done" with the error message stored as the result. The chat agent can query it to see what went wrong.
- **System restart**: Agent states are stored in-memory and are lost on restart. Any agents that were "running" before restart are orphaned (no recovery mechanism — acceptable for MVP).
- **Empty API key**: The Deepseek provider is created with whatever value `DEEPSEEK_API_KEY` has. If empty, Deepseek's API will return a 401 error at request time — this is expected and transparent.
- **Race condition on agent allocation**: In Python's single-threaded asyncio event loop, the state check and task creation happen sequentially within the same coroutine, so no real race condition exists between checking "is running" and dispatching.

## Requirements *(mandatory)*

### Functional Requirements

**Agent Monitor:**

- **FR-001**: The system MUST track each subagent's execution state with three possible states: idle, running, and done.
- **FR-002**: The system MUST record, for each agent: current status, task description, notified user ID, start timestamp, and result output (when done).
- **FR-003**: The system MUST provide a mechanism for the chat agent to query the current status and result of a specific subagent by name.
- **FR-004**: The system MUST prevent allocation of a subagent that is currently in "running" state, returning a clear error message instead.
- **FR-005**: The system MUST allow allocation of a subagent that is in "idle" or "done" state.
- **FR-006**: The system MUST transition agent state from idle to running upon successful allocation, and from running to done upon completion (whether success or failure).
- **FR-007**: Agent states MUST be stored in memory (no persistence across restarts required).

**Deepseek Provider:**

- **FR-008**: The system MUST provide a Deepseek model configuration using Deepseek's official OpenAI-compatible API base URL (`https://api.deepseek.com/v1`).
- **FR-009**: The system MUST use the model identifier `deepseek-chat` for Deepseek API calls.
- **FR-010**: The system MUST read the Deepseek API key from the `DEEPSEEK_API_KEY` environment variable.
- **FR-011**: The `.env.prod` configuration file MUST contain a `DEEPSEEK_API_KEY=` placeholder entry for manual key configuration.
- **FR-012**: The `get_code_model()` factory function MUST return a model instance configured for Deepseek (not the previous volcengine-based configuration).

### Key Entities

- **AgentState**: Represents the running state of a single subagent. Fields: agent name (string key), status (enum: idle/running/done), task description (string), user ID (integer), started_at (Unix timestamp), result (string or null).
- **DeepseekConfig**: Configuration values for the Deepseek provider. Fields: base_url (string), model (string = "deepseek-chat"), api_key (string, sourced from environment).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The chat agent can query any subagent's status and receive an accurate response within 1 second.
- **SC-002**: Duplicate agent allocation is 100% prevented — no two tasks can run on the same agent simultaneously.
- **SC-003**: Failed agent tasks are recorded with their error output and are queryable (no silent failures).
- **SC-004**: The `get_code_model()` function returns a model configured with Deepseek parameters in under 100ms.
- **SC-005**: Existing functionality (coding agent, HTML rendering) continues to work with the Deepseek provider when a valid API key is configured.

## Assumptions

- The Deepseek API key will be manually configured by the operator in `.env.prod` after deployment.
- In-memory agent state tracking is sufficient — no persistence across restarts is needed for MVP.
- The existing `ChatOpenAI` class from LangChain is compatible with Deepseek's OpenAI-compatible API.
- The monkey-patch for `reasoning_content` in `models.py` already handles Deepseek-compatible response formats.
