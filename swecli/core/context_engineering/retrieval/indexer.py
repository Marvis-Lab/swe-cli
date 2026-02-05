"""Codebase indexer for generating concise OPENCLI.md summaries."""

from __future__ import annotations

import fnmatch
import json
import os
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
        ".idea",
        ".vscode",
    }

    def __init__(self, working_dir: Optional[Path] = None) -> None:
        self.working_dir = Path(working_dir or Path.cwd())
        self.token_monitor = ContextTokenMonitor()
        self.target_tokens = 3000
        self.file_count = 0
        self.structure_lines: List[str] = []
        self.key_files_found: Dict[str, List[Path]] = {
            "Main": [],
            "Config": [],
            "Tests": [],
            "Docs": [],
        }

    def generate_index(self, max_tokens: int = 3000) -> str:
        self._walk_and_collect()

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

    def _walk_and_collect(self) -> None:
        """Walk the directory tree to collect stats, structure, and key files."""
        self.file_count = 0
        self.structure_lines = ["## Structure\n", "```"]
        # Reset key files
        for k in self.key_files_found:
            self.key_files_found[k] = []

        key_patterns = {
            "Main": ["main.py", "index.js", "app.py", "server.py", "__init__.py"],
            "Config": ["setup.py", "package.json", "pyproject.toml", "requirements.txt", "Dockerfile"],
            "Tests": ["test_*.py", "*_test.py", "tests", "spec"],  # removed trailing slash for fnmatch
            "Docs": ["README.md", "CHANGELOG.md", "docs"],  # removed trailing slash for fnmatch
        }

        try:
            for root, dirs, files in os.walk(self.working_dir):
                # Prune ignored directories
                dirs[:] = [d for d in dirs if d not in self.IGNORED_DIRS]

                # Calculate depth
                rel_path = Path(root).relative_to(self.working_dir)
                if str(rel_path) == ".":
                    depth = 0
                else:
                    depth = len(rel_path.parts)

                # Structure Generation (limit depth to 2)
                if depth <= 2:
                    indent = "  " * depth
                    if depth > 0:
                        self.structure_lines.append(f"{indent}{Path(root).name}/")

                    # Add files to structure if depth < 2 (so files are at depth 1 or 2)
                    # Actually tree -L 2 shows files at level 2.
                    if depth < 2:
                        file_indent = "  " * (depth + 1)
                        for f in files:
                            self.structure_lines.append(f"{file_indent}{f}")

                # File counting
                self.file_count += len(files)

                # Key Files Detection
                # Check files
                for f in files:
                    for category, patterns in key_patterns.items():
                        for pattern in patterns:
                            if fnmatch.fnmatch(f, pattern):
                                f_path = Path(root) / f
                                if f_path not in self.key_files_found[category]:
                                    self.key_files_found[category].append(f_path)

                # Check directories (for patterns like 'tests', 'docs')
                for d in dirs:
                    for category, patterns in key_patterns.items():
                        for pattern in patterns:
                            if fnmatch.fnmatch(d, pattern):
                                d_path = Path(root) / d
                                if d_path not in self.key_files_found[category]:
                                    self.key_files_found[category].append(d_path)

        except Exception:
            self.structure_lines.append("(Unable to generate structure)")

        self.structure_lines.append("```")

    def _generate_overview(self) -> str:
        lines = ["## Overview\n"]
        lines.append(f"**Total Files:** {self.file_count}")

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
        output = "\n".join(self.structure_lines)
        if len(output) > 1500:
            output = "\n".join(output.split("\n")[:30]) + "\n... (truncated)\n```"
        return output

    def _generate_key_files(self) -> str:
        lines = ["## Key Files\n"]

        for category, found in self.key_files_found.items():
            if found:
                lines.append(f"\n### {category}")
                # Sort by path length to prefer top-level files
                sorted_files = sorted(found, key=lambda p: len(p.parts))
                for f in sorted_files[:5]:
                    try:
                        rel_path = f.relative_to(self.working_dir)
                        lines.append(f"- `{rel_path}`")
                    except ValueError:
                        continue # Should not happen if logic is correct

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

    def _compress_content(self, content: str, max_tokens: int) -> str:
        paragraphs = content.split("\n\n")
        compressed: List[str] = []
        for paragraph in paragraphs:
            compressed.append(paragraph)
            tokens = self.token_monitor.count_tokens("\n\n".join(compressed))
            if tokens >= max_tokens:
                break
        return "\n\n".join(compressed)
