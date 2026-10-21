"""Generate a private, reviewable launchd plan for periodic worker intake."""

import os
import plistlib
import stat
from pathlib import Path

from .storage import StorageError, write_bundle


class LaunchdError(Exception):
    """The launchd plan inputs are invalid or unsafe."""


_LABEL = "com.hyperreview.intake"
_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def _absolute(path, name):
    """Make an absolute lexical path while preserving a final venv symlink."""
    candidate = Path(path).expanduser()
    if ".." in candidate.parts:
        raise LaunchdError(f"{name} path must not contain parent traversal")
    return Path(os.path.abspath(candidate))


def _check_parents(path, name, *, allow_final_symlink=False):
    """Reject symlinked parents; optionally permit the final executable symlink."""
    parts = path.parts
    current = Path(parts[0])
    for index, part in enumerate(parts[1:], start=1):
        current = current / part
        is_final = index == len(parts) - 1
        try:
            mode = current.lstat().st_mode
        except OSError as error:
            raise LaunchdError(f"{name} path is unavailable") from error
        if stat.S_ISLNK(mode) and not (allow_final_symlink and is_final):
            raise LaunchdError(f"{name} path must not traverse symlinks")


def _private_regular_file(path, name):
    _check_parents(path, name)
    try:
        info = path.stat()
    except OSError as error:
        raise LaunchdError(f"{name} file is unavailable") from error
    if not stat.S_ISREG(info.st_mode):
        raise LaunchdError(f"{name} must be a regular file")
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise LaunchdError(f"{name} file must be private (mode 0600 or stricter)")


def _executable(path):
    _check_parents(path, "Python", allow_final_symlink=True)
    try:
        info = path.stat()
    except OSError as error:
        raise LaunchdError("Python executable is unavailable") from error
    if not stat.S_ISREG(info.st_mode) or not os.access(path, os.X_OK):
        raise LaunchdError("Python must name a regular executable file")


def _private_directory(path, name):
    _check_parents(path, name)
    try:
        info = path.stat()
    except OSError as error:
        raise LaunchdError(f"{name} directory is unavailable") from error
    if not stat.S_ISDIR(info.st_mode):
        raise LaunchdError(f"{name} must be a directory")
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise LaunchdError(f"{name} directory must be private")


def write_launchd_plan(*, config_path: Path, python: Path, output_root: Path) -> Path:
    """Write a private launchd plist and operator instructions; never install it."""
    config = _absolute(config_path, "Config")
    interpreter = _absolute(python, "Python")
    _private_regular_file(config, "Config")
    _executable(interpreter)

    # Keep this import lazy: worker intake remains independently usable without
    # loading a configuration until the operator asks for a launchd plan.
    from .worker import WAKE_SECONDS, WorkerError, _prepare_logs, load_config

    try:
        loaded = load_config(config)
        interval = loaded["interval_seconds"]
        state_root = _absolute(loaded["state_root"], "State root")
    except LaunchdError:
        raise
    except (WorkerError, OSError, ValueError, KeyError, TypeError) as error:
        raise LaunchdError("Worker configuration is invalid") from error
    if type(interval) is not int or interval < 300:
        raise LaunchdError("Worker interval must be an integer of at least 300 seconds")
    _private_directory(state_root, "State root")
    try:
        _prepare_logs(state_root)
    except (WorkerError, OSError, ValueError) as error:
        raise LaunchdError("Worker log targets must be owner-private") from error
    log_root = state_root / "logs"
    _private_directory(log_root, "State logs")

    plist = {
        "Label": "com.hyperreview.preview" if "preview" in loaded else _LABEL,
        "ProgramArguments": [
            str(interpreter), "-B", "-m", "hyperreview", "worker-run",
            "--config", str(config),
        ],
        "StartInterval": WAKE_SECONDS,
        "RunAtLoad": False,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "Umask": 63,
        "ExitTimeOut": 10,
        "WorkingDirectory": str(state_root),
        "StandardOutPath": str(log_root / "worker.stdout.log"),
        "StandardErrorPath": str(log_root / "worker.stderr.log"),
        "EnvironmentVariables": {
            "PATH": _PATH,
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    }
    plist_bytes = plistlib.dumps(plist, fmt=plistlib.FMT_XML, sort_keys=True)
    instructions = _installation_instructions(private_preview="preview" in loaded,
                                              review_gates="review_gate" in loaded)
    try:
        destination = write_bundle(
            {"agent.plist": plist_bytes, "installation.md": instructions}, output_root
        )
    except (OSError, StorageError) as error:
        raise LaunchdError("Could not write the private launchd plan") from error
    return destination


def _installation_instructions(private_preview=False, review_gates=False):
    """Static instructions intentionally contain no input-controlled shell text."""
    instructions = b"""# HyperReview worker launchd plan

Review `agent.plist` before installation. This plan runs only the bounded worker
intake tick. It reads GitHub state and prepares private evidence/request
artifacts. Unattended inference and publication remain disabled until a separate
operational gate is approved.

## Install after review

Copy `agent.plist` to `~/Library/LaunchAgents/com.hyperreview.intake.plist` and
set mode 0600:

```sh
mkdir -p "$HOME/Library/LaunchAgents"
install -m 600 agent.plist "$HOME/Library/LaunchAgents/com.hyperreview.intake.plist"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.hyperreview.intake.plist"
```

Run those commands from the directory containing the reviewed `agent.plist`.
The generator does not copy or install the file and does not invoke `launchctl`.

## Disable and unload

```sh
launchctl disable "gui/$(id -u)/com.hyperreview.intake"
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.hyperreview.intake.plist"
```

To re-enable it later, review the plist again, run `launchctl enable
"gui/$(id -u)/com.hyperreview.intake"`, then bootstrap the plist as above.
"""

    if private_preview:
        instructions = instructions.replace(b"com.hyperreview.intake", b"com.hyperreview.preview")
        instructions = instructions.replace(
            b"Review `agent.plist` before installation. This plan runs only the bounded worker\n"
            b"intake tick. It reads GitHub state and prepares private evidence/request\n"
            b"artifacts. Unattended inference and publication remain disabled until a separate\n"
            b"operational gate is approved.",
            b"Review `agent.plist`, the private-preview config, cloud acknowledgement and\n"
            b"binary pins before installation. This plan runs bounded intake and isolated\n"
            b"Codex generation through a private compiled preview. It does not publish,\n"
            b"track, create review gates or merge PRs. It uses a separate preview service\n"
            b"label; keep its state root separate from an existing intake-only timer.")
    if review_gates:
        instructions = instructions.replace(
            b"It does not publish,\ntrack, create review gates or merge PRs.",
            b"It creates and completes only its own explicitly authorized automatic review threads.\n"
            b"Failures keep the thread open; deadlines do not release it. It does not publish ordinary comments,\n"
            b"track or merge PRs.")
        instructions += b"\nThe review-gate repository grant and ETA are in the v3 worker config.\n"
    instructions += b"\nThe service wakes every 30 seconds. The configured interval limits PR discovery, not ready queue work. One run collects at most one request and may immediately generate one preview under the existing grants and budgets.\n"
    return instructions
