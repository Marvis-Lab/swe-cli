"""Codebase indexer for generating concise OPENCLI.md summaries."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Set

from .token_monitor import ContextTokenMonitor


class CodebaseIndexer:
    """Generate concise codebase summaries for context."""

    IGNORED_DIRS = {
        "node_modules",
        "__pycache__",
        ".git",
        "venv",
        "build",
        "dist",
        ".venv",
        ".idea",
        ".vscode",
        ".mypy_cache",
        ".pytest_cache",
        "site-packages",
    }

    def __init__(self, working_dir: Optional[Path] = None) -> None:
        self.working_dir = Path(working_dir or Path.cwd())
        self.token_monitor = ContextTokenMonitor()
        self.target_tokens = 3000
        self._file_cache: List[Path] = []
        self._dir_cache: List[Path] = []
        self._children_map: Dict[Path, List[Path]] = {}
        self._cache_populated = False

    def _populate_cache(self) -> None:
        if self._cache_populated:
            return

        self._file_cache = []
        self._dir_cache = []
        self._children_map = {}

        for root, dirs, files in os.walk(self.working_dir):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS]

            rel_root = Path(root).relative_to(self.working_dir)

            if rel_root not in self._children_map:
                self._children_map[rel_root] = []

            for d in dirs:
                rel_dir = rel_root / d
                self._dir_cache.append(rel_dir)
                self._children_map[rel_root].append(rel_dir)

            for f in files:
                rel_file = rel_root / f
                self._file_cache.append(rel_file)
                self._children_map[rel_root].append(rel_file)

        self._cache_populated = True

    def generate_index(self, max_tokens: int = 3000) -> str:
        self._populate_cache()

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

        # Use cached file count
        file_count = len(self._file_cache)
        lines.append(f"**Total Files:** {file_count}")

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

        tree_lines = ["."]
        root_children = self._get_sorted_children(Path("."))

        for i, child in enumerate(root_children):
            is_last = (i == len(root_children) - 1)
            prefix = "└── " if is_last else "├── "
            tree_lines.append(f"{prefix}{child.name}")

            if self._is_dir(child):
                sub_children = self._get_sorted_children(child)
                for j, sub_child in enumerate(sub_children):
                    is_last_sub = (j == len(sub_children) - 1)
                    sub_prefix = "    " if is_last else "│   "
                    connector = "└── " if is_last_sub else "├── "
                    tree_lines.append(f"{sub_prefix}{connector}{sub_child.name}")

        tree_output = "\n".join(tree_lines)
        if len(tree_output) > 1500:
             tree_output = "\n".join(tree_output.split("\n")[:30]) + "\n... (truncated)"

        lines.append(tree_output)
        lines.append("```")
        return "\n".join(lines)

    def _is_dir(self, path: Path) -> bool:
        if path == Path("."):
            return True
        return path in self._dir_cache

    def _get_sorted_children(self, parent: Path) -> List[Path]:
        children = self._children_map.get(parent, [])
        # Sort directories first, then files, then alphabetically
        return sorted(children, key=lambda p: (not self._is_dir(p), p.name.lower()))

    def _generate_key_files(self) -> str:
        lines = ["## Key Files\n"]
        key_patterns = {
            "Main": ["main.py", "index.js", "app.py", "server.py", "__init__.py"],
            "Config": ["setup.py", "package.json", "pyproject.toml", "requirements.txt", "Dockerfile"],
            "Tests": ["test_*.py", "*_test.py", "tests", "spec"],
            "Docs": ["README.md", "CHANGELOG.md", "docs"],
        }

        for category, patterns in key_patterns.items():
            found = self._find_files(patterns)
            if found:
                lines.append(f"\n### {category}")
                for f in found[:5]:
                    lines.append(f"- `{f}`")

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
            p = Path(pattern)
            if p in self._file_cache:
                return self.working_dir / p
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
            if any(Path(f) in self._file_cache for f in files):
                return project_type
        return None

    def _find_files(self, patterns: List[str]) -> List[Path]:
        matches: Set[Path] = set()
        for pattern in patterns:
            # Check files
            for f in self._file_cache:
                # Use standard match AND match with ** prefix to simulate glob-like behavior for filename matching
                if f.match(pattern) or f.match(f"**/{pattern}"):
                    matches.add(f)
            # Check dirs
            for d in self._dir_cache:
                if d.match(pattern) or d.match(f"**/{pattern}"):
                    matches.add(d)
        return sorted(list(matches))

    def _compress_content(self, content: str, max_tokens: int) -> str:
        paragraphs = content.split("\n\n")
        compressed: List[str] = []
        for paragraph in paragraphs:
            compressed.append(paragraph)
            tokens = self.token_monitor.count_tokens("\n\n".join(compressed))
            if tokens >= max_tokens:
                break
        return "\n\n".join(compressed)
