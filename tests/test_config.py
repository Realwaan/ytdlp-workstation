"""Tests for Configuration Manager."""

import json
from pathlib import Path
from ytdlp_workstation.core.config import ConfigManager, DEFAULT_CONFIG


def test_config_defaults(tmp_path):
    cfg_file = tmp_path / "test_config.json"
    mgr = ConfigManager(config_path=cfg_file)
    assert mgr.get("clipboard_mode") == "auto"
    assert mgr.get("preset") == 1
    assert mgr.get("use_download_archive") is True
    assert mgr.get("max_concurrent_downloads") == 2


def test_config_set_and_save(tmp_path):
    cfg_file = tmp_path / "test_config.json"
    mgr = ConfigManager(config_path=cfg_file)
    mgr.set("preset", 3)
    mgr.set("speed_limit", "10M")

    # Read back directly from disk
    assert cfg_file.exists()
    with open(cfg_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["preset"] == 3
    assert data["speed_limit"] == "10M"


def test_config_update(tmp_path):
    cfg_file = tmp_path / "test_config.json"
    mgr = ConfigManager(config_path=cfg_file)
    mgr.update({"sponsorblock": True, "codec_preference": "compatibility"})

    new_mgr = ConfigManager(config_path=cfg_file)
    assert new_mgr.get("sponsorblock") is True
    assert new_mgr.get("codec_preference") == "compatibility"
