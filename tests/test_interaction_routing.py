"""tests/test_interaction_routing.py — Verification of the Agent Interaction Model & Router."""

import pytest
from harness.contracts import AgentPhase, RequestType, TaskType
from harness.issue_parser import IssueParser, classify_user_request
from harness.orchestrator import Orchestrator
from harness.config import load_config


def test_conversational_greetings_routing():
    for greeting in ["hi", "hello", "hey", "Hi Zenith", "Hello there", "good morning"]:
        res = classify_user_request(greeting)
        assert res.request_type == RequestType.CONVERSATIONAL_REQUEST, f"Failed for {greeting}"
        assert "Hello. I'm Zenith" in res.direct_response


def test_conversational_capability_routing():
    for q in ["what can you do?", "who are you?", "what is zenith?", "tell me about yourself", "how do you work?"]:
        res = classify_user_request(q)
        assert res.request_type == RequestType.CONVERSATIONAL_REQUEST, f"Failed for {q}"
        assert "I can inspect repositories, investigate code issues" in res.direct_response


def test_code_tasks_routing():
    code_tasks = [
        "Fix the session timeout after login.",
        "Find why authentication returns 401.",
        "Fix the failing test.",
        "Inspect the session handling bug.",
        "Recover the broken implementation.",
        "Fix KeyError when calling calculate_discount() with missing customer tier",
        "Refactor auth/session.py to use redis client",
    ]
    for task in code_tasks:
        res = classify_user_request(task)
        assert res.request_type == RequestType.CODE_TASK, f"Failed for {task}"


def test_orchestrator_conversational_shortcut(tmp_path):
    config = load_config(cli_args={"repo": str(tmp_path), "dry_run": True})
    orchestrator = Orchestrator(config=config)
    session_result = orchestrator.run(issue_text="hi")

    assert session_result.status == AgentPhase.DONE
    assert session_result.verification_result is None
    assert session_result.total_steps == 0
    assert "Hello. I'm Zenith" in session_result.final_response
    assert len(session_result.modified_files) == 0
