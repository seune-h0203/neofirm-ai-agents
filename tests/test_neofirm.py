"""
tests/test_neofirm.py — Unit tests for NeoFirm Task 2 pipeline.

Verifies:
1. NeoFirm does NOT invoke `codex exec`
2. NeoFirm DOES invoke the Claude Code CLI wrapper
3. Three independent agent roles are present
4. Three debate rounds are wired up
5. Final synthesis is executed
6. Slide generation is executed
7. Quality review is executed
8. Claude CLI failure is handled correctly
9. NotebookLM behavior is preserved
10. No ANTHROPIC_API_KEY is required in the NeoFirm code
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import run_neofirm as rn
from pathlib import Path as _Path  # already imported above but alias for clarity


# ---------------------------------------------------------------------------
# 1. No codex exec usage
# ---------------------------------------------------------------------------
class TestNoCodexExec:
    def test_run_neofirm_source_has_no_codex_exec(self):
        src = inspect.getsource(rn)
        assert "codex exec" not in src, "run_neofirm.py must not contain 'codex exec'"

    def test_run_neofirm_source_has_no_codex_import(self):
        src = inspect.getsource(rn)
        assert "import codex" not in src, "run_neofirm.py must not import codex"

    def test_no_codex_exec_in_claude_function(self):
        src = inspect.getsource(rn.claude)
        assert "codex" not in src.lower()


# ---------------------------------------------------------------------------
# 2. Claude Code CLI wrapper present and correct
# ---------------------------------------------------------------------------
class TestClaudeWrapper:
    def test_claude_function_exists(self):
        assert callable(rn.claude)

    def test_claude_cmd_uses_claude_or_npx(self):
        cmd = rn.CLAUDE_BASE
        base = Path(cmd[0]).name.lower().replace(".cmd", "").replace(".exe", "")
        assert base in ("claude", "npx"), (
            f"CLAUDE_BASE[0] must resolve to 'claude' or 'npx', got {cmd[0]!r}"
        )
        if base == "npx":
            assert "@anthropic-ai/claude-code" in " ".join(cmd)

    def test_claude_uses_print_flag(self):
        src = inspect.getsource(rn.claude)
        assert "--print" in src

    def test_claude_uses_no_session_persistence(self):
        src = inspect.getsource(rn.claude)
        assert "--no-session-persistence" in src

    def test_claude_uses_output_format_text(self):
        src = inspect.getsource(rn.claude)
        assert "output-format" in src and "text" in src

    def test_claude_success_path(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Mock Claude response"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = rn.claude("hello", label="test")
        assert result == "Mock Claude response"

    def test_claude_failure_raises(self):
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "some error"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="Claude CLI exited"):
                rn.claude("hello", label="test_fail")

    def test_claude_empty_output_raises(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="empty output"):
                rn.claude("hello", label="test_empty")

    def test_claude_timeout_raises(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 5)):
            with pytest.raises(RuntimeError, match="timed out"):
                rn.claude("hello", timeout=5, label="test_timeout")


# ---------------------------------------------------------------------------
# 3. Three independent agent roles
# ---------------------------------------------------------------------------
class TestAgentRoles:
    def test_three_agent_roles_defined(self):
        assert set(rn.AGENT_ROLES.keys()) == {"market", "execution", "skeptic"}

    def test_market_agent_has_role_text(self):
        assert len(rn.AGENT_ROLES["market"]) > 20

    def test_execution_agent_has_role_text(self):
        assert len(rn.AGENT_ROLES["execution"]) > 20

    def test_skeptic_agent_has_role_text(self):
        assert len(rn.AGENT_ROLES["skeptic"]) > 20

    def test_agent_roles_are_distinct(self):
        roles = list(rn.AGENT_ROLES.values())
        assert roles[0] != roles[1]
        assert roles[1] != roles[2]
        assert roles[0] != roles[2]

    def test_round1_calls_all_three_agents(self):
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        call_labels = []

        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            call_labels.append(label)
            return f"Response from {label}"

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            with patch.object(rn, "claude", side_effect=fake_claude):
                result = rn.run_debate_round1(run_dir, {"k": "v"}, "test_sector")

        assert "round1_market" in call_labels
        assert "round1_execution" in call_labels
        assert "round1_skeptic" in call_labels
        assert set(result.keys()) == {"market", "execution", "skeptic"}

    def test_round2_calls_all_three_agents(self):
        mock_r1 = {
            "market": "market pos",
            "execution": "exec pos",
            "skeptic": "skeptic pos",
        }
        call_labels = []

        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            call_labels.append(label)
            return f"Response from {label}"

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rn, "claude", side_effect=fake_claude):
                result = rn.run_debate_round2(Path(tmp), mock_r1, "test_sector")

        assert "round2_market" in call_labels
        assert "round2_execution" in call_labels
        assert "round2_skeptic" in call_labels

    def test_round3_calls_all_three_agents(self):
        mock_r1 = {"market": "r1m", "execution": "r1e", "skeptic": "r1s"}
        mock_r2 = {"market": "r2m", "execution": "r2e", "skeptic": "r2s"}
        call_labels = []

        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            call_labels.append(label)
            return f"Response from {label}"

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rn, "claude", side_effect=fake_claude):
                result = rn.run_debate_round3(Path(tmp), mock_r1, mock_r2, "test_sector")

        assert "round3_market" in call_labels
        assert "round3_execution" in call_labels
        assert "round3_skeptic" in call_labels


# ---------------------------------------------------------------------------
# 4. Three rounds are distinct functions
# ---------------------------------------------------------------------------
class TestDebateRounds:
    def test_round1_function_exists(self):
        assert callable(rn.run_debate_round1)

    def test_round2_function_exists(self):
        assert callable(rn.run_debate_round2)

    def test_round3_function_exists(self):
        assert callable(rn.run_debate_round3)

    def test_rounds_are_different_functions(self):
        assert rn.run_debate_round1 is not rn.run_debate_round2
        assert rn.run_debate_round2 is not rn.run_debate_round3

    def test_debate_log_saved(self):
        r1 = {"market": "m1", "execution": "e1", "skeptic": "s1"}
        r2 = {"market": "m2", "execution": "e2", "skeptic": "s2"}
        r3 = {"market": "m3", "execution": "e3", "skeptic": "s3"}
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            path = rn.save_debate_log(run_dir, "IT", r1, r2, r3)
            assert path.exists()
            content = path.read_text(encoding="utf-8")
            assert "Round 1" in content
            assert "Round 2" in content
            assert "Round 3" in content
            assert "MARKET" in content
            assert "EXECUTION" in content
            assert "SKEPTIC" in content


# ---------------------------------------------------------------------------
# 5. Synthesis function
# ---------------------------------------------------------------------------
class TestSynthesis:
    def test_synthesis_function_exists(self):
        assert callable(rn.run_synthesis)

    def test_synthesis_calls_claude_with_label(self):
        call_labels = []

        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            call_labels.append(label)
            return "Final synthesis response"

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rn, "claude", side_effect=fake_claude):
                result = rn.run_synthesis(
                    Path(tmp), "IT",
                    {"market": "m", "execution": "e", "skeptic": "s"},
                    {"market": "m2", "execution": "e2", "skeptic": "s2"},
                    {"market": "m3", "execution": "e3", "skeptic": "s3"},
                    {"value_chain": "vc"},
                )
            assert "synthesis" in call_labels
            assert result == "Final synthesis response"
            assert (Path(tmp) / "synthesis.md").exists()


# ---------------------------------------------------------------------------
# 6. Slide generation
# ---------------------------------------------------------------------------
class TestSlideGeneration:
    def test_slide_generation_function_exists(self):
        assert callable(rn.run_slide_generation)

    def test_slide_generation_calls_claude(self):
        valid_json = json.dumps({
            "title": "Test",
            "sector": "IT",
            "slides": [
                {"slide_number": 1, "title": "Slide 1", "key_points": ["pt1"]},
            ],
        })

        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            return valid_json

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rn, "claude", side_effect=fake_claude):
                result = rn.run_slide_generation(
                    Path(tmp), "IT", "synthesis text", {"k": "v"}, {"market": "m"}
                )
            assert "slides" in result
            assert (Path(tmp) / "slides.json").exists()

    def test_slide_generation_invalid_json_raises(self):
        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            return "not json at all"

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rn, "claude", side_effect=fake_claude):
                with pytest.raises(RuntimeError, match="invalid JSON"):
                    rn.run_slide_generation(
                        Path(tmp), "IT", "synthesis", {"k": "v"}, {"market": "m"}
                    )


# ---------------------------------------------------------------------------
# 7. Quality review
# ---------------------------------------------------------------------------
class TestQualityReview:
    def test_review_function_exists(self):
        assert callable(rn.run_quality_review)

    def test_review_pass(self):
        valid_review = json.dumps({
            "required_content_present": True,
            "claims_grounded": True,
            "debate_reflected": True,
            "slide_count_ok": True,
            "logical_consistency": True,
            "overall_pass": True,
            "issues": [],
            "suggestions": [],
        })

        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            return valid_review

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rn, "claude", side_effect=fake_claude):
                review = rn.run_quality_review(
                    Path(tmp), "IT", {"slides": []}, True
                )
            assert review["overall_pass"] is True

    def test_review_fail_returns_dict_with_issues(self):
        fail_review = json.dumps({
            "overall_pass": False,
            "issues": ["Missing debate summary"],
            "suggestions": ["Add agent debate slide"],
        })

        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            return fail_review

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rn, "claude", side_effect=fake_claude):
                review = rn.run_quality_review(Path(tmp), "IT", {"slides": []})
            assert review["overall_pass"] is False
            assert len(review["issues"]) > 0


# ---------------------------------------------------------------------------
# 8. Failure handling
# ---------------------------------------------------------------------------
class TestFailureHandling:
    def test_claude_failure_does_not_silently_continue(self):
        def fail_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            raise RuntimeError("Claude CLI exited 1")

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(rn, "claude", side_effect=fail_claude):
                with pytest.raises(RuntimeError):
                    rn.run_synthesis(
                        Path(tmp), "IT",
                        {"market": "m", "execution": "e", "skeptic": "s"},
                        {"market": "m2", "execution": "e2", "skeptic": "s2"},
                        {"market": "m3", "execution": "e3", "skeptic": "s3"},
                        {},
                    )


# ---------------------------------------------------------------------------
# 9. NotebookLM behavior preserved
# ---------------------------------------------------------------------------
class TestNotebookLM:
    def test_nlm_query_function_exists(self):
        assert callable(rn.nlm_query)

    def test_nlm_fallback_to_claude_when_nlm_none(self):
        claude_calls = []

        def fake_claude(prompt, system_role="", label="", run_dir=None, timeout=180):
            claude_calls.append(label)
            return "claude fallback response"

        original_nlm = rn.NLM
        try:
            rn.NLM = None
            with patch.object(rn, "claude", side_effect=fake_claude):
                result = rn.nlm_query("test question")
            assert result == "claude fallback response"
            assert any("fallback" in l for l in claude_calls)
        finally:
            rn.NLM = original_nlm

    def test_notebook_id_set(self):
        assert rn.NOTEBOOK_ID and len(rn.NOTEBOOK_ID) > 10


# ---------------------------------------------------------------------------
# 10. No ANTHROPIC_API_KEY required
# ---------------------------------------------------------------------------
class TestNoApiKeyRequired:
    def test_anthropic_api_key_not_accessed_in_source(self):
        """Check that ANTHROPIC_API_KEY is not read from os.environ in the pipeline."""
        src = inspect.getsource(rn)
        # The key must not be fetched from the environment
        assert 'os.environ.get("ANTHROPIC_API_KEY"' not in src, (
            "run_neofirm.py must not read ANTHROPIC_API_KEY from os.environ"
        )
        assert "os.environ['ANTHROPIC_API_KEY']" not in src
        assert 'os.getenv("ANTHROPIC_API_KEY"' not in src

    def test_no_direct_anthropic_api_calls(self):
        src = inspect.getsource(rn)
        assert "api.anthropic.com" not in src, (
            "run_neofirm.py must not call Anthropic API directly"
        )
        assert "from anthropic import" not in src, (
            "run_neofirm.py must not import the anthropic SDK"
        )
        assert "import anthropic" not in src, (
            "run_neofirm.py must not import the anthropic SDK"
        )

    def test_pipeline_does_not_require_env_var(self):
        """Pipeline code must not fail at import time due to missing ANTHROPIC_API_KEY."""
        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            importlib.reload(rn)  # Re-import without the env var
        except Exception as exc:
            pytest.fail(f"run_neofirm failed to import without ANTHROPIC_API_KEY: {exc}")
        finally:
            if saved:
                os.environ["ANTHROPIC_API_KEY"] = saved
