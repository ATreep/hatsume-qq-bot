# Quickstart: Timer Module

**Feature**: 008-timer-module | **Date**: 2026-06-07

## Overview

The timer module allows QQ group members to schedule bot actions via natural language chat or slash commands. Tasks persist across restarts.

## Usage

### Creating a Timer (Natural Language)

In any group chat, tell the bot what to remind you about:

```
@初芽 明早8点提醒我开会
@初芽 每天早上7点叫我起床
@初芽 3小时后提醒我收衣服
```

The bot will confirm with the task ID and trigger times.

### Creating a Timer (Command)

```
/timer update <id> <prompt> @ <time1>, <time2>, ...
```

Example:
```
/timer update 1 提醒吃药 @ 2026-06-09T08:00:00+08:00, 2026-06-10T08:00:00+08:00
```

### Managing Timers

```
/timer list              # List all timers in this group
/timer delete <id>       # Delete a specific timer
/timer update <id> ...   # Update a timer's prompt and times
/timer                   # Show help (all sub-commands)
```

### Natural Language Management

You can also manage timers through conversation:

```
"帮我看看我设了哪些定时任务"     → bot lists all
"把我那个开会的定时取消了"       → bot deletes it
```

## What Happens When a Timer Fires

1. Bot looks up the creator's current group nickname
2. If the user has left the group → timer is silently cleaned up
3. Bot fetches the last 5 messages in the group for context
4. An independent AI agent executes the task prompt
5. The result is sent to the group @-mentioning the creator

## Constraints

- Maximum 30 days in the future
- `create_timer` allows at most 10 unique triggers in any rolling 24-hour window; `/timer update` is not subject to this frequency limit
- Prompt text max 500 characters
- Timer chat_agent runs independently — won't interrupt ongoing conversations

## Debug API

```
GET /debug/api/timers
```

Returns all timer tasks with trigger statuses for the debug panel.

## Startup Behavior

On bot restart:
- All pending future timers are reloaded
- Timers missed within 5 minutes are executed immediately
- Timers missed beyond 5 minutes are marked as expired
