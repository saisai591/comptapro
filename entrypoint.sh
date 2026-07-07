#!/bin/sh
# ComptaPro — Docker entrypoint
# Initialise la DB puis lance le serveur

echo "=== ComptaPro ==="
echo "DB path: ${COMPTAPRO_DB_PATH}"
echo "Port:    ${COMPTAPRO_PORT}"
echo ""

# Ensure data dir exists
mkdir -p "$(dirname "$COMPTAPRO_DB_PATH")"

# Init DB via Python
python3 -c "
import sys, os
sys.path.insert(0, '/app')
os.environ['PYTHONIOENCODING'] = 'utf-8'
from comptable.db import init_db
init_db()
print('DB initialisee')
"

# Launch server
exec python3 -m comptable.server --port "${COMPTAPRO_PORT}"
