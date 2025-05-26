FROM mcr.microsoft.com/devcontainers/base:1.2.0-ubuntu-24.04

# Install Python 3.12 and development tools
RUN apt-get update -y \
 && apt-get install -y --no-install-recommends \
      curl git build-essential ca-certificates \
      python3.12 python3.12-dev python3.12-venv python3-pip \
      sudo \
 && rm -rf /var/lib/apt/lists/* \
 && echo "vscode ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

# Set Python 3.12 as default
RUN update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
 && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# Install uv for Python package management
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

# Install Node.js 20.x for Claude Code
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - \
 && apt-get install -y nodejs

# Ensure vscode user owns their home directory
RUN chown -R vscode:vscode /home/vscode
# Install Claude Code CLI as non-root user
RUN npm install -g @anthropic-ai/claude-code

USER vscode   # non-root from here on
