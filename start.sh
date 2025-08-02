#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Start the Uvicorn server in the background
echo "Starting Uvicorn server..."
uvicorn main:app --host 0.0.0.0 --port 4004 &

# Start the ML worker script in the background
echo "Starting ML worker script..."
python ./ml_model/run.py &

# Wait for any process to exit
wait -n

# Exit with status of process that exited first
exit $?