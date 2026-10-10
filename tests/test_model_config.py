import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from model_provider_support import config


@pytest.fixture
def store(tmp_path):
    result = config.ModelConfigStore(tmp_path)
    result.save_provider(
        "primary",
        base_url="https://example.test/custom/v3",
        supported_apis=["openai_chat_completions", "openai_responses"],
        api_key="private-test-key",
        create=True,
    )
    result.use_model("advance", "primary", "first", "openai_responses")
    return result


def test_switch_survives_new_instance_and_resets_old_model_options(store):
    store.set_option("advance", "reasoning_effort", "high")
    old = store.resolve("advance")
    store.use_model("advance", "primary", "second", "openai_chat_completions")
    current = config.ModelConfigStore(store.root).resolve("advance")
    assert (
        current["model"],
        current["api"],
        current["base_url"],
        current["options"],
    ) == ("second", "openai_chat_completions", "https://example.test/custom/v3", {})
    assert old["model"] == "first" and old["options"] == {"reasoning_effort": "high"}


def test_secret_file_permissions_and_redacted_snapshot(store):
    for path in (store.providers_path, store.models_path):
        assert path.stat().st_mode & 0o777 == 0o600
    providers, _ = store.snapshot()
    assert "private-test-key" not in repr(providers)
    assert providers["primary"]["key_configured"] is True


@pytest.mark.parametrize(
    "operation",
    [
        lambda s: s.use_model("advance", "primary", "x", "google_genai"),
        lambda s: s.use_model("embedding", "primary", "x", "openai_responses"),
        lambda s: s.set_option("advance", "extra_body", {}),
        lambda s: s.set_option("advance", "temperature", True),
        lambda s: s.set_option("advance", "max_tokens", 0),
        lambda s: s.save_provider("primary", supported_apis=["google_genai"]),
        lambda s: s.save_provider(
            "primary", base_url="https://user:private-test-key@example.test"
        ),
        lambda s: s.remove_provider("primary"),
    ],
)
def test_invalid_mutations_preserve_both_files(store, operation):
    before = (store.providers_path.read_bytes(), store.models_path.read_bytes())
    with pytest.raises(config.ModelConfigError) as error:
        operation(store)
    assert "private-test-key" not in str(error.value)
    assert (store.providers_path.read_bytes(), store.models_path.read_bytes()) == before


def test_syntax_errors_do_not_echo_credentials(store):
    store.providers_path.write_text("providers: [private-test-key\n")
    with pytest.raises(config.ModelConfigError) as error:
        store.resolve("advance")
    assert "private-test-key" not in str(error.value)


def test_missing_file_does_not_reset_surviving_config(store):
    before = store.providers_path.read_bytes()
    store.models_path.unlink()
    with pytest.raises(config.ModelConfigError, match="restore"):
        store.snapshot()
    assert store.providers_path.read_bytes() == before
    assert not store.models_path.exists()


def test_environment_keys_do_not_override_or_refill_yaml(store):
    store.save_provider(
        "ds",
        base_url="https://example.test/v1",
        supported_apis=["openai_chat_completions"],
        api_key="",
        create=True,
    )
    store.use_model("lite", "ds", "a-model")
    with patch.dict(os.environ, {"DS_API_KEY": "legacy-env-secret"}):
        with pytest.raises(config.ModelConfigError, match="no API key"):
            store.resolve("lite")
        assert "legacy-env-secret" not in store.providers_path.read_text()


def test_provider_deletion_after_reassignment(store):
    store.save_provider(
        "next",
        base_url="https://next.test/v1",
        supported_apis=["openai_chat_completions"],
        api_key="next-key",
        create=True,
    )
    store.use_model("advance", "next", "next-model")
    store.remove_provider("primary")
    assert list(store.snapshot()[0]) == ["next"]


def test_concurrent_updates_do_not_lose_independent_options(store):
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(
            pool.map(
                lambda item: store.set_option("advance", *item),
                [("temperature", 0.4), ("max_tokens", 128)],
            )
        )
    assert store.resolve("advance")["options"] == {
        "temperature": 0.4,
        "max_tokens": 128,
    }


def test_google_options_are_native_and_mutually_exclusive(store):
    store.save_provider(
        "google",
        base_url="https://generativelanguage.googleapis.com",
        supported_apis=["google_genai"],
        api_key="fake-google",
        create=True,
    )
    store.use_model("vision", "google", "gemini-test")
    store.set_option("vision", "thinking_budget", 0)
    with pytest.raises(config.ModelConfigError):
        store.set_option("vision", "thinking_level", "low")
    store.set_option("vision", "thinking_budget", None)
    store.set_option("vision", "thinking_level", "low")
    assert store.resolve("vision")["options"] == {"thinking_level": "low"}


def test_ambiguous_api_must_be_explicit_on_new_provider(store):
    with pytest.raises(config.ModelConfigError, match="--api"):
        store.use_model("coding", "primary", "code-model")
    store.use_model("coding", "primary", "code-model", "openai_responses")
    assert store.resolve("coding")["api"] == "openai_responses"
