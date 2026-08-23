import pytest

from data_agent.cli import main


def test_eval_milestone_stub_is_explicit(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["eval"]) == 0

    output = capsys.readouterr().out
    assert "reserved for M15" in output
