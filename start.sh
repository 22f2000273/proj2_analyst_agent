#!/bin/bash

# ================= INSTRUCTIONS =================
echo "=============================================="
echo " How to get the required credentials:"
echo ""
echo " 1. Get your Google API key here:"
echo "    https://aistudio.google.com/apikey"
echo ""
echo " 2. Register at ngrok and get your authtoken:"
echo "    https://ngrok.com/"
echo ""
echo " 3. Create a .env file with:"
echo "    GENAI_API_KEY=your_google_api_key"
echo "    NGROK_AUTHTOKEN=your_ngrok_token"
echo "    api_key=your_google_api_key  # For your existing code"
echo ""
echo " This script will:"
echo "    - Load credentials from .env file"
echo "    - Install all requirements from requirements.txt"
echo "    - Install ngrok (if not already installed)"
echo "    - Start your FastAPI app with uvicorn"
echo "    - Create a public ngrok URL for your app"
echo "=============================================="
echo ""

# ================= LOAD FROM .ENV FILE =================
if [ -f ".env" ]; then
    echo "Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
    echo "✅ Environment variables loaded from .env"
else
    echo "❌ .env file not found. Please create one with your credentials."
    echo "Example .env file:"
    echo "GENAI_API_KEY=your_google_api_key_here"
    echo "NGROK_AUTHTOKEN=your_ngrok_token_here"
    echo "api_key=your_google_api_key_here"
    exit 1
fi

# ================= CREATE & ACTIVATE VENV =================
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

# ================= VALIDATE CREDENTIALS =================
if [ -z "$GENAI_API_KEY" ]; then
    echo "❌ GENAI_API_KEY not found in .env file"
    read -p "Enter your GENAI API key: " GENAI_API_KEY
    export GENAI_API_KEY=$GENAI_API_KEY
else
    echo "✅ GENAI_API_KEY loaded from .env"
fi

if [ -z "$NGROK_AUTHTOKEN" ]; then
    echo "❌ NGROK_AUTHTOKEN not found in .env file"
    read -p "Enter your ngrok authtoken: " NGROK_AUTHTOKEN
    export NGROK_AUTHTOKEN=$NGROK_AUTHTOKEN
else
    echo "✅ NGROK_AUTHTOKEN loaded from .env"
fi

# ================= INSTALL REQUIREMENTS =================
echo "Installing dependencies from requirements.txt..."
pip install -r requirements.txt

# ================= INSTALL NGROK =================
if ! command -v ngrok &> /dev/null; then
    echo "ngrok not found, installing..."
    pip install pyngrok
    NGROK_BIN=$(python3 -m pyngrok config get-path)
else
    NGROK_BIN=$(command -v ngrok)
fi

# ================= CONFIGURE NGROK =================
$NGROK_BIN config add-authtoken "$NGROK_AUTHTOKEN"

# ================= DETECT APP FILE =================
if [ -f "main.py" ]; then
    APP_TARGET="main:app"
elif [ -f "app.py" ]; then
    APP_TARGET="app:app"
else
    echo "Could not detect FastAPI entry file. Please enter module:variable (e.g., app:app)"
    read -p "Module:Variable => " APP_TARGET
fi

# ================= START UVICORN =================
echo "Starting uvicorn server..."
uvicorn $APP_TARGET --reload --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!

# Trap Ctrl+C to stop uvicorn too
trap "echo -e '\nStopping servers...'; kill $UVICORN_PID; exit" INT

# Countdown timer (10 seconds)
echo "Waiting for uvicorn to start..."
for i in {10..1}; do
    echo -ne "Starting in $i seconds...\r"
    sleep 1
done
echo -e "\nServer should be ready now."

# ================= START NGROK (FOREGROUND) =================
echo "Starting ngrok tunnel on port 8000..."
$NGROK_BIN http 8000
