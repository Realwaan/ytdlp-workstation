"""Tests for watermark remover and delogo / crop filters."""

from pathlib import Path
from unittest.mock import patch
from ytdlp_workstation.engine.watermark_remover import (
    build_delogo_cmd,
    build_crop_cmd,
    build_crop_bottom_cmd,
    delogo_video,
    crop_video,
    clean_video,
)


def test_build_delogo_cmd():
    inp = Path("/fake/video.mp4")
    out = Path("/fake/video_clean.mp4")
    cmd = build_delogo_cmd(inp, out, x=10, y=20, w=150, h=80)
    assert "-vf" in cmd
    idx = cmd.index("-vf")
    assert cmd[idx + 1] == "delogo=x=10:y=20:w=150:h=80"
    assert "-c:a" in cmd
    assert "copy" in cmd
    assert str(out) == cmd[-1]


def test_build_crop_bottom_cmd():
    inp = Path("/fake/video.mp4")
    out = Path("/fake/video_cropped.mp4")
    cmd = build_crop_bottom_cmd(inp, out, crop_bottom_pixels=80)
    assert "-vf" in cmd
    idx = cmd.index("-vf")
    assert cmd[idx + 1] == "crop=in_w:in_h-80:0:0"
    assert str(out) == cmd[-1]


def test_delogo_nonexistent_file():
    res = delogo_video("/nonexistent/file.mp4")
    assert res is None


@patch("ytdlp_workstation.engine.watermark_remover.run_ffmpeg_filter", return_value=True)
def test_delogo_video_success(mock_run, tmp_path):
    dummy = tmp_path / "sample.mp4"
    dummy.write_text("dummy video content")
    out_target = tmp_path / "sample_clean.mp4"
    out_target.write_text("clean video content")

    res = delogo_video(dummy, output_path=out_target, x=5, y=5, w=50, h=50)
    assert res == out_target
    assert mock_run.called


@patch("ytdlp_workstation.engine.watermark_remover.run_ffmpeg_filter", return_value=True)
def test_clean_video_crop_mode(mock_run, tmp_path):
    dummy = tmp_path / "sample2.mp4"
    dummy.write_text("dummy video content")
    out_target = tmp_path / "sample2_cropped.mp4"
    out_target.write_text("cropped video content")

    res = clean_video(dummy, mode="crop", output_path=out_target, crop_bottom_pixels=100)
    assert res == out_target
    assert mock_run.called
