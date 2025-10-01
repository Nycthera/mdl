#!/bin/bash

echo "Are you sure you want to update? (y/n)"
read -r answer

if [[ "$answer" =~ ^[Yy]$ ]]; then
    echo "🔄 Updating repo..."
    git pull origin main || { echo "❌ Git pull failed"; exit 1; }

    TARGET="/usr/local/bin/mdl"
    BACKUP="/usr/local/bin/mdl.bak"
    NEW="/Users/tkrobot/Downloads/mdl/main.py"

    if [ -f "$TARGET" ]; then
        echo "✅ mdl found in /usr/local/bin, backing up..."
        sudo mv "$TARGET" "$BACKUP"

        echo "📦 Installing new mdl..."
        sudo cp "$NEW" "$TARGET"
        sudo chmod +x "$TARGET"
        echo "🎉 Update complete! Old version saved as mdl.bak"
    else
        echo "⚠️ mdl not found in /usr/local/bin, skipping copy."
    fi
else
    echo "❎ Update cancelled."
fi
