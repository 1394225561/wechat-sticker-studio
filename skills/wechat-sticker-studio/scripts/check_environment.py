"""Report whether this interpreter matches the documented local GIF environment."""

import json
import platform
import sys
from pathlib import Path

PYTHON_VERSION = (3, 12)


def main():
    requirements = Path(__file__).resolve().parents[1] / "requirements.txt"
    errors = []
    required_pillow = None
    try:
        package, _, version = requirements.read_text(encoding="utf-8").strip().partition("==")
        if package != "Pillow" or not version:
            raise ValueError("expected one Pillow==VERSION pin")
        required_pillow = version
    except (OSError, ValueError) as exc:
        errors.append({"code": "invalid_requirements", "message": str(exc)})

    required_python = ".".join(map(str, PYTHON_VERSION))
    if sys.version_info[:2] != PYTHON_VERSION:
        errors.append({"code": "python_version_mismatch", "message": f"Use Python {required_python}."})

    pillow_version = None
    try:
        import PIL.Image

        pillow_version = PIL.__version__
    except (ImportError, OSError) as exc:
        code = "pillow_import_failed"
        if isinstance(exc, ModuleNotFoundError) and exc.name == "PIL":
            code = "pillow_missing"
        errors.append({"code": code, "message": str(exc)})
    if pillow_version and required_pillow and pillow_version != required_pillow:
        errors.append({"code": "pillow_version_mismatch", "message": f"Install Pillow {required_pillow}."})

    print(json.dumps({
        "ok": not errors,
        "python": {"executable": sys.executable, "version": platform.python_version(), "required": required_python},
        "pillow": {"version": pillow_version, "required": required_pillow},
        "errors": errors,
    }, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
