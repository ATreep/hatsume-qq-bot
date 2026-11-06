"""Producer provenance contracts without booting NoneBot or graph consumers."""

import importlib.util
from datetime import timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1] / "hatsume/plugins/hatsume-plugin"
PACKAGE = "runtime_event_producers"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class ProducerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        modules = {}
        for suffix in ("", ".timer", ".hooks", ".graph", ".utils"):
            module = ModuleType(PACKAGE + suffix)
            module.__path__ = [str(ROOT / suffix.lstrip("."))]
            modules[PACKAGE + suffix] = module
        self.inject_timer = Mock()
        self.registry = SimpleNamespace(
            routed_group_ids=lambda: [123],
            get_existing=lambda group_id: None,
        )
        modules[PACKAGE + ".graph.nodes"] = SimpleNamespace(
            inject_timer=self.inject_timer
        )
        modules[PACKAGE + ".group_runtime"] = SimpleNamespace(
            group_runtime_registry=self.registry
        )
        modules[PACKAGE + ".state"] = SimpleNamespace(
            peer_session_id=lambda group, user: f"{group}:{user}"
        )
        modules[PACKAGE + ".utils.security"] = SimpleNamespace(
            mask_secret_keys=lambda value: value
        )
        modules[PACKAGE + ".config"] = SimpleNamespace(
            AUTO_RESPONSE_GROUP_BLACKLIST=set(),
            AUTO_RESPONSE_MAX_INTERVAL_MINUTES=60,
            AUTO_RESPONSE_MIN_INTERVAL_MINUTES=30,
            AUTO_RESPONSE_QUIET_END_HOUR=8,
            AUTO_RESPONSE_QUIET_START_HOUR=0,
            TIMER_TOLERANCE_MINUTES=5,
            HOOKS_DIR=ROOT,
        )
        modules[PACKAGE + ".timer.schedule"] = SimpleNamespace(
            SHANGHAI=timezone.utc,
            occurrence_at_index=lambda task, point, index: 1000.0 + index,
        )
        modules[PACKAGE + ".timer.store"] = SimpleNamespace(TimerStore=object)
        modules[PACKAGE + ".hooks.store"] = SimpleNamespace(
            HookStore=object,
            HOOK_MAX_TIMEOUT_SECONDS=300,
            HOOK_TRIGGER_HEARTBEAT="heartbeat",
            HOOK_TRIGGER_MESSAGE="message_match",
            ANY_MATCH_USER_ID=0,
        )
        modules["nonebot"] = SimpleNamespace(
            require=lambda name: SimpleNamespace(scheduler=Mock())
        )
        for kind, attr in (
            ("calendarinterval", "CalendarIntervalTrigger"),
            ("cron", "CronTrigger"),
            ("date", "DateTrigger"),
            ("interval", "IntervalTrigger"),
        ):
            modules[f"apscheduler.triggers.{kind}"] = SimpleNamespace(**{attr: Mock()})
        modules["apscheduler.events"] = SimpleNamespace(
            EVENT_JOB_MISSED=1, EVENT_JOB_SUBMITTED=2
        )
        patcher = patch.dict(sys.modules, modules)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.timer = load(PACKAGE + ".timer.executor", ROOT / "timer/executor.py")
        self.heartbeat = load(PACKAGE + ".hooks.executor", ROOT / "hooks/executor.py")
        self.message = load(
            PACKAGE + ".hooks.message_trigger", ROOT / "hooks/message_trigger.py"
        )

    def timer_store(self, task_type="normal"):
        self.task = dict(
            id=7,
            group_id=123,
            user_id=0,
            prompt="notify 初芽",
            task_type=task_type,
            schedule_type="at",
        )
        self.point = dict(
            id=9, task_id=7, processed_occurrences=0, planned_occurrences=2
        )
        return SimpleNamespace(
            get_task=lambda task_id: self.task,
            get_point=lambda point_id: self.point,
            mark_occurrence_processed=Mock(return_value=True),
        )

    async def test_timer_occurrence_provenance_and_stable_key(self):
        store = self.timer_store()
        for scheduled_at in (1000.0, 1000.0, 1001.0):
            await self.timer._execute_point(9, store, scheduled_at=scheduled_at)
        first, replay, later = [
            call.kwargs for call in self.inject_timer.call_args_list
        ]
        self.assertEqual(
            first["event_data"],
            dict(
                source="timer",
                task_id=7,
                point_id=9,
                occurrence=1000.0,
                scheduled_at=1000.0,
                occurrence_index=0,
                task_type="normal",
                schedule_type="at",
            ),
        )
        self.assertEqual(first["event_key"], replay["event_key"])
        self.assertNotEqual(first["event_key"], later["event_key"])
        store.mark_occurrence_processed.assert_called_with(9, 1001.0)

    async def test_timer_injection_failure_still_advances(self):
        store = self.timer_store()
        self.inject_timer.side_effect = RuntimeError("consumer unavailable")
        await self.timer._execute_point(9, store, scheduled_at=1000.0)
        store.mark_occurrence_processed.assert_called_once_with(9, 1000.0)

    async def test_auto_response_source_and_existing_synchronization(self):
        store = self.timer_store("auto_response")
        with (
            patch.object(
                self.timer, "_get_auto_response_state", return_value=(True, True)
            ),
            patch.object(
                self.timer, "_is_auto_response_quiet_time", return_value=False
            ),
            patch.object(self.timer, "_synchronize_current_auto_response") as sync,
        ):
            await self.timer._execute_point(9, store, scheduled_at=1000.0)
        event = self.inject_timer.call_args.kwargs
        self.assertEqual(event["event_data"]["source"], "auto_response")
        self.assertEqual(event["event_data"]["task_type"], "auto_response")
        self.assertEqual(event["event_data"]["point_id"], 9)
        self.assertEqual(event["event_data"]["occurrence"], 1000.0)
        self.assertEqual(event["user_id"], 0)
        sync.assert_called_once_with(store, 123)

    async def test_auto_response_preserves_skip_gates(self):
        for reason in ("quiet", "active", "processed", "unroutable", "inactive"):
            with self.subTest(reason=reason):
                store = self.timer_store("auto_response")
                store.mark_occurrence_processed.return_value = reason != "processed"
                self.inject_timer.reset_mock()
                runtime = SimpleNamespace(
                    conversation=SimpleNamespace(is_chatting=True)
                )
                with (
                    patch.object(
                        self.timer,
                        "_get_auto_response_state",
                        return_value=(reason != "inactive", reason != "unroutable"),
                    ),
                    patch.object(
                        self.timer,
                        "_is_auto_response_quiet_time",
                        return_value=reason == "quiet",
                    ),
                    patch.object(self.timer, "_synchronize_current_auto_response"),
                    patch.object(self.timer, "cancel_point_job"),
                    patch.object(
                        self.registry,
                        "get_existing",
                        return_value=runtime if reason == "active" else None,
                    ),
                ):
                    await self.timer._execute_point(9, store, scheduled_at=1000.0)
                self.inject_timer.assert_not_called()

    def hook_store(self):
        self.record = dict(
            id=8,
            group_id=123,
            enabled=True,
            trigger_type="heartbeat",
            name="watch",
            script_path="/fixture/watch",
            timeout_seconds=30,
            prompt="notify 初芽",
            updated_at=1,
            notified_user_ids=[456],
        )
        return SimpleNamespace(
            get_hook=lambda hook_id: self.record,
            record_failure=Mock(),
            record_success=Mock(),
        )

    async def test_heartbeat_provenance_and_notifications(self):
        store = self.hook_store()
        inject = Mock()
        result = self.heartbeat.HookScriptResult(10, "event", "", None)
        with (
            patch.object(
                self.heartbeat,
                "validate_hook_script_path",
                return_value=Path("/fixture/watch"),
            ),
            patch.object(
                self.heartbeat, "run_hook_script", new=AsyncMock(return_value=result)
            ),
            patch.object(self.heartbeat.time, "time", return_value=2000.0),
        ):
            await self.heartbeat.execute_hook(8, store, inject_fn=inject)
        event = inject.call_args.kwargs
        self.assertEqual(event["event_key"], "hook:123:8:heartbeat:2000.0")
        self.assertEqual(
            event["event_data"],
            dict(hook_id=8, trigger_type="heartbeat", run_at=2000.0, fired_at=2000.0),
        )
        self.assertEqual(event["notified_user_ids"], [456])
        store.record_success.assert_called_once_with(8, 10, 2000.0)

    async def test_heartbeat_no_event_failure_and_changed_hook_do_not_inject(self):
        for reason in ("empty", "failure", "changed"):
            store = self.hook_store()
            inject = Mock()

            async def execute(*args, **kwargs):
                if reason == "changed":
                    self.record = {**self.record, "updated_at": 2}
                return self.heartbeat.HookScriptResult(
                    0 if reason == "empty" else 10,
                    "event",
                    "",
                    "bad" if reason == "failure" else None,
                )

            with (
                patch.object(
                    self.heartbeat,
                    "validate_hook_script_path",
                    return_value=Path("/fixture/watch"),
                ),
                patch.object(self.heartbeat, "run_hook_script", new=execute),
            ):
                await self.heartbeat.execute_hook(8, store, inject_fn=inject)
            inject.assert_not_called()

    def message_store(self):
        records = [
            dict(
                id=idx,
                name=f"hook-{idx}",
                enabled=True,
                trigger_type="message_match",
                match_pattern="hello",
                match_user_id=0,
                prompt="notify 初芽",
            )
            for idx in (1, 2)
        ]
        return SimpleNamespace(
            list_enabled_message_hooks=lambda group: records,
            record_failure=Mock(),
            record_trigger=Mock(),
        )

    async def test_message_match_provenance_distinguishes_hooks_and_messages(self):
        store = self.message_store()
        inject = Mock()
        for message_id in (55, 55, 56):
            await self.message.dispatch_message_hooks(
                group_id=123,
                user_id=456,
                text="hello",
                store=store,
                inject_fn=inject,
                now=3000.0,
                message_id=message_id,
            )
        events = [call.kwargs for call in inject.call_args_list]
        self.assertEqual(
            events[0]["event_data"],
            dict(
                hook_id=1,
                trigger_type="message_match",
                fired_at=3000.0,
                message_id=55,
                user_id=456,
            ),
        )
        self.assertNotEqual(events[0]["event_key"], events[1]["event_key"])
        self.assertEqual(events[0]["event_key"], events[2]["event_key"])
        self.assertNotEqual(events[0]["event_key"], events[4]["event_key"])

    async def test_message_without_id_has_distinct_delivery_keys(self):
        store = self.message_store()
        inject = Mock()
        for _ in range(2):
            await self.message.dispatch_message_hooks(
                group_id=123,
                user_id=456,
                text="hello",
                store=store,
                inject_fn=inject,
                now=3000.0,
            )
        events = [call.kwargs for call in inject.call_args_list]
        self.assertIsNone(events[0]["event_data"]["message_id"])
        self.assertNotEqual(events[0]["event_key"], events[2]["event_key"])

    async def test_message_failure_does_not_block_other_hooks(self):
        store = self.message_store()
        inject = Mock(side_effect=[RuntimeError("consumer unavailable"), None])
        fired = await self.message.dispatch_message_hooks(
            group_id=123,
            user_id=456,
            text="hello",
            store=store,
            inject_fn=inject,
            now=3000.0,
            message_id=55,
        )
        self.assertEqual(fired, ["hook-2"])
        store.record_failure.assert_called_once()
        store.record_trigger.assert_called_once_with(2, 3000.0)


if __name__ == "__main__":
    unittest.main()
