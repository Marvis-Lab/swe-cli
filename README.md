<p align="center">
  <img src="logo/swe-cli-high-resolution-logo-grayscale-transparent.png" alt="SWE-CLI Logo" width="400" style="border: 2px solid #e1e4e8; border-radius: 12px; padding: 20px;"/>
</p>

<h1 align="center">SWE-CLI</h1>

<p align="center">
  <a href="https://pypi.org/project/swe-cli/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/swe-cli?style=flat-square" /></a>
  <a href="https://python.org/"><img alt="Python version" src="https://img.shields.io/badge/python-%3E%3D3.10-brightgreen?style=flat-square" /></a>
  <a href="./LICENSE"><img alt="License: MIT" src="https://img.shields.io/badge/License-MIT-blue.svg?style=flat-square" /></a>
</p>

## Overview

**SWE-CLI** is a one-stop, cost-effective CLI-based coding agent designed to democratize how coding agents are built. It supports **MCP (Model Context Protocol)**, **multi-provider LLMs** (Fireworks, OpenAI, Anthropic), and deep **codebase understanding** through a modular, SOLID-based architecture.

## Installation

We recommend using [uv](https://github.com/astral-sh/uv) for fast and reliable installation.

### User Installation
```bash
uv pip install swe-cli
```

### Development Setup
```bash
git clone https://github.com/swe-cli/swe-cli.git
cd swe-cli
uv sync
```

## Quick Start

1.  **Configure**: Run the setup wizard to configure your LLM providers.
    ```bash
    swecli config setup
    ```

2.  **Run**: Start the interactive coding assistant.
    ```bash
    swecli
    ```
    *Or start the Web UI:*
    ```bash
    swecli run ui
    ```

## Key Components

*   **Interactive TUI**: A full-screen, Textual-based terminal interface for seamless interaction.
*   **MCP Support**: Extensible architecture using the Model Context Protocol to connect with external tools and data.
*   **Multi-Provider**: Native support for Fireworks, OpenAI, and Anthropic models.
*   **Session Management**: Persistent conversation history and context management.
*   **SOLID Architecture**: Built with clean, maintainable code using dependency injection and interface-driven design.

## License

[MIT](LICENSE)
