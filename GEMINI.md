# SWE-CLI

## Project Overview

**SWE-CLI** is an AI-powered command-line interface designed to serve as a comprehensive coding agent. It integrates with various LLM providers (Fireworks, OpenAI, Anthropic) to assist developers with coding tasks directly from the terminal. The project emphasizes a modular architecture based on SOLID principles, enabling features like context management, shell command execution, and future capabilities such as GitHub issue resolution and sub-agent orchestration.

**Key Technologies:**
*   **Language:** Python (>=3.10)
*   **UI Frameworks:** Textual, Rich, Prompt Toolkit
*   **LLM Integration:** HTTPX (Native clients), PydanticAI (Experimental)
*   **Web Automation:** Playwright, Crawl4AI
*   **Package Management:** Setuptools, pip

## Architecture

The codebase is organized within the `swecli/` directory:

*   **`swecli/cli.py`**: The main entry point for the application.
*   **`swecli/core/`**: Contains the core logic, including agents and tool definitions.
*   **`swecli/ui_textual/`**: Implements the Textual-based user interface.
*   **`swecli/web/`**: Web UI components and static assets.
*   **`swecli/config/`**: Configuration loading and management.
*   **`swecli/commands/`**: Implementation of specific CLI commands.
*   **`swecli/repl/`**: Read-Eval-Print Loop logic.

## Building and Running

### Installation

To install the project in editable mode (recommended for development):

```bash
pip install -e .
```

To install standard dependencies:

```bash
pip install -r requirements.txt
```

### Running the CLI

Once installed, the CLI can be launched using the entry point:

```bash
swecli
```

### Configuration

Configuration is managed via `~/.swecli/settings.json` or environment variables. See `README.md` for details on setting up providers like Fireworks, OpenAI, or Anthropic.

## Development Conventions

### Testing

The project uses `pytest` for testing. Tests are located in the `tests/` directory.

To run tests:
```bash
pytest
```

### Code Style & Linting

The project adheres to strict code style guidelines enforced by **Black** and **Ruff**. Type checking is performed with **Mypy**.

*   **Formatting:** `black` (Line length: 100)
*   **Linting:** `ruff`
*   **Type Checking:** `mypy` (Strict mode)

Configuration for these tools is found in `pyproject.toml`.

### Contribution Guidelines

*   Follow SOLID principles and interface-driven design.
*   Ensure new features are covered by tests.
*   Run linters and type checkers before committing changes.
