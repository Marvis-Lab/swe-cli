"""Codebase indexer for generating concise SWECLI.md summaries."""

from __future__ import annotations

import json
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

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

    def generate_index(self, max_tokens: int = 3000) -> str:
        self._ensure_cache()
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

    def _ensure_cache(self) -> None:
        """Populate the file cache if it's empty."""
        if self._file_cache is not None:
            return

        self._file_cache = []
        for root, dirs, files in os.walk(self.working_dir):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]

            for file in files:
                self._file_cache.append(Path(root) / file)

    def _generate_overview(self) -> str:
        self._ensure_cache()
        lines = ["## Overview\n"]

        # Use cached file count
        if self._file_cache is not None:
            lines.append(f"**Total Files:** {len(self._file_cache)}")

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
            # We keep the subprocess call for tree as it handles visual structure well,
            # but ensure we use the same ignore list.
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
        self._ensure_cache()
        lines = ["## Key Files\n"]
        key_patterns = {
            "Main": ["main.py", "index.js", "app.py", "server.py", "__init__.py"],
            "Config": [
                "setup.py",
                "package.json",
                "pyproject.toml",
                "requirements.txt",
                "Dockerfile",
            ],
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
        self._ensure_cache()
        matches: List[Path] = []
        if self._file_cache is None:
            return matches

        for pattern in patterns:
            # If pattern ends with /, it matches directories.
            # But _file_cache only contains files.
            # Logic in original code:
            # matches.extend(self.working_dir.glob(f"**/{pattern}"))

            # If pattern is like "docs/", glob would match directories.
            # But my cache is only files.
            # The usage in _generate_key_files: "tests/", "docs/"

            # We need to filter files that are UNDER these directories.

            is_dir_pattern = pattern.endswith("/")
            clean_pattern = pattern.rstrip("/")

            for file_path in self._file_cache:
                rel_path = file_path.relative_to(self.working_dir)

                if is_dir_pattern:
                    # Check if file is inside the directory
                    # e.g. pattern "tests/", file "tests/foo.py" -> rel_path "tests/foo.py"
                    # We check if any part of the path matches clean_pattern
                    if clean_pattern in rel_path.parts:
                         matches.append(file_path)
                else:
                    # File pattern match
                    # glob matches recursively with **
                    # Here we can use match() on the path
                    if file_path.match(pattern) or file_path.match(f"**/{pattern}"):
                         matches.append(file_path)

        # Deduplicate matches while preserving order
        unique_matches = []
        seen = set()
        for m in matches:
            if m not in seen:
                unique_matches.append(m)
                seen.add(m)

        return unique_matches

    def _basic_structure(self) -> str:
        # Replaced ls -R with internal walk to be consistent (and we already have it in cache usually,
        # but _basic_structure is fallback for structure visualization)
        # But _basic_structure formats output differently than cache list.
        # Let's keep it simple and use cache if available to simulate tree?
        # Constructing a tree string from list of files is complex.
        # Let's stick to a simplified listing if tree fails.

        self._ensure_cache()
        if self._file_cache is None:
             return "(Unable to generate structure)"

        # Just list top level dirs and files and maybe one level deep
        # Or just list the first N files from cache
        lines = []
        count = 0
        for f in self._file_cache:
            rel = f.relative_to(self.working_dir)
            lines.append(str(rel))
            count += 1
            if count > 40:
                lines.append("... (truncated)")
                break
        return "\n".join(lines)

    def _compress_content(self, content: str, max_tokens: int) -> str:
        paragraphs = content.split("\n\n")
        compressed: List[str] = []
        for paragraph in paragraphs:
            compressed.append(paragraph)
            tokens = self.token_monitor.count_tokens("\n\n".join(compressed))
            if tokens >= max_tokens:
                break
        return "\n\n".join(compressed)
