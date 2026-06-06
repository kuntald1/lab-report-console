#!/bin/bash

echo ""
echo " =========================================="
echo "  MediCloud Local Backend - Starting..."
echo " =========================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo " [ERROR] .env file not found!"
    echo " Please copy .env.example to .env and fill in your database details."
    echo ""
    exit 1
fi

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo " [ERROR] Python3 not found!"
    echo " Install: sudo apt install python3 python3-pip python3-venv"
    echo ""
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo " [INFO] Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
source venv/bin/activate

# Install dependencies
echo " [INFO] Installing dependencies..."
pip install -r requirements.txt --quiet

# Show local IP
echo ""
echo " [INFO] Your local IP address:"
hostname -I | awk '{print "  " $1}'
echo ""
echo " [INFO] Starting MediCloud backend on http://0.0.0.0:8001"
echo " [INFO] API Docs: http://localhost:8001/docs"
echo " [INFO] Press Ctrl+C to stop"
echo ""

# Start the server
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
