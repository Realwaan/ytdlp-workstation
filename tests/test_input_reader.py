import pytest
from unittest.mock import patch, MagicMock
from ytdlp_workstation.cli.input_reader import _read_line_msvcrt, COMMAND_HISTORY, _remember
from ytdlp_workstation.core.state import AppState


def test_remember_history():
    COMMAND_HISTORY.clear()
    _remember("play 1")
    _remember("play 1")  # Deduplicated consecutive
    _remember("help")
    assert COMMAND_HISTORY == ["play 1", "help"]


def test_msvcrt_typing_and_enter():
    state = AppState()
    keys = ["h", "i", "\r"]
    with patch("msvcrt.kbhit", side_effect=[True, True, True]), \
         patch("msvcrt.getwch", side_effect=keys):
        result = _read_line_msvcrt(">>> ", state, history=False, interruptible=False)
        assert result == "hi"


def test_msvcrt_in_line_arrow_and_insert():
    state = AppState()
    # Type 'a', 'c', Left Arrow ('\xe0', 'K'), type 'b', Enter
    keys = ["a", "c", "\xe0", "K", "b", "\r"]
    with patch("msvcrt.kbhit", side_effect=[True] * len(keys)), \
         patch("msvcrt.getwch", side_effect=keys):
        result = _read_line_msvcrt(">>> ", state, history=False, interruptible=False)
        assert result == "abc"


def test_msvcrt_home_and_end_navigation():
    state = AppState()
    # Type 'b', 'c', Home ('\xe0', 'G'), type 'a', End ('\xe0', 'O'), type 'd', Enter
    keys = ["b", "c", "\xe0", "G", "a", "\xe0", "O", "d", "\r"]
    with patch("msvcrt.kbhit", side_effect=[True] * len(keys)), \
         patch("msvcrt.getwch", side_effect=keys):
        result = _read_line_msvcrt(">>> ", state, history=False, interruptible=False)
        assert result == "abcd"


def test_msvcrt_delete_key():
    state = AppState()
    # Type 'a', 'x', 'b', Left Arrow twice, Delete ('\xe0', 'S'), Enter
    keys = ["a", "x", "b", "\xe0", "K", "\xe0", "K", "\xe0", "S", "\r"]
    with patch("msvcrt.kbhit", side_effect=[True] * len(keys)), \
         patch("msvcrt.getwch", side_effect=keys):
        result = _read_line_msvcrt(">>> ", state, history=False, interruptible=False)
        assert result == "ab"


def test_msvcrt_backspace_in_middle():
    state = AppState()
    # Type 'a', 'x', 'b', Left Arrow, Backspace ('\x08'), Enter
    keys = ["a", "x", "b", "\xe0", "K", "\x08", "\r"]
    with patch("msvcrt.kbhit", side_effect=[True] * len(keys)), \
         patch("msvcrt.getwch", side_effect=keys):
        result = _read_line_msvcrt(">>> ", state, history=False, interruptible=False)
        assert result == "ab"


def test_msvcrt_tab_completion_in_loop():
    state = AppState()
    # Type 'm', 'e', 'r', Tab ('\t'), Enter ('\r')
    keys = ["m", "e", "r", "\t", "\r"]
    with patch("msvcrt.kbhit", side_effect=[True] * len(keys)), \
         patch("msvcrt.getwch", side_effect=keys):
        result = _read_line_msvcrt(">>> ", state, history=False, interruptible=False)
        assert result == "merge "


def test_msvcrt_ctrl_c_clears_buffer_first():
    state = AppState()
    # Type 'h', 'i', Ctrl+C ('\x03'), type 'o', 'k', Enter
    keys = ["h", "i", "\x03", "o", "k", "\r"]
    with patch("msvcrt.kbhit", side_effect=[True] * len(keys)), \
         patch("msvcrt.getwch", side_effect=keys):
        result = _read_line_msvcrt(">>> ", state, history=False, interruptible=False)
        assert result == "ok"


def test_msvcrt_ctrl_c_empty_buffer_raises():
    state = AppState()
    with patch("msvcrt.kbhit", return_value=True), \
         patch("msvcrt.getwch", return_value="\x03"):
        with pytest.raises(KeyboardInterrupt):
            _read_line_msvcrt(">>> ", state, history=False, interruptible=False)
