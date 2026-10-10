# Shopping agent

## Run the mock store on Windows

Requirements: Python 3.12 or newer and Node.js 20 or newer. Install the Python packages once from PowerShell:

```powershell
py -m pip install -r requirements.txt
```

Then start both the API and storefront with one command:

```powershell
py run.py
```

The launcher installs the frontend's npm packages on first run, starts both local servers, and opens the storefront in your default browser. Press `Ctrl+C` in the terminal to stop them. You do not need to install `uv`, run the servers separately, or pass host/port flags.

For tests, install the development dependencies once with `py -m pip install -r requirements-dev.txt`, then run `py -m pytest`.

The mock store is synthetic and local-only. It does not make purchases or handle payments. See [mock-store/README.md](mock-store/README.md) for task examples and store behavior.
