#!/bin/bash
# Quick Setup Script for StandX Maker Hedger

set -e  # Exit on error

echo "================================================"
echo "  StandX Maker Hedger - Quick Setup"
echo "================================================"
echo ""

# Check if .env already exists
if [ -f .env ]; then
    read -p ".env file already exists. Overwrite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Keeping existing .env file"
    else
        cp .env.example .env
        echo "Created new .env file from template"
    fi
else
    cp .env.example .env
    echo "✓ Created .env file from template"
fi

# Create logs directory
mkdir -p logs
echo "✓ Created logs directory"

# Check if virtual environment exists
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    echo "✓ Created virtual environment"
else
    source venv/bin/activate
    echo "✓ Activated virtual environment"
fi

# Install dependencies
echo ""
echo "Installing dependencies..."
pip install --upgrade pip
pip install -r requirements.txt
echo "✓ Dependencies installed"

# Make start script executable
chmod +x start.sh
echo "✓ Made start.sh executable"

# Configure VS Code settings
mkdir -p .vscode
cat > .vscode/settings.json << 'EOF'
{
    "python.defaultInterpreterPath": "${workspaceFolder}/venv/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "files.exclude": {
        "**/__pycache__": true,
        "**/*.pyc": true
    }
}
EOF
echo "✓ Configured VS Code settings"

echo ""
echo "============================================="
echo "  Setup Complete!"
echo "============================================="
echo ""
echo "Next steps:"
echo "  1. Edit .env file and add your credentials:"
echo "     nano .env"
echo ""
echo "  2. (Optional) Edit config.json to adjust parameters"
echo ""
echo "  3. Start the bot:"
echo "     ./start.sh"
echo ""
echo "     Or directly:"
echo "     python main.py"
echo ""
echo "Required credentials in .env:"
echo "  - SOLANA_PRIVATE_KEY (StandX)"
echo "  - API_KEY_PRIVATE_KEY (Lighter)"
echo "  - LIGHTER_ACCOUNT_INDEX"
echo "  - LIGHTER_API_KEY_INDEX"
echo ""
