import os
import subprocess
import sys

from run import ROOT, api_environment


def test_api_subprocess_can_import_src_package_without_installing_it():
    environment = api_environment()
    source_path = str(ROOT / "src")
    assert environment["PYTHONPATH"].split(os.pathsep)[0] == source_path

    code = (
        "import importlib.util; "
        "assert importlib.util.find_spec('shopping_agent') is not None"
    )
    subprocess.run([sys.executable, "-S", "-c", code], cwd=ROOT, env=environment, check=True)


def test_api_environment_preserves_existing_pythonpath(monkeypatch):
    from run import api_environment

    monkeypatch.setenv("PYTHONPATH", "existing-path")
    assert api_environment()["PYTHONPATH"] == os.pathsep.join(
        [str(ROOT / "src"), "existing-path"]
    )
