# Feature Specification: Background Shell Stdin Injection

**Feature Branch**: `022-bg-shell-stdin-injection`

**Created**: 2026-06-30

**Status**: Draft

**Input**: User description: "The background shell agent should have the ability of input by stdin to the current running process. Though the bg shell agent is running, the chat agent can pass new information to the bg shell agent and the bg shell agent can input text to stdin (such as authenticated code)"

## Clarifications

### Session 2026-06-30

- Q: How should simple confirmation prompts be handled — should they bypass the notification mechanism entirely? → A: Route everything through INPUT_NEEDED with notification. The user always sees a brief stdin request notification, and the resolution model auto-answers simple prompts within seconds without requiring the user to type anything.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Interactive Command with Password Input (Priority: P1)

A user in a QQ group asks the bot to run a command that requires authentication, such as `sudo apt install nginx`. The bot starts the background shell agent to execute the command. When the process prompts for a sudo password, the bot detects the stdin request and asks the user for the password in the chat. The user provides it, the bot forwards it to the process via stdin, and the installation continues to completion.

**Why this priority**: This is the core use case — without stdin injection, any interactive command that requires authentication or confirmation is immediately killed. This enables the most common interactive shell scenarios.

**Independent Test**: Can be fully tested by asking the bot to run an interactive shell script that reads from stdin and echoes the input back. The test validates the full pipeline: detection → notification → user response → stdin write → process continues.

**Acceptance Scenarios**:

1. **Given** the bot is in a QQ group chat, **When** a user asks the bot to run a command that requires password input (e.g., `sudo apt install nginx`), **Then** the bot dispatches the command to the background shell agent, detects the password prompt, notifies the user in chat with a stdin request, and waits for the user to respond with the password.
2. **Given** the bot has issued a stdin request for a password, **When** the user provides the password in chat, **Then** the bot writes the password to the process's stdin, the process authenticates and continues execution, and the bot reports completion to the user.
3. **Given** the bot has issued a stdin request, **When** the user provides irrelevant or incorrect input, **Then** the bot re-requests with a clearer description of what input is needed.

---

### User Story 2 - Confirmation Prompt Auto-Response (Priority: P2)

A user asks the bot to run a command that encounters a `[y/N]` confirmation prompt mid-execution. The background shell agent detects the prompt and sends a brief stdin request notification to the chat. Since this is a simple confirmation, the resolution code model autonomously decides to answer "N" (safe default) without requiring the user to type anything. The command continues or exits gracefully.

**Why this priority**: Many commands produce confirmation prompts (`apt install`, `rm -rf`, etc.). The hybrid approach (always notify, but auto-answer simple prompts in the resolution stage) provides transparency while keeping common cases hands-free.

**Independent Test**: Can be tested with a script that prints `Continue? [y/N]` and reads from stdin. The test verifies that a notification is sent to the chat, but the resolution model auto-answers without any user input, and the process continues.

**Acceptance Scenarios**:

1. **Given** a background process outputs `Continue? [y/N]` and waits for stdin, **When** the code model determines this is a low-risk confirmation, **Then** the agent sends a brief stdin request notification to the chat, the resolution model autonomously writes "N\n" to stdin (safe default) within seconds, and monitoring continues without requiring user input.
2. **Given** a background process outputs a confirmation prompt that has safety implications, **When** the code model assesses the risk, **Then** it escalates to the user via an INPUT_NEEDED notification with a longer timeout, waiting for explicit user input rather than auto-answering.
3. **Given** a background process outputs a confirmation prompt but the agent cannot determine the correct response, **When** the confirmation is ambiguous, **Then** it signals in the notification that user input is required rather than attempting to guess.

---

### User Story 3 - Token/Auth Code Mid-Execution (Priority: P2)

A user asks the bot to run `gh auth login` which opens a browser-based OAuth flow. The background shell agent detects the process is waiting for an auth token and notifies the user with the URL to visit. The user completes the OAuth flow in their browser, copies the token, and pastes it in chat. The bot writes the token to the process's stdin, completing the authentication.

**Why this priority**: CLI tools increasingly use browser-based auth flows. Being able to handle the auth code passthrough makes the bot usable for modern DevOps workflows (GitHub CLI, cloud CLIs, etc.).

**Independent Test**: Can be tested with a script that simulates an auth flow — outputs an instruction with a fake URL, reads a token from stdin, and echoes success. Validates the URL→notify→token→stdin chain.

**Acceptance Scenarios**:

1. **Given** a background process outputs a URL for authentication (e.g., `gh auth login`), **When** the agent detects the URL and stdin wait, **Then** it notifies the user with the URL and a stdin request for the auth code.
2. **Given** the user has received the URL notification and completed the auth flow, **When** the user provides the auth code/token in chat, **Then** the bot writes the token to the process's stdin, and the auth completes.
3. **Given** the auth flow takes longer than the default timeout, **When** the agent determines the wait requires more time, **Then** it adjusts the timeout accordingly (up to 10 minutes for auth flows).

---

### User Story 4 - Stdin Timeout with Safe Default (Priority: P3)

A background process waits for stdin input, the agent notifies the user, but the user does not respond within the timeout period. The code model assesses the situation and, for a simple confirmation prompt, answers "N" (safe default) rather than killing the process. For a password/token prompt where no safe default exists, the agent kills the process and reports the timeout to the user.

**Why this priority**: Timeout handling ensures the bot doesn't hang indefinitely when the user is away. The intelligent fallback (safe defaults vs. kill) prevents resource waste while maintaining safety.

