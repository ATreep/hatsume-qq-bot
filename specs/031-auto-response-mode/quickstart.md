# Quickstart: Auto Response Mode

**Feature**: Auto Response Mode
**Date**: 2026-07-13

## Enabling

1. Set `AUTO_RESPONSE_GROUP_ID` in `config.py` to the target group QQ ID.
2. Restart the bot. On startup, `refresh_auto_response()` creates the first timer (random 1-3h trigger).

## Verification

- **Immediate test**: Admin sends `/autoresponse` in the target group. The bot should respond with a short (~30 char) topical reply.
- **Passive check**: Wait 1-3 hours after startup; observe the bot sends an auto-response message.
- **Timer status**: (Future: a `/timer autocreate` equivalent for auto_response can be added for status queries.)

## Debugging

- Log messages are tagged `💬 [auto_response]` — grep the bot logs for this prefix.
- Check the timer database: `SELECT * FROM timer_tasks WHERE task_type = 'auto_response';`
- Use `/autoresponse` (admin only) to manually trigger without affecting the scheduled timer.

## Disabling

Delete the auto_response task from the database:
```sql
DELETE FROM timer_tasks WHERE task_type = 'auto_response';
```
Then restart the bot or wait for the next trigger (which will find no task and not reschedule).

To re-enable, restart the bot — `refresh_auto_response()` will create a fresh task.
