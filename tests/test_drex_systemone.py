"""Contract tests for the TypeSafe-compatible Drex System One request."""

import os
import runpy
import sys
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "hatsume/plugins/hatsume-plugin/graph/nodes.py"
)


def _load_request_helpers():
    """Load the two dependency-light helpers without booting the plugin."""
    import ast

    tree = ast.parse(SOURCE.read_text())
    names = {"_build_systemone_body", "_post_systemone"}
    code = compile(
        ast.Module(
            body=[
                node
                for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name in names
            ],
            type_ignores=[],
        ),
        str(SOURCE),
        "exec",
    )
    namespace = {"Any": Any, "Mapping": Mapping}
    exec(code, namespace)  # noqa: S102
    return namespace


class DrexSystemOneTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.namespace = _load_request_helpers()
        self.post = AsyncMock(return_value={"answers": {}})
        self.model = SimpleNamespace(
            model_name="drex-latest",
            root_async_client=SimpleNamespace(post=self.post),
        )

    def load_config(self, env):
        dotenv_stub = SimpleNamespace(load_dotenv=lambda _path: None)
        with patch.dict(os.environ, env, clear=True), patch.dict(
            sys.modules, {"dotenv": dotenv_stub}
        ):
            return runpy.run_path(
                str(SOURCE.parent.parent / "config.py"),
                run_name="drex_config_test",
            )

    def test_model_credentials_are_not_loaded_from_environment(self):
        config = self.load_config(
            {
                "DREX_API_KEY": "legacy-secret",
                "TYPESAFE_API_KEY": "typesafe-secret",
                "TYPESAFE_BASE_URL": "https://drex.nace.ai/",
                "TYPESAFE_DEFAULT_MODEL": "drex-latest",
            }
        )
        self.assertNotIn("TYPESAFE_API_KEY", config)
        self.assertNotIn("TYPESAFE_BASE_URL", config)
        self.assertNotIn("TYPESAFE_DEFAULT_MODEL", config)

    def questions(self):
        return {
            "is_urgent": {
                "type": "noul",
                "instructions": "Does this convey urgency?",
                "criteria": {"true": "Time-sensitive", "false": "Not urgent"},
            },
            "department": {
                "type": "choice",
                "instructions": "Which team should handle this?",
                "criteria": {
                    "billing": "Payments and refunds",
                    "technical": "Bugs and outages",
                },
            },
            "frustration": {
                "type": "score",
                "instructions": "How frustrated is the customer?",
                "criteria": ["Calm", "Frustrated", "Very angry"],
            },
        }

    def test_question_contract_keeps_noul_choice_and_score_shapes(self):
        questions = self.questions()
        body = self.namespace["_build_systemone_body"](
            "drex-latest", "customer state", questions
        )

        self.assertEqual(body["model"], "drex-latest")
        self.assertEqual(body["state"], "customer state")
        self.assertEqual(set(body["questions"]), set(questions))
        self.assertEqual(body["questions"]["is_urgent"]["type"], "noul")
        self.assertEqual(body["questions"]["department"]["type"], "choice")
        self.assertEqual(body["questions"]["frustration"]["type"], "score")
        self.assertEqual(
            body["questions"]["frustration"]["criteria"],
            ["Calm", "Frustrated", "Very angry"],
        )

    async def test_multiple_questions_use_one_forward_pass(self):
        await self.namespace["_post_systemone"](
            self.model, {"message": "customer state"}, self.questions()
        )

