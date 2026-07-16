# Quickstart: Background Shell Stdin Injection

## What This Feature Does

When the bot runs an interactive shell command (e.g., `sudo apt install nginx`) in the background, the process can now receive stdin input instead of being killed when it asks for a password or confirmation.

## How to Use

1. **Ask the bot to run an interactive command**: `@hatsume sudo apt install nginx`
2. **Bot detects stdin need**: The bot sends a chat notification showing what input is needed (e.g., "进程等待 sudo 密码")
3. **Provide input**: Reply with the required information (password, token, confirmation)
4. **Bot continues execution**: The process receives the input and continues running

## Key Behaviors

- **Simple confirmations** (`[y/N]`): The bot auto-answers with the safe default (`N`) within seconds — no user input required, but a brief notification is shown
- **Passwords/tokens**: The bot waits up to 5 minutes (default) for you to provide the input
- **Timeouts**: If you don't respond in time, the bot either auto-answers (for confirmations) or kills the process (for passwords where guessing would be unsafe)

## Technical Notes

- Only one background shell process runs at a time
- stdin input is UTF-8 encoded
- A trailing newline is automatically appended if missing
- Sensitive data (passwords) sent in chat is at your own risk
