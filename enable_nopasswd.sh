#!/bin/bash

# This script enables passwordless sudo for the current user.
# It creates a specific override file in /etc/sudoers.d/

TARGET_USER="kalm"
OVERRIDE_FILE="/etc/sudoers.d/90-$TARGET_USER-overrides"

echo "[*] Setting up passwordless sudo for $TARGET_USER..."

# 1. Check if the user exists
if ! id "$TARGET_USER" &>/dev/null; then
    echo "[!] Error: User $TARGET_USER does not exist on this system."
    exit 1
fi

# 2. Create the sudoers entry
# We use sudo here, so you will be prompted for your password ONE LAST TIME.
echo "$TARGET_USER ALL=(ALL) NOPASSWD:ALL" | sudo tee "$OVERRIDE_FILE" > /dev/null

# 3. Set strict permissions (required by sudo)
sudo chmod 0440 "$OVERRIDE_FILE"

# 4. Verify
if sudo -n true 2>/dev/null; then
    echo "[SUCCESS] Passwordless sudo is now enabled for $TARGET_USER."
else
    echo "[FAILED] Something went wrong. Sudo still requires a password."
    exit 1
fi
