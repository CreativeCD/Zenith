#!/usr/bin/env bash
# install.sh — 1-step installer for Zenith (zencode / zicode)
# Compatible with macOS, Linux, and WSL.

set -e

echo ""
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║   ⚡ ZENITH AI CODING ASSISTANT INSTALLER    ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo ""

# 1. Check Python
PYTHON_BIN=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v "$cmd")"
    break
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "❌ Error: Python 3.10+ is required but was not found."
  echo "Please install Python from https://www.python.org/ or via your package manager."
  exit 1
fi

PY_VER="$($PYTHON_BIN -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
echo "  • Found Python : $PYTHON_BIN (version $PY_VER)"

# 2. Get repository directory
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$REPO_DIR"

# 3. Install Python dependencies
echo "  • Installing dependencies from requirements.txt..."
"$PYTHON_BIN" -m pip install -q -r requirements.txt

# 4. Setup .env
if [ ! -f "$REPO_DIR/.env" ]; then
  if [ -f "$REPO_DIR/.env.example" ]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    echo "  • Created .env from .env.example"
  else
    touch "$REPO_DIR/.env"
  fi
  echo ""
  echo "  ⚠️  ACTION REQUIRED: Set your Google Gemini API key!"
  echo "     Get a free key at: https://aistudio.google.com/"
  echo "     Add it to: $REPO_DIR/.env as AI_API_KEY=your_key"
  echo ""
fi

# 5. Link executable to ~/.local/bin
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

chmod +x "$REPO_DIR/zicode"
ln -sf "$REPO_DIR/zicode" "$INSTALL_DIR/zicode"
ln -sf "$REPO_DIR/zicode" "$INSTALL_DIR/zencode"

echo "  • Linked commands to: $INSTALL_DIR/zencode and $INSTALL_DIR/zicode"

# 6. Check PATH
case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *)
    echo "  • Adding $INSTALL_DIR to your shell profile..."
    SHELL_PROFILE=""
    if [ -n "$ZSH_VERSION" ] || [ "$SHELL" = "/bin/zsh" ] || [ "$SHELL" = "/usr/bin/zsh" ]; then
      SHELL_PROFILE="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
      SHELL_PROFILE="$HOME/.bashrc"
    elif [ -f "$HOME/.bash_profile" ]; then
      SHELL_PROFILE="$HOME/.bash_profile"
    fi

    if [ -n "$SHELL_PROFILE" ]; then
      echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_PROFILE"
      echo "  • Added to $SHELL_PROFILE (restart terminal or run: source $SHELL_PROFILE)"
    fi
    ;;
esac

echo ""
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║   ✅ ZENITH INSTALLED SUCCESSFULLY!          ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo ""
echo "  To start, open any terminal or repo and run:"
echo "    zencode"
echo ""
