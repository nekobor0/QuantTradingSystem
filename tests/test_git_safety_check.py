from __future__ import annotations

import json

import scripts.git_safety_check as safety


def test_safe_text_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "ROOT", tmp_path)
    (tmp_path / "safe.py").write_text("value = 'public configuration'\n", encoding="utf-8")
    assert safety.inspect_path("safe.py", "worktree") == 0


def test_hard_coded_credential_is_redacted_and_rejected(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(safety, "ROOT", tmp_path)
    sample_value = "not_for_version_control_" + "x" * 16
    (tmp_path / "unsafe.py").write_text(f"password = {sample_value!r}\n", encoding="utf-8")
    assert safety.inspect_path("unsafe.py", "worktree") == 1
    output = capsys.readouterr().out
    assert "unsafe.py:1" in output
    assert "hard-coded credential-like literal" in output
    assert sample_value not in output


def test_notebook_output_and_forbidden_extension_are_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(safety, "ROOT", tmp_path)
    notebook = {
        "cells": [{"cell_type": "code", "execution_count": 1, "outputs": [{"output_type": "stream"}]}]
    }
    (tmp_path / "analysis.ipynb").write_text(json.dumps(notebook), encoding="utf-8")
    assert safety.inspect_path("analysis.ipynb", "worktree") == 1
    (tmp_path / "prices.csv").write_text("date,close\n", encoding="utf-8")
    assert safety.inspect_path("prices.csv", "worktree") == 1
