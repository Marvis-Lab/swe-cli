"""Codebase indexer for generating concise OPENCLI.md summaries."""

from __future__ import annotations

import json
import os
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional

from .token_monitor import ContextTokenMonitor


IGNORED_DIRS = {
    "node_modules",
    "__pycache__",
    ".git",
    "venv",
    ".venv",
    "build",
    "dist",
    "target",
    ".idea",
    ".vscode",
    "coverage",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
}


class CodebaseIndexer:
    """Generate concise codebase summaries for context."""

    def __init__(self, working_dir: Optional[Path] = None) -> None:
        self.working_dir = Path(working_dir or Path.cwd())
        self.token_monitor = ContextTokenMonitor()
        self.target_tokens = 3000

    def generate_index(self, max_tokens: int = 3000) -> str:
        sections = []
        sections.append(f"# {self.working_dir.name}\n")
        sections.append(self._generate_overview())
        sections.append(self._generate_structure())
        sections.append(self._generate_key_files())

        deps = self._generate_dependencies()
        if deps:
            sections.append(deps)

        content = "\n\n".join(sections)
        tokens = self.token_monitor.count_tokens(content)
        if tokens > max_tokens:
            content = self._compress_content(content, max_tokens)
        return content

    def _generate_overview(self) -> str:
        lines = ["## Overview\n"]
        file_count = 0
        try:
            for root, dirs, files in os.walk(self.working_dir):
                # Modify dirs in-place to skip ignored directories
                dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                file_count += len(files)
            lines.append(f"**Total Files:** {file_count}")
        except Exception:
            pass

        readme_path = self._find_readme()
        if readme_path:
            readme_content = readme_path.read_text(errors="ignore")
            first_para = self._extract_description(readme_content)
            if first_para:
                lines.append(f"\n{first_para}")

        project_type = self._detect_project_type()
        if project_type:
            lines.append(f"\n**Type:** {project_type}")

        return "\n".join(lines)

    def _generate_structure(self) -> str:
        lines = ["## Structure\n", "```"]
        try:
            tree_output = self._generate_tree_string(max_depth=2)
            if len(tree_output) > 1500:
                tree_output = "\n".join(tree_output.split("\n")[:30]) + "\n... (truncated)"
            lines.append(tree_output)
        except Exception:
            lines.append("(Unable to generate structure)")

        lines.append("```")
        return "\n".join(lines)

    def _generate_tree_string(self, max_depth: int = 2) -> str:
        """Generate a tree-like directory structure string."""
        output = ["."]

        # Helper to recursively build tree
        def _build_tree(directory: Path, prefix: str, depth: int):
            if depth > max_depth:
                return

            try:
                entries = sorted([
                    p for p in directory.iterdir()
                    if p.name not in IGNORED_DIRS
                ], key=lambda x: (x.is_file(), x.name.lower()))
            except PermissionError:
                return

            for i, entry in enumerate(entries):
                is_last = (i == len(entries) - 1)
                connector = "└── " if is_last else "├── "
                output.append(f"{prefix}{connector}{entry.name}")

                if entry.is_dir() and depth < max_depth:
                    extension = "    " if is_last else "│   "
                    _build_tree(entry, prefix + extension, depth + 1)

        _build_tree(self.working_dir, "", 1)
        return "\n".join(output)

    def _generate_key_files(self) -> str:
        lines = ["## Key Files\n"]
        key_patterns = {
            "Main": ["main.py", "index.js", "app.py", "server.py", "__init__.py"],
            "Config": ["setup.py", "package.json", "pyproject.toml", "requirements.txt", "Dockerfile"],
            "Tests": ["test_*.py", "*_test.py", "tests/", "spec/"],
            "Docs": ["README.md", "CHANGELOG.md", "docs/"],
        }

        for category, patterns in key_patterns.items():
            found = self._find_files(patterns)
            if found:
                lines.append(f"\n### {category}")
                for f in found[:5]:
                    rel_path = f.relative_to(self.working_dir)
                    lines.append(f"- `{rel_path}`")

        return "\n".join(lines)

    def _generate_dependencies(self) -> Optional[str]:
        deps: Dict[str, List[str]] = {}

        req_file = self.working_dir / "requirements.txt"
        if req_file.exists():
            content = req_file.read_text(errors="ignore")
            deps["Python"] = [
                line.strip()
                for line in content.split("\n")
                if line.strip() and not line.startswith("#")
            ][:10]

        package_json = self.working_dir / "package.json"
        if package_json.exists():
            try:
                data = json.loads(package_json.read_text())
                node_deps = list(data.get("dependencies", {}).keys())[:10]
                if node_deps:
                    deps["Node"] = node_deps
            except Exception:
                pass

        if not deps:
            return None

        lines = ["## Dependencies\n"]
        for tech, dep_list in deps.items():
            lines.append(f"\n### {tech}")
            for dep in dep_list:
                lines.append(f"- {dep}")
            if len(dep_list) >= 10:
                lines.append("- *(and more...)*")

        return "\n".join(lines)

    def _find_readme(self) -> Optional[Path]:
        for pattern in ["README.md", "README.rst", "README.txt", "README"]:
            readme = self.working_dir / pattern
            if readme.exists():
                return readme
        return None

    def _extract_description(self, content: str, max_length: int = 300) -> Optional[str]:
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        if not paragraphs:
            return None
        description = paragraphs[0]
        if len(description) > max_length:
            description = description[: max_length - 3] + "..."
        return description

    def _detect_project_type(self) -> Optional[str]:
        indicators = {
            "Python": ["pyproject.toml", "requirements.txt", "setup.py", "Pipfile"],
            "Node": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
            "Rust": ["Cargo.toml"],
            "Go": ["go.mod"],
            "Java": ["pom.xml", "build.gradle"],
        }
        for project_type, files in indicators.items():
            if any((self.working_dir / f).exists() for f in files):
                return project_type
        return None

    def _find_files(self, patterns: List[str]) -> List[Path]:
        matches: List[Path] = []
        for pattern in patterns:
            # Handle directory patterns ending in /
            if pattern.endswith("/"):
                # Just check if directory exists in the walk
                # But we need to search recursively
                 for root, dirs, files in os.walk(self.working_dir):
                    dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                    dir_name = pattern.rstrip("/")
                    if dir_name in dirs:
                        matches.append(Path(root) / dir_name)
            else:
                # File pattern
                for root, dirs, files in os.walk(self.working_dir):
                    dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
                    for filename in fnmatch.filter(files, pattern):
                        matches.append(Path(root) / filename)

        # Deduplicate matches
        return list(set(matches))

    def _compress_content(self, content: str, max_tokens: int) -> str:
        paragraphs = content.split("\n\n")
        compressed: List[str] = []
        for paragraph in paragraphs:
            compressed.append(paragraph)
            tokens = self.token_monitor.count_tokens("\n\n".join(compressed))
            if tokens >= max_tokens:
                break
        return "\n\n".join(compressed)
