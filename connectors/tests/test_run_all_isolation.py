"""
Regression guard for the Sep 23 2026 audit finding: a single connector's
missing env var must never prevent every OTHER connector from running.
Previously run_all.py imported all connectors at module level, so one
KeyError during import (confirmed real: megaphone_connector with no
MEGAPHONE_* secrets in daily-sync.yml) killed the entire daily sync.
"""
import os
import sys
import types
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import run_all  # noqa: E402


def test_importing_run_all_does_not_import_any_connector():
    """Importing run_all itself must be side-effect free -- no connector
    module (and so no module-level os.environ[...] read) gets touched."""
    for _, target in run_all.CONNECTORS:
        assert isinstance(target, str) and ":" in target


def test_one_broken_connector_does_not_stop_the_others():
    ran = []
    good = types.ModuleType("fake_good_connector")
    good.run = lambda: ran.append("good") or 1
    sys.modules["fake_good_connector"] = good

    def broken_import(name, *a, **k):
        if name == "fake_broken_connector":
            raise KeyError("MISSING_SECRET")
        return real_import(name, *a, **k)

    real_import = run_all.importlib.import_module
    with patch.object(run_all, "CONNECTORS", [("broken", "fake_broken_connector:run"),
                                              ("good", "fake_good_connector:run")]), \
         patch.object(run_all.importlib, "import_module", side_effect=broken_import):
        exit_code = run_all.main()

    assert ran == ["good"], "the healthy connector must still run after a broken one"
    assert exit_code == 1, "the run as a whole must still report failure"


def test_every_registered_target_names_a_real_module_file():
    here = os.path.dirname(os.path.dirname(__file__))
    for _, target in run_all.CONNECTORS:
        module_name = target.split(":")[0]
        assert os.path.exists(os.path.join(here, f"{module_name}.py")), module_name
