"""Codebase indexer for generating concise OPENCLI.md summaries."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .token_monitor import ContextTokenMonitor

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
}


class CodebaseIndexer:
    """Generate concise codebase summaries for context."""

    def __init__(self, working_dir: Optional[Path] = None) -> None:
        self.working_dir = Path(working_dir or Path.cwd())
        self.token_monitor = ContextTokenMonitor()
        self.target_tokens = 3000
        self._file_cache: Optional[List[Path]] = None
        self._dir_cache: Optional[List[Path]] = None

    def generate_index(self, max_tokens: int = 3000) -> str:
        # Pre-scan codebase to populate caches
        self._scan_codebase()

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

    def _scan_codebase(self) -> None:
        """Walk the directory once and cache files and directories."""
        self._file_cache = []
        self._dir_cache = []

        for root, dirs, files in os.walk(self.working_dir):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

            root_path = Path(root)
            self._dir_cache.append(root_path)
            for f in files:
                self._file_cache.append(root_path / f)

    def _generate_overview(self) -> str:
        lines = ["## Overview\n"]

        # Use cached file count if available, otherwise fallback (though _scan_codebase should be called)
        if self._file_cache is not None:
            file_count = len(self._file_cache)
            lines.append(f"**Total Files:** {file_count}")
        else:
             # Fallback if _scan_codebase wasn't called (shouldn't happen in normal flow)
            try:
                result = subprocess.run(
                    ["find", ".", "-type", "f"],
                    capture_output=True,
                    text=True,
                    cwd=self.working_dir,
                    timeout=5,
                )
                if result.returncode == 0:
                    file_count = len(result.stdout.strip().split("\n"))
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
            # Construct ignore pattern for tree
            ignore_pattern = "|".join(IGNORED_DIRS)
            result = subprocess.run(
                [
                    "tree",
                    "-L",
                    "2",
                    "-I",
                    ignore_pattern,
                ],
                capture_output=True,
                text=True,
                cwd=self.working_dir,
                timeout=5,
            )
            if result.returncode == 0:
                tree_output = result.stdout.strip()
                if len(tree_output) > 1500:
                    tree_output = "\n".join(tree_output.split("\n")[:30]) + "\n... (truncated)"
                lines.append(tree_output)
            else:
                lines.append(self._basic_structure())
        except FileNotFoundError:
            lines.append(self._basic_structure())
        except Exception:
            lines.append("(Unable to generate structure)")

        lines.append("```")
        return "\n".join(lines)

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
        if self._file_cache is None:
            # Fallback if _scan_codebase wasn't called
            self._scan_codebase()

        matches: List[Path] = []

        # We need to handle directory patterns like "tests/" or "spec/" differently
        # and file patterns like "*.py" or "test_*.py"

        dir_patterns = [p for p in patterns if p.endswith("/")]
        file_patterns = [p for p in patterns if not p.endswith("/")]

        if self._file_cache:
            for f in self._file_cache:
                # Check file patterns
                name = f.name
                if any(fnmatch.fnmatch(name, p) for p in file_patterns):
                    matches.append(f)
                    continue

                # Check directory patterns (simple approach: check if file is under that dir)
                # But glob(**/tests/) implies finding directories.
                # The original code used glob(**/pattern)
                # If pattern is tests/, glob finds directories named tests.

                # If the original code returned directories for patterns ending in /, we should too.
                # But _find_files return type is List[Path], usually files.
                # Let's see how it's used: "for f in found[:5]: lines.append(...)".

                # If the original glob returned directories, and we only cache files, we miss directories.
                # But _dir_cache can help.

        # Let's refine based on what glob does.
        # glob(**/tests/) finds directories.
        # glob(**/test_*.py) finds files.

        # So we should search in _dir_cache for dir patterns, and _file_cache for file patterns.

        for p in dir_patterns:
            p_clean = p.rstrip("/")
            if self._dir_cache:
                for d in self._dir_cache:
                    if fnmatch.fnmatch(d.name, p_clean):
                        matches.append(d)

        for p in file_patterns:
            if self._file_cache:
                for f in self._file_cache:
                    if fnmatch.fnmatch(f.name, p):
                        matches.append(f)

        return sorted(list(set(matches)))

    def _basic_structure(self) -> str:
        try:
             # Can we use _dir_cache and _file_cache here to generate a tree-like structure?
             # For now, sticking to existing subprocess logic but maybe it's fine as fallback.
             # Or we can improve it later.
            result = subprocess.run(
                ["ls", "-R"],
                capture_output=True,
                text=True,
                cwd=self.working_dir,
                timeout=5,
            )
            if result.returncode == 0:
                output = result.stdout.strip()
                if len(output) > 1200:
                    output = "\n".join(output.split("\n")[:40]) + "\n... (truncated)"
                return output
        except Exception:
            pass
        return "(Unable to generate structure)"

    def _compress_content(self, content: str, max_tokens: int) -> str:
        paragraphs = content.split("\n\n")
        compressed: List[str] = []
        for paragraph in paragraphs:
            compressed.append(paragraph)
            tokens = self.token_monitor.count_tokens("\n\n".join(compressed))
            if tokens >= max_tokens:
                break
        return "\n\n".join(compressed)
