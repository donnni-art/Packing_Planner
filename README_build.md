Build instructions (Windows)

This project is packaged into a portable Windows distribution folder so end users do not need to install Python.

Steps to build (developer machine must have Python installed):

1. Open PowerShell or Command Prompt in the project root.
2. Run the build batch file:

```bat
build_planner.bat
```

What the script does:
- Creates a virtual environment in `.venv` if it does not exist.
- Installs or updates build/runtime dependencies from `requirements.txt`.
- Runs PyInstaller in `--onefile` mode.
- Stages a deployable folder at `dist\PackingPlanner\` containing:
	- `PackingPlanner.exe`
	- `app\config.yaml`
	- `app_icon.ico`
	- `output\`

Deploy to another PC:

1. Copy the entire `dist\PackingPlanner\` folder to the target machine.
2. Run `PackingPlanner.exe` from inside that folder.

Notes:
- The build machine needs Python installed. Target machines do not.
- LAN monitor support requires the `websockets` package, which is already listed in `requirements.txt` and bundled by the build script.
- If you add more runtime files later, update `build_planner.bat` and/or `PackingPlanner.spec` together so the packaged output stays consistent with this document.
