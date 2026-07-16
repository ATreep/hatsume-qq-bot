# Feature Specification: Background Shell Agent

**Feature Branch**: `021-background-shell-agent`

**Created**: 2026-06-30

**Status**: Draft

**Input**: User description: "Add a background_shell built-in agent to the hatsume QQ bot. This agent executes interactive or time-consuming shell commands in the background by spawning processes with output redirected to a tmp file. The agent polls periodically, uses the code model to decide next actions, and can inject mid-progress output into the main conversation without stopping itself. Total elapsed time is tracked and the process is force-killed on timeout."

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Run an Interactive Auth Command (Priority: P1)

A group member asks the bot to run a CLI authentication command (e.g., `gh auth login`). The bot starts the command in the background. When the command outputs a URL that the user needs to visit, the bot sends that URL to the group chat. While waiting for the user to complete the browser-based auth, the command stays alive in the background. Once the auth completes, the bot notifies the user that the command finished successfully.

**Why this priority**: This is the primary use case that motivated the feature — without background execution, interactive auth commands are impossible because the bot's conversation graph blocks waiting for the command to finish.

**Independent Test**: Can be tested by having a user request `gh auth login` (or a simulated command that outputs a URL then waits) and verifying that (1) the URL is relayed to chat, (2) the bot remains responsive during the wait, and (3) the success message arrives after auth completes.

**Acceptance Scenarios**:

1. **Given** a user asks the bot to run an OAuth CLI command, **When** the command outputs an authorization URL, **Then** the bot posts the URL to the group chat within 60 seconds and the bot remains available for other messages.
2. **Given** a background auth command is waiting for user action, **When** the user completes the browser-based authorization, **Then** the bot detects the command's success and notifies the user within one poll cycle.
3. **Given** a background auth command is running, **When** the command fails with an error (e.g., "Permission denied"), **Then** the bot terminates the command and notifies the user with the error output.

---

### User Story 2 — Monitor a Long-Running Command (Priority: P2)

A group member asks the bot to run a time-consuming command (e.g., a large compilation, a data processing script). The bot starts it in the background and periodically checks on it. The user can ask about progress at any time. If the command exceeds the time limit, the bot terminates it gracefully and reports what happened.

**Why this priority**: Extends the background execution model to non-interactive long-running tasks, establishing the polling and timeout patterns that apply to all background commands.

**Independent Test**: Can be tested by requesting a command that takes several minutes (e.g., `sleep 120 && echo done`) and verifying that the bot reports completion after the expected time, without blocking other interactions.

**Acceptance Scenarios**:

1. **Given** a user asks the bot to run a long compilation, **When** 5 minutes pass without the command completing, **Then** the bot terminates the command and reports the timeout with the partial output collected so far.
2. **Given** a background command is running normally with no output requiring user attention, **When** the command completes successfully, **Then** the bot notifies the user with the command's full output.
3. **Given** a background command is running, **When** the user checks the agent status via the status command, **Then** the bot shows that the background_shell agent is "running" with the task description and elapsed time.

---

### User Story 3 — Multiple Agents Running Concurrently (Priority: P3)

Different group members can dispatch different background shell tasks, and they run independently without interfering with each other. The bot can have a coding agent working while a background shell agent handles an auth flow simultaneously.

**Why this priority**: Ensures the agent infrastructure scales correctly — important for multi-user group scenarios but less critical than the core functionality.

**Independent Test**: Can be tested by dispatching two different background_shell tasks from two different users and verifying both complete independently with correct results delivered to each user.

**Acceptance Scenarios**:

1. **Given** User A's background auth command is waiting, **When** User B dispatches a different background shell command, **Then** both commands run independently without interfering, and each user receives their own command's results.
2. **Given** a background_shell agent is already running, **When** someone tries to dispatch another instance of background_shell, **Then** the system rejects the duplicate with a clear message that the agent is busy.

---

### Edge Cases

- What happens when the bot restarts while a background command is running? The process and tmp file are lost; the agent does not persist across restarts (acceptable — shell commands are transient by nature).
- What happens when the code model returns an unrecognized decision format? The agent defaults to continuing with the current poll interval.
- What happens when the tmp file for output is deleted externally? The agent reads empty output and continues polling; if the process dies, it detects this via process status.
- What happens when the total timeout is not specified by the user? A default of 300 seconds (5 minutes) is used.
- What happens when the conversation is force-cleared (via /clear command) while a background command is running? The agent task is cancelled, the process is terminated, and the tmp file is cleaned up.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The bot MUST be able to start a shell command in the background without blocking ongoing conversations.
- **FR-002**: The bot MUST redirect all command output (stdout and stderr merged) to a temporary file for incremental reading.
- **FR-003**: The bot MUST poll the running command periodically in configurable intervals (in seconds) to check for new output.
- **FR-004**: The bot MUST use its decision model to evaluate the command's output at each poll cycle and choose one of: complete (DONE), terminate (KILL), continue waiting (CONTINUE:N seconds), or notify user and continue (NOTIFY:N seconds).
- **FR-005**: When the decision model chooses NOTIFY, the bot MUST inject the current command output into the conversation so the user sees it, while the background command continues running.
- **FR-006**: The injected notification MUST include the agent name ("background_shell") and the original task description so the user and the conversation model understand the context.
- **FR-007**: The bot MUST track total elapsed time since the command started and force-terminate the command if it exceeds the specified timeout (default: 300 seconds).
- **FR-008**: The bot MUST parse the task description to extract: the shell command to execute, the termination condition, and the total timeout.
- **FR-009**: When a background command completes (DONE), the bot MUST notify the user with the command's full accumulated output and the total elapsed time.
- **FR-010**: When a background command is terminated (KILL or timeout), the bot MUST notify the user with the reason and any output collected up to termination.
- **FR-011**: Users MUST be able to see the status of the background_shell agent (running, done, elapsed time) through the existing agent status display.
- **FR-012**: The background_shell agent MUST NOT allow duplicate instances — if one is already running, a new dispatch request is rejected.

### Key Entities

- **Background Command**: Represents a running shell process. Key attributes: unique identifier, the shell command string, the tmp file path for output, start time, total timeout, elapsed time, current poll interval.
- **Poll Decision**: The result of each monitoring cycle. Values: DONE (successful completion), KILL (error termination), CONTINUE:N (continue polling after N seconds), NOTIFY:N (notify user then continue after N seconds).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can initiate an interactive auth command and receive the auth URL in chat within 60 seconds of the command outputting it.
- **SC-002**: During background command execution, the bot remains responsive to other user messages (no conversation blocking).
- **SC-003**: Background commands that exceed their timeout are terminated within one poll cycle of reaching the timeout limit.
- **SC-004**: Users can check the status of any running background command through the existing agent status command.
- **SC-005**: The system correctly handles all four decision states (DONE, KILL, CONTINUE, NOTIFY) without manual intervention for at least 95% of common shell commands.

## Assumptions

- The Docker sandbox environment used for shell execution is already configured and available (same as existing `shell_executor` tool).
- The existing agent dispatch mechanism (`agent_allocate`) and notification infrastructure (`inject_agent_notification`) function correctly and require no modification.
- The code model (used for decision-making) has sufficient capability to interpret shell command output and make reasonable poll decisions.
- Users have a way to cancel or kill background commands through the existing conversation clear mechanism or through natural language requests.
- Background process persistence across bot restarts is not required — commands are transient and restart-safe behavior is out of scope.
- Poll intervals are measured in seconds (not minutes) to allow fine-grained control over check frequency.
