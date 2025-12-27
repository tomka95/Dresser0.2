"""Runtime version validation utilities."""

import sys
from typing import Tuple


# Minimum required Python version
REQUIRED_PYTHON_MAJOR = 3
REQUIRED_PYTHON_MINOR = 8


def get_python_version() -> Tuple[int, int, int]:
    """Get the current Python version as (major, minor, patch)."""
    return sys.version_info[:3]


def format_version(version: Tuple[int, int, int]) -> str:
    """Format version tuple as string (e.g., '3.11.5')."""
    return f"{version[0]}.{version[1]}.{version[2]}"


def check_python_version() -> None:
    """Check if Python version meets requirements. Raises SystemExit if incompatible."""
    current = get_python_version()
    current_str = format_version(current)
    
    # Log detected version
    print(f"[VERSION CHECK] Detected Python {current_str}")
    
    # Check major version
    if current[0] != REQUIRED_PYTHON_MAJOR:
        error_msg = (
            f"❌ Incompatible Python version detected: {current_str}\n"
            f"   Required: Python {REQUIRED_PYTHON_MAJOR}.{REQUIRED_PYTHON_MINOR}+ (Python 3.8 or higher)\n"
            f"   Detected: Python {current_str}\n"
            f"   Please upgrade Python to a compatible version."
        )
        print(error_msg, file=sys.stderr)
        sys.exit(1)
    
    # Check minor version
    if current[1] < REQUIRED_PYTHON_MINOR:
        error_msg = (
            f"❌ Incompatible Python version detected: {current_str}\n"
            f"   Required: Python {REQUIRED_PYTHON_MAJOR}.{REQUIRED_PYTHON_MINOR}+ (Python 3.8 or higher)\n"
            f"   Detected: Python {current_str}\n"
            f"   Please upgrade Python to a compatible version."
        )
        print(error_msg, file=sys.stderr)
        sys.exit(1)
    
    # Success
    print(f"[VERSION CHECK] ✓ Python version {current_str} is compatible (requires {REQUIRED_PYTHON_MAJOR}.{REQUIRED_PYTHON_MINOR}+)")