**Independent Test**: Can be tested by having a script wait for stdin with a 10-second timeout set, never providing input, and verifying the agent either auto-answers or kills based on prompt type.

**Acceptance Scenarios**:

1. **Given** a process is waiting for a confirmation `[y/N]` and the user has not responded after the timeout, **When** the timeout expires, **Then** the agent autonomously writes "N\n" (safe default) and the process continues.
2. **Given** a process is waiting for a password and the user has not responded after the timeout, **When** the timeout expires and no safe default exists, **Then** the agent kills the process and notifies the user of the timeout.
3. **Given** a process is waiting for input and the timeout is approaching, **When** the agent still deems the wait valuable, **Then** it may re-issue the INPUT_NEEDED notification with a refreshed timeout.

---

### Edge Cases

- What happens when the process exits while waiting for stdin input? The agent detects the process has terminated, reads any remaining output, and declares the task complete.
- What happens when the same stdin request is replied to twice? The first reply is delivered to the process; the second reply is rejected with an error message explaining the request was already handled.
- What happens when a stdin response is sent with an invalid or expired request identifier? The system returns a descriptive error message indicating the request was not found.
- What happens when the execution environment crashes mid-stdin-wait? The agent detects the failure and performs a graceful cleanup of all pending requests.
- What happens when stdin write fails (process already exited)? The write operation reports failure, and the agent detects the exited process on its next status check and completes normally.
- What happens if a stdin response is sent when no background process is running? The request identifier won't match any pending request, and the system returns an error.
- What happens with special characters in stdin text? All text is properly encoded before being sent to the process, supporting the full character set used in shell interactions.
- What happens when multiple background shell processes attempt to run concurrently? The system prevents concurrent execution; additionally, each process has an independent identifier namespace preventing cross-process interference.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST spawn background shell processes with a writable stdin channel.
- **FR-002**: System MUST detect when a background process is waiting for interactive stdin input, using both output pattern analysis and output timeout heuristics via the code model.
- **FR-003**: System MUST support an `INPUT_NEEDED` decision type in the background shell agent's poll loop, with configurable timeout (default 300 seconds) and human-readable description.
- **FR-004**: System MUST notify the chat agent when stdin input is required, including a unique request_id, the description of what input is needed, the recent process output context, and the timeout duration.
- **FR-005**: System MUST provide a mechanism for the chat agent to pass raw input text to the background shell agent's stdin queue.
- **FR-006**: System MUST route chat agent responses to the correct background process using the request_id from the INPUT_NEEDED notification.
- **FR-007**: The background shell agent's code model MUST mediate between the raw text from the chat agent and the final stdin content, transforming the text to match the process's expected format.
- **FR-008**: System MUST handle stdin request timeouts gracefully — the code model decides whether to provide a safe default answer, re-issue the request, or kill the process.
- **FR-009**: System MUST cancel stdin requests and kill the process if the overall command timeout (`total_timeout`) is exceeded.
- **FR-010**: System MUST prevent double-reply to the same stdin request by removing the queue entry on first successful delivery.
- **FR-011**: System MUST clean up all pending stdin queue entries when the background shell agent shuts down (normal completion, error, or cancellation).
- **FR-012**: The stdin write operation MUST handle errors gracefully (broken pipe, process exit) and report failure to the agent for appropriate handling.
- **FR-013**: System MUST automatically append a trailing newline to stdin text if missing, to prevent the process from hanging on incomplete input.

### Key Entities

- **Stdin Request**: Represents a pending stdin input request. Key attributes: `request_id` (unique identifier, format `stdin_<proc_id>_<seq>`), `description` (what input is needed), `timeout` (seconds to wait), `context` (recent process output showing the prompt). Lifecycle: created when `INPUT_NEEDED` decision is made, resolved when chat agent responds or timeout expires.
- **Stdin Queue**: An asynchronous queue associated with each `request_id`. Bridges the async boundary between the chat agent and the background shell agent poll loop. Resolves to either a string (user input) or `None` (timeout/cancellation).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can successfully complete interactive shell commands (password prompts, confirmations, auth flows) without the process being killed due to stdin wait — measured by successful completion rate of interactive commands exceeding 90%.
- **SC-002**: Stdin input requests are delivered to the user in chat within 5 seconds of the process entering the stdin-wait state.
- **SC-003**: For simple confirmation prompts (y/N style), the resolution model autonomously handles over 80% of cases without requiring the user to type a response — a brief notification is sent but the process receives stdin input without user action.
- **SC-004**: Stdin timeout recovery prevents indefinite agent hanging — the agent either auto-answers or kills the process within 120% of the specified timeout.
- **SC-005**: Zero cases of stdin input going to the wrong process when multiple stdin requests are active (enforced by unique request_id matching).
- **SC-006**: Users no longer encounter "command was killed because it asked for input" outcomes for interactive commands that receive timely stdin responses.

## Assumptions

- The Docker sandbox environment supports processes with stdin channels (compatible with the existing container launch setup).
- The code model (doubao-seed-2-0-code) has sufficient reasoning capability to distinguish between interactive prompts and normal output, and to make appropriate auto-answer vs. escalate decisions.
- Users are in a QQ group chat context and can respond to stdin requests within the timeout period (5-minute default).
- Sensitive data (passwords, tokens) sent via chat are at the user's own risk — the system does not add special encryption or redaction for stdin content.
- Only one background shell agent runs at a time (enforced by existing system mechanism).
- The chat agent (main LLM) will correctly interpret stdin request notifications and invoke the appropriate response mechanism with appropriate content.
- Default process timeout for overall command execution is 300 seconds, consistent with existing background shell agent behavior.
