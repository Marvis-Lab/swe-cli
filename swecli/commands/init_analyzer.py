"""Codebase analyzer for /init command.

This module provides utility functions for analyzing codebase structure,
but the main intelligence comes from the Pydantic AI agent making strategic
decisions about what to scan and how deep to go.
"""

from pathlib import Path
from typing import Any, Optional


class CodebaseAnalyzer:
    """Analyzes codebase structure and patterns.

    This class provides helper methods for common analysis tasks,
    but the Pydantic AI agent orchestrates the overall scanning strategy.
    """

    # Common patterns to exclude
    EXCLUDE_PATTERNS = [
        "node_modules",
        ".git",
        "__pycache__",
        "venv",
        ".venv",
        "build",
        "dist",
        ".pytest_cache",
        ".mypy_cache",
        "coverage",
        ".tox",
        "*.egg-info",
    ]

    # Language-specific dependency files
    DEPENDENCY_FILES = {
        "python": ["requirements.txt", "setup.py", "pyproject.toml", "Pipfile", "environment.yml"],
        "javascript": ["package.json", "yarn.lock", "package-lock.json"],
        "typescript": ["package.json", "tsconfig.json"],
        "rust": ["Cargo.toml", "Cargo.lock"],
        "go": ["go.mod", "go.sum"],
        "ruby": ["Gemfile", "Gemfile.lock"],
        "php": ["composer.json", "composer.lock"],
        "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        "csharp": ["*.csproj", "*.sln", "packages.config"],
    }

    # Common entry point patterns by language
    ENTRY_POINT_PATTERNS = {
        "python": [
            ("if __name__ == '__main__':", "*.py"),
            ("main.py", None),
            ("app.py", None),
            ("__main__.py", None),
        ],
        "javascript": [
            ("index.js", None),
            ("main.js", None),
            ("app.js", None),
            ("server.js", None),
        ],
        "typescript": [
            ("index.ts", None),
            ("main.ts", None),
            ("app.ts", None),
        ],
        "go": [
            ("main.go", None),
        ],
        "rust": [
            ("main.rs", None),
        ],
    }

    def __init__(self, path: Path):
        """Initialize analyzer.

        Args:
            path: Path to analyze
        """
        self.path = path

    def get_exclude_patterns_str(self) -> str:
        """Get exclude patterns as string for bash commands.

        Returns:
            String suitable for find command exclusion
        """
        patterns = []
        for pattern in self.EXCLUDE_PATTERNS:
            if pattern.startswith("*"):
                patterns.append(f"-name '{pattern}'")
            else:
                patterns.append(f"-path '*/{pattern}/*'")

        return " -o ".join(patterns)

    def detect_primary_language(self) -> Optional[str]:
        """Detect primary language based on file extensions.

        This is a simple heuristic - count files by extension.
        The AI agent can make more sophisticated determinations.

        Returns:
            Detected language or None
        """
        # This is just a helper - the agent should use bash commands
        # to count files more efficiently
        return None  # Agent will determine via bash tools

    def get_dependency_file_patterns(self, language: str) -> list[str]:
        """Get dependency file patterns for a language.

        Args:
            language: Programming language

        Returns:
            List of dependency file names/patterns
        """
        return self.DEPENDENCY_FILES.get(language.lower(), [])

    def get_entry_point_patterns(self, language: str) -> list[tuple[str, Optional[str]]]:
        """Get entry point patterns for a language.

        Args:
            language: Programming language

        Returns:
            List of (pattern, file_extension) tuples
        """
        return self.ENTRY_POINT_PATTERNS.get(language.lower(), [])

    @staticmethod
    def get_reconnaissance_commands(path: Path) -> dict[str, str]:
        """Get bash commands for Phase 1: Reconnaissance.

        Args:
            path: Path to analyze

        Returns:
            Dictionary of command names to bash commands
        """
        exclude = "-path '*/node_modules/*' -o -path '*/.git/*' -o -path '*/__pycache__/*' -o -path '*/venv/*' -o -path '*/build/*' -o -path '*/dist/*'"

        return {
            "total_files": f"find {path} -type f -not \\( {exclude} \\) | wc -l",
            "total_dirs": f"find {path} -type d -not \\( {exclude} \\) | wc -l",
            "total_size": f"du -sh {path}",
            "python_files": f"find {path} -name '*.py' -not \\( {exclude} \\) | wc -l",
            "js_files": f"find {path} -name '*.js' -not \\( {exclude} \\) | wc -l",
            "ts_files": f"find {path} -name '*.ts' -not \\( {exclude} \\) | wc -l",
            "go_files": f"find {path} -name '*.go' -not \\( {exclude} \\) | wc -l",
            "rust_files": f"find {path} -name '*.rs' -not \\( {exclude} \\) | wc -l",
            "md_files": f"find {path} -name '*.md' -not \\( {exclude} \\) | wc -l",
        }

    @staticmethod
    def get_prioritization_commands(path: Path) -> dict[str, str]:
        """Get bash commands for Phase 2: Prioritization.

        Args:
            path: Path to analyze

        Returns:
            Dictionary of command names to bash commands
        """
        exclude = "-not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/__pycache__/*'"

        return {
            # Priority 1: Documentation
            "find_readme": f"find {path} -maxdepth 1 -iname 'README*' {exclude}",
            "find_contributing": f"find {path} -maxdepth 1 -iname 'CONTRIBUTING*' {exclude}",
            "find_docs_dir": f"find {path} -maxdepth 2 -name 'docs' -type d {exclude}",
            "find_md_files": f"find {path} -maxdepth 2 -name '*.md' {exclude} | head -10",

            # Priority 2: Configuration
            "find_package_json": f"find {path} -maxdepth 2 -name 'package.json' {exclude}",
            "find_requirements": f"find {path} -maxdepth 2 -name 'requirements.txt' {exclude}",
            "find_cargo_toml": f"find {path} -maxdepth 2 -name 'Cargo.toml' {exclude}",
            "find_go_mod": f"find {path} -maxdepth 2 -name 'go.mod' {exclude}",
            "find_dockerfile": f"find {path} -maxdepth 2 -name 'Dockerfile' {exclude}",
            "find_makefile": f"find {path} -maxdepth 2 -name 'Makefile' {exclude}",
        }

    @staticmethod
    def format_scan_strategy(file_count: int) -> dict[str, Any]:
        """Determine scan strategy based on file count.

        Args:
            file_count: Total number of files

        Returns:
            Strategy configuration
        """
        if file_count < 500:
            return {
                "type": "detailed",
                "tree_depth": 4,
                "read_docs": "all",
                "read_configs": "all",
                "read_entry_points": "all",
                "read_core": 10,
                "read_tests": 5,
                "grep_limit": 50,
                "estimated_time": "5-10s",
                "target_tokens": "4000-5000",
            }
        elif file_count < 5000:
            return {
                "type": "balanced",
                "tree_depth": 3,
                "read_docs": 5,
                "read_configs": 5,
                "read_entry_points": 3,
                "read_core": 5,
                "read_tests": 2,
                "grep_limit": 30,
                "estimated_time": "10-20s",
                "target_tokens": "3000-4000",
            }
        elif file_count < 50000:
            return {
                "type": "selective",
                "tree_depth": 2,
                "read_docs": 3,
                "read_configs": 3,
                "read_entry_points": 2,
                "read_core": 3,
                "read_tests": 0,
                "grep_limit": 15,
                "estimated_time": "15-30s",
                "target_tokens": "2000-3000",
            }
        else:
            return {
                "type": "structural",
                "tree_depth": 1,
                "read_docs": 1,
                "read_configs": 1,
                "read_entry_points": 1,
                "read_core": 0,
                "read_tests": 0,
                "grep_limit": 5,
                "estimated_time": "20-40s",
                "target_tokens": "1500-2000",
            }
