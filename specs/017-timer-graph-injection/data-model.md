# Data Model: Timer Graph Injection

**Feature**: 017-timer-graph-injection
**Date**: 2026-06-28

## Overview

No database schema changes. The existing `timer_triggers` and `timer_tasks` tables remain unchanged. The only addition is a new in-memory message format for timer notifications.

## Existing Entities (Unchanged)

### timer_tasks

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER PK | Auto-increment task ID |
| group_id | INTEGER | QQ group ID |
| user_id | INTEGER | QQ user ID of creator |
| prompt | TEXT | Timer prompt text (max 500 chars) |
| created_at | REAL | Unix timestamp |
| updated_at | REAL | Unix timestamp |

### timer_triggers

| Field | Type | Description |
|-------|------|-------------|
| id | INTEGER PK | Auto-increment trigger ID |
| task_id | INTEGER FK | References timer_tasks(id) ON DELETE CASCADE |
| trigger_at | REAL | Unix timestamp when trigger fires |
| fired | INTEGER | 0 = pending, 1 = fired |
| job_id | TEXT | APScheduler job ID (format: `timer_{id}`) |

## New In-Memory Entity

### Timer Notification Message

A specially marked message injected into `ConversationState.human_queue`. Not persisted — exists only during the conversation lifecycle.

| Component | Format | Example |
|-----------|--------|---------|
| Mark prefix | `__timer__:{user_id}` | `__timer__:123456` |
| System instruction | `(SYSTEM) ...` | `(SYSTEM) 定时任务已触发...` |
| Context block | System prompt + recent chat | `系统上下文：...` |
| Task prompt | User's timer prompt | `定时任务内容：提醒喝水` |

**Detection**: `detect_timer_notification` scans `state["messages"][-1].content` for the `__timer__:` prefix, extracts user_id via `split(":", 1)`.

**State transitions**: Message is created → appended to human_queue → picked up by human_node → processed by ai_node → detection extracts user_id → response sent with @-mention.

## Entity Relationships

```
timer_tasks (1) ──< (N) timer_triggers
     │
     │ (unchanged — trigger fires, mark fired)
     │
     ▼
_inject_timer_to_graph()
     │
     │ (new — builds Timer Notification Message)
     ▼
ConversationState.human_queue
     │
     ▼
LangGraph (human_node → detect_node → ai_node)
```
