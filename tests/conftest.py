"""
Shared pytest configuration.

Redirects every persistent file the workstation writes (config.json, history.json,
archive.txt, workstation.db, downloads/) into a throwaway temp folder BEFORE the
package is imported. Without this, tests calling ``AppState().set_config(...)``
silently overwrote the user's real ``data/config.json`` (e.g. pointing
``rank_download_dir`` at a pytest temp directory).
"""

import os
import shutil
import tempfile

_TEST_ROOT = tempfile.mkdtemp(prefix="ytdlp_ws_tests_")
os.environ["YTDLP_WS_DATA_DIR"] = os.path.join(_TEST_ROOT, "data")
os.environ["YTDLP_WS_DOWNLOAD_DIR"] = os.path.join(_TEST_ROOT, "downloads")


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_ROOT, ignore_errors=True)
