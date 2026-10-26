import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from ytdlp_workstation.engine.auto_clipper import (
    get_sfx_path,
    create_vertical_short,
    generate_anti_spam_variants,
)


def test_get_sfx_path(tmp_path):
    with patch("ytdlp_workstation.engine.auto_clipper.SFX_DIR", tmp_path):
        fake_wav = tmp_path / "test_sfx.wav"
        fake_wav.write_text("audio")
        
        assert get_sfx_path("test_sfx") == fake_wav
        assert get_sfx_path("non_existent") is None


def test_create_vertical_short_nonexistent_input(tmp_path):
    non_existent = tmp_path / "no_such_file.mp4"
    out = tmp_path / "out.mp4"
    res = create_vertical_short(non_existent, out)
    assert res is None


@patch("subprocess.run")
def test_create_vertical_short_success(mock_sub, tmp_path):
    input_file = tmp_path / "stream.mp4"
    input_file.write_text("video_content")
    out_file = tmp_path / "output_short.mp4"

    def side_effect(cmd, **kwargs):
        # Create output file to simulate successful ffmpeg render
        out_file.write_text("rendered_output")
        m = MagicMock()
        m.returncode = 0
        return m

    mock_sub.side_effect = side_effect

    res = create_vertical_short(
        input_file=input_file,
        output_file=out_file,
        title_hook="FaZe Win",
        sfx_cues=[{"sfx": "ding", "time_s": 2.0, "volume": 1.0}],
    )

    assert res == out_file
    assert out_file.exists()
    assert mock_sub.called
    cmd_args = mock_sub.call_args[0][0]
    assert "-filter_complex" in cmd_args


@patch("ytdlp_workstation.engine.auto_clipper.create_vertical_short")
def test_generate_anti_spam_variants(mock_create, tmp_path):
    input_file = tmp_path / "faze.mp4"
    input_file.write_text("sample")
    out_dir = tmp_path / "variants"

    # Simulate each variant returning an existing path
    def mock_render(input_file, output_file, **kwargs):
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text("variant")
        return output_file

    mock_create.side_effect = mock_render

    variants = generate_anti_spam_variants(input_file, out_dir, base_name="TEST_FAZE")

    assert len(variants) == 3
    assert mock_create.call_count == 3
    names = [v.name for v in variants]
    assert any("V1_GRAIL" in n for n in names)
    assert any("V2_REACTION" in n for n in names)
    assert any("V3_HOLY_GRAIL" in n for n in names)
