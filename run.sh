#!/usr/bin/env bash
# Launch TuxVox using its virtual environment.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/.venv/bin/activate"
exec python3 -m tuxvox.main "$@"
