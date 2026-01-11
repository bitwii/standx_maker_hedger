#!/bin/bash
# Start script for StandX Maker Hedger

echo "============================================"
echo "  StandX Maker Hedger - Market Making Bot"
echo "============================================"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "ERROR: .env file not found!"
    echo "Please copy .env.example to .env and fill in your credentials"
    echo ""
    echo "  cp .env.example .env"
    echo "  nano .env  # or use your preferred editor"
    echo ""
    exit 1
fi

# Check if config.json exists
if [ ! -f config.json ]; then
    echo "ERROR: config.json not found!"
    exit 1
fi

# Create logs directory
mkdir -p logs

# Activate virtual environment if it exists
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
elif [ -d "env" ]; then
    echo "Activating virtual environment..."
    source env/bin/activate
fi

# Check dependencies
echo "Checking dependencies..."
pip install -q -r requirements.txt

echo ""
echo "Starting StandX Maker Hedger..."
echo "Press Ctrl+C to stop"
echo ""

# Run the bot
python main.py

echo ""
echo "Bot stopped."
