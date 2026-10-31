"""Start the local mock store and open its storefront in the default browser."""

import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "mock-store" / "storefront"
API_URL = "http://127.0.0.1:8000/api/products"
SHOP_URL = "http://localhost:5173"
NPM = "npm.cmd" if os.name == "nt" else "npm"
NODE = "node"


def ensure_frontend_dependencies() -> None:
    """Install storefront packages on first run when npm has not created node_modules."""
    if (FRONTEND / "node_modules" / "vite").exists():
        return

    if shutil.which(NPM) is None or shutil.which(NODE) is None:
        raise RuntimeError("Node.js and npm are required; install Node.js 20 or newer, then rerun.")

    print("Installing storefront packages for the first run...")
    subprocess.run([NPM, "install"], cwd=FRONTEND, check=True)


def api_environment() -> dict[str, str]:
    """Add the repository's src layout to the Uvicorn child without requiring a package install."""
    environment = os.environ.copy()
    source_path = str(ROOT / "src")
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        source_path + os.pathsep + existing_pythonpath
        if existing_pythonpath
        else source_path
    )
    return environment


def wait_until_ready(url: str, process: subprocess.Popen, label: str) -> None:
    """Wait for a child server to answer or fail fast when it exits or times out."""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{label} exited before becoming ready; check its output above.")

        try:
            with urlopen(url, timeout=1):
                return

        except (OSError, URLError):
            time.sleep(0.25)

    raise RuntimeError(f"{label} did not become ready within 30 seconds.")


def stop_processes(processes: list[subprocess.Popen]) -> None:
    for process in reversed(processes):
        if process.poll() is None:
            process.terminate()

    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=5)

            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    """Launch the API and storefront together, then open the working storefront URL."""
    if sys.version_info < (3, 12):
        print("Python 3.12 or newer is required.", file=sys.stderr)
        return 1

    try:
        import fastapi  # noqa: F401
        import pydantic  # noqa: F401
        import uvicorn  # noqa: F401

    except ImportError:
        print("Python packages are missing; run `py -m pip install -r requirements.txt`.", file=sys.stderr)
        return 1

    if shutil.which(NPM) is None or shutil.which(NODE) is None:
        print("Node.js and npm are required; install Node.js 20 or newer.", file=sys.stderr)
        return 1

    processes = []
    try:
        ensure_frontend_dependencies()
        api = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "server.app:app",
                "--app-dir", "mock-store", "--host", "127.0.0.1", "--port", "8000",
            ],
            cwd=ROOT,
            env=api_environment(),
        )
        processes.append(api)
        wait_until_ready(API_URL, api, "Mock-store API")

        frontend = subprocess.Popen(
            [
                NODE, "node_modules/vite/bin/vite.js", "--host", "127.0.0.1",
                "--port", "5173", "--strictPort",
            ],
            cwd=FRONTEND,
        )
        processes.append(frontend)
        wait_until_ready(SHOP_URL, frontend, "Storefront")

        print(f"Shopping store is running at {SHOP_URL}")
        print("Press Ctrl+C to stop both servers.")
        webbrowser.open(SHOP_URL)

        while all(process.poll() is None for process in processes):
            time.sleep(0.5)

        return 0

    except KeyboardInterrupt:
        print("\nStopping the shopping store...")
        return 0

    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Could not start the shopping store: {error}", file=sys.stderr)
        return 1

    finally:
        stop_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
