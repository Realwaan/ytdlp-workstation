"""
Tests for Audio Loudness Normalization (EBU R128) in format_builder and CLI.
"""

from unittest.mock import MagicMock, patch
from ytdlp_workstation.core.state import DownloadJob, AppState
from ytdlp_workstation.engine.format_builder import _build_common_options, build_subprocess_command
from ytdlp_workstation.cli.commands import cmd_norm


def test_native_opts_injects_loudnorm_when_enabled():
    job = DownloadJob(url="https://www.youtube.com/watch?v=audiotest1", preset_override=7, force_audio=True)
    config = {"preset": 7, "audio_loudness_norm": True}

    opts = _build_common_options(job, config)
    assert "postprocessor_args" in opts
    assert "ExtractAudio" in opts["postprocessor_args"]
    assert "-af" in opts["postprocessor_args"]["ExtractAudio"]
    assert "loudnorm=I=-16:TP=-1.5:LRA=11" in opts["postprocessor_args"]["ExtractAudio"]


def test_native_opts_skips_loudnorm_when_disabled():
    job = DownloadJob(url="https://www.youtube.com/watch?v=audiotest2", preset_override=7, force_audio=True)
    config = {"preset": 7, "audio_loudness_norm": False}

    opts = _build_common_options(job, config)
    assert "postprocessor_args" not in opts


def test_subprocess_command_injects_loudnorm_flag():
    job = DownloadJob(url="https://www.youtube.com/watch?v=audiotest3", preset_override=7, force_audio=True)
    config = {"preset": 7, "audio_loudness_norm": True}

    cmd, preset_name = build_subprocess_command(job, config)
    assert "--postprocessor-args" in cmd
    idx = cmd.index("--postprocessor-args")
    assert "ExtractAudio:-af loudnorm=I=-16:TP=-1.5:LRA=11" in cmd[idx + 1]


def test_cmd_norm_toggle_and_set(capsys):
    state = AppState()
    state.config["audio_loudness_norm"] = False

    # Check status display
    cmd_norm("norm", state=state)
    out = capsys.readouterr().out
    assert "DISABLED" in out

    # Turn on
    cmd_norm("norm on", state=state)
    assert state.config["audio_loudness_norm"] is True

    # Toggle off
    cmd_norm("norm toggle", state=state)
    assert state.config["audio_loudness_norm"] is False

    # Turn off explicitly
    cmd_norm("norm off", state=state)
    assert state.config["audio_loudness_norm"] is False
