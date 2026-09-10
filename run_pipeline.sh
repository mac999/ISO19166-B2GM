#!/bin/sh
# Run the PD -> CM -> EM -> LM pipeline on the shipped example.
# Extra arguments are passed on to B2GM_main.py, e.g.:
#   ./run_pipeline.sh --citygml-version 3.0
set -e
cd "$(dirname "$0")"

if [ -z "$PYTHON" ]; then
    for candidate in python3 python; do
        if command -v "$candidate" >/dev/null 2>&1; then
            PYTHON="$candidate"
            break
        fi
    done
fi
if [ -z "$PYTHON" ]; then
    echo "Python 3.9 or newer is required but was not found on PATH." >&2
    echo "Install it, or point PYTHON at an interpreter: PYTHON=/path/to/python $0" >&2
    exit 1
fi

if ! "$PYTHON" -c "import ifcopenshell, pyproj, shapely, numpy, tqdm" >/dev/null 2>&1; then
    echo "Installing the core dependencies into $PYTHON ..."
    "$PYTHON" -m pip install -r requirements.txt
fi

exec "$PYTHON" B2GM_main.py "$@"
