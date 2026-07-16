"""Tests for secret key masking gate."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTILS_PATH = ROOT / "hatsume/plugins/hatsume-plugin/utils/security.py"

# Import mask_secret_keys via importlib to avoid package dependency issues
import importlib.util
spec = importlib.util.spec_from_file_location("utils", UTILS_PATH)
utils = importlib.util.module_from_spec(spec)
sys.modules["utils"] = utils
spec.loader.exec_module(utils)
mask_secret_keys = utils.mask_secret_keys


class TestMaskSecretKeys:
    """Tests for mask_secret_keys function."""

    # ---- OpenAI / Anthropic keys ----

    def test_masks_sk_ant_key(self):
        result = mask_secret_keys("My key is sk-ant-api03-abc123def456ghi789jkl012")
        assert "sk-ant-api03-xxx...xxx" in result
        assert "abc123def456ghi789jkl012" not in result

    def test_masks_sk_basic_key(self):
        result = mask_secret_keys("Use sk-abcdefghijklmnopqrstuvwxyz123456 for auth")
        assert "sk-xxx...xxx" in result
        assert "abcdefghijklmnopqrstuvwxyz123456" not in result

    # ---- GitHub tokens ----

    def test_masks_ghp_key(self):
        result = mask_secret_keys("token: ghp_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890")
        assert "ghp_xxx...xxx" in result
        assert "aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" not in result

    def test_masks_gho_key(self):
        result = mask_secret_keys("oauth: gho_1234567890abcdefghijklmnopqrstuv")
        assert "gho_xxx...xxx" in result

    def test_masks_ghu_key(self):
        result = mask_secret_keys("user: ghu_ABCDEFGHIJKLMNOPQRSTUVWXYZ123456")
        assert "ghu_xxx...xxx" in result

    def test_masks_github_pat_key(self):
        result = mask_secret_keys("pat: github_pat_11ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890")
        assert "github_pat_xxx...xxx" in result

    # ---- Volcengine Ark ----

    def test_masks_ark_key(self):
        result = mask_secret_keys("secret: ark-abc123def456ghi789jkl012mno345pqr678")
        assert "ark-xxx...xxx" in result
        assert "abc123def456ghi789jkl012mno345pqr678" not in result

    # ---- Generic access key ----

    def test_masks_ak_key(self):
        result = mask_secret_keys("access: ak-1234567890abcdefghijklmnopqrstuv")
        assert "ak-xxx...xxx" in result

    # ---- Multiple keys in one message ----

    def test_masks_multiple_keys(self):
        result = mask_secret_keys(
            "Keys: sk-ant-api03-aaa111bbb222ccc333ddd444eee555 "
            "and ghp_XXX111YYY222ZZZ333WWW444VVV555UUU666"
        )
        assert "sk-ant-api03-xxx...xxx" in result
        assert "ghp_xxx...xxx" in result
        assert "aaa111bbb222ccc333ddd444eee555" not in result
        assert "XXX111YYY222ZZZ333WWW444VVV555UUU666" not in result

    # ---- No false positives ----

    def test_no_mask_on_normal_text(self):
        text = "Hello! How are you today? Let's discuss the project."
        assert mask_secret_keys(text) == text

    def test_no_mask_on_short_prefix_match(self):
        """Keys shorter than 20 body chars should not be masked (too short to be real keys)."""
        text = "the sk- short one"  # "short" is only 5 chars after sk-
        assert mask_secret_keys(text) == text

    def test_no_mask_on_sk_without_enough_chars(self):
        text = "sk-tooshort"  # only 8 chars after sk-
        assert mask_secret_keys(text) == text

    # ---- Edge cases ----

    def test_empty_string(self):
        assert mask_secret_keys("") == ""

    def test_key_at_start_of_string(self):
        result = mask_secret_keys("sk-ant-api03-abc123def456ghi789jkl012mno345 is my key")
        assert result.startswith("sk-ant-api03-xxx...xxx")

    def test_key_at_end_of_string(self):
        result = mask_secret_keys("My key is ark-abc123def456ghi789jkl012mno345")
        assert result.endswith("ark-xxx...xxx")

    def test_key_with_hyphens_in_body(self):
        """Keys with hyphens in the body (like Anthropic keys)."""
        result = mask_secret_keys("sk-ant-api03-abc-def-ghi-jkl-mno-pqr-stu-vwx-yz0")
        assert "sk-ant-api03-xxx...xxx" in result

    def test_key_with_underscores_in_body(self):
        """GitHub tokens have underscores as prefix separator."""
        result = mask_secret_keys("ghp_abc123def456ghi789jkl012mno345pqr678stu")
        assert "ghp_xxx...xxx" in result

    def test_mixed_content_with_code_blocks(self):
        text = """Here is a config:
        API_KEY=sk-ant-api03-abc123def456ghi789jkl
        export GITHUB_TOKEN=ghp_secret1234567890abcdefgh
        """
        result = mask_secret_keys(text)
        assert "sk-ant-api03-xxx...xxx" in result
        assert "ghp_xxx...xxx" in result
