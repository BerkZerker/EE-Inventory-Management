#!/usr/bin/env bash
set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $WEB_PID $WEBHOOK_PID $FRONTEND_PID 2>/dev/null
    wait $WEB_PID $WEBHOOK_PID $FRONTEND_PID 2>/dev/null
    echo "All services stopped."
}
trap cleanup EXIT INT TERM

# Initialize database if it doesn't exist
if [ ! -f data/ebike_inventory.db ]; then
    echo "Initializing database..."
    uv run python main.py init-db
fi

# Start API server
echo "Starting API server on port 5000..."
uv run python main.py web &
WEB_PID=$!

# Start webhook listener
echo "Starting webhook listener on port 5001..."
uv run python main.py webhook &
WEBHOOK_PID=$!

# Start frontend dev server
echo "Starting frontend dev server on port 5173..."
cd frontend && npm run dev &
FRONTEND_PID=$!
cd "$DIR"

echo ""
echo "========================================="
echo "  All services running:"
echo "  API:      http://localhost:5000"
echo "  Webhook:  http://localhost:5001"
echo "  Frontend: http://localhost:5173"
echo "========================================="
echo "  Press Ctrl+C to stop all services"
echo "========================================="
echo ""

# Open frontend in browser after a short delay to let the dev server start
(sleep 2 && xdg-open http://localhost:5173 2>/dev/null || open http://localhost:5173 2>/dev/null || true) &

wait
