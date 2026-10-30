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
# Bind all interfaces so Tailscale / LAN clients can reach the store (not just this machine's loopback).
BIND_HOST = "0.0.0.0"
API_PORT = 8000
SHOP_PORT = 5173
API_URL = f"http://127.0.0.1:{API_PORT}/api/products"
SHOP_URL = f"http://127.0.0.1:{SHOP_PORT}"
NPM = "npm.cmd" if os.name == "nt" else "npm"


def resolve_node() -> str:
    """Prefer system Node.js; vite-plus's runtime is often firewall-blocked for inbound Tailscale."""
    if os.name == "nt":
        system_node = Path(r"C:\Program Files\nodejs\node.exe")
        if system_node.is_file():
            return str(system_node)
    found = shutil.which("node")
    if found is None:
        raise RuntimeError("Node.js is required; install Node.js 20 or newer, then rerun.")
    return found


def _tailscale_bin() -> str | None:
    return shutil.which("tailscale") or shutil.which("tailscale.exe")


def tailscale_ipv4() -> str | None:
    """Best-effort Tailscale IPv4 for the Network: banner; None if unavailable."""
    executable = _tailscale_bin()
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, "ip", "-4"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    address = (completed.stdout or "").strip().splitlines()
    return address[0].strip() if address else None


def tailscale_app_url(port: int) -> str | None:
    """Prefer MagicDNS serve URL when `tailscale serve` is proxying this port."""
    executable = _tailscale_bin()
    if executable is None:
        return None
    try:
        completed = subprocess.run(
            [executable, "serve", "status"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    needle = f":{port}"
    for line in (completed.stdout or "").splitlines():
        text = line.strip()
        if text.startswith("http") and needle in text and ".ts.net" in text:
            return text if text.endswith("/") else f"{text}/"
    for line in (completed.stdout or "").splitlines():
        text = line.strip()
        if text.startswith("http") and needle in text:
            return text if text.endswith("/") else f"{text}/"
    return None


def ensure_frontend_dependencies(node: str) -> None:
    """Install storefront packages on first run when npm has not created node_modules."""
    if (FRONTEND / "node_modules" / "vite").exists():
        return

    if shutil.which(NPM) is None or not Path(node).exists():
        raise RuntimeError("Node.js and npm are required; install Node.js 20 or newer, then rerun.")

    print("Installing storefront packages for the first run...", flush=True)
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

    try:
        node = resolve_node()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1

    if shutil.which(NPM) is None:
        print("npm is required; install Node.js 20 or newer.", file=sys.stderr)
        return 1

    processes = []
    try:
        ensure_frontend_dependencies(node)
        api = subprocess.Popen(
            [
                sys.executable, "-m", "uvicorn", "server.app:app",
                "--app-dir", "mock-store", "--host", BIND_HOST, "--port", str(API_PORT),
            ],
            cwd=ROOT,
            env=api_environment(),
        )
        processes.append(api)
        wait_until_ready(API_URL, api, "Mock-store API")

        frontend = subprocess.Popen(
            [
                node, "node_modules/vite/bin/vite.js", "--host", BIND_HOST,
                "--port", str(SHOP_PORT), "--strictPort",
            ],
            cwd=FRONTEND,
        )
        processes.append(frontend)
        wait_until_ready(SHOP_URL, frontend, "Storefront")

        print(f"  Local:     http://localhost:{SHOP_PORT}/", flush=True)
        ts_url = tailscale_app_url(SHOP_PORT) or (
            f"http://{tailscale_ipv4()}:{SHOP_PORT}/" if tailscale_ipv4() else None
        )
        if ts_url:
            print(f"  Tailscale: {ts_url}", flush=True)
            docs = tailscale_app_url(API_PORT)
            if docs:
                print(f"  API docs:  {docs.rstrip('/')}/docs", flush=True)
            elif (ip := tailscale_ipv4()):
                print(f"  API docs:  http://{ip}:{API_PORT}/docs", flush=True)
        print("Press Ctrl+C to stop both servers.", flush=True)
        # Open the Tailscale URL in the laptop browser when one is available.
        if ts_url:
            webbrowser.open(ts_url)
        elif sys.stdout.isatty():
            webbrowser.open(f"http://localhost:{SHOP_PORT}/")

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
