"""Codebase indexer for generating concise SWECLI.md summaries."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from .token_monitor import ContextTokenMonitor


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
            result = subprocess.run(
                [
                    "tree",
                    "-L",
                    "2",
                    "-I",
                    "node_modules|__pycache__|.git|venv|build|dist",
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

        scanned_files = self._scan_key_files(key_patterns)

        for category, found in scanned_files.items():
            if found:
                lines.append(f"\n### {category}")
                # Sort for deterministic output
                found.sort(key=lambda p: str(p))
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

    def _scan_key_files(self, key_patterns: Dict[str, List[str]]) -> Dict[str, List[Path]]:
        results: Dict[str, List[Path]] = {k: [] for k in key_patterns}
        ignored_dirs = {
            "node_modules", "__pycache__", ".git", "venv", "build", "dist", ".venv", ".idea", ".vscode"
        }

        # Split patterns into file and dir patterns
        cat_file_patterns = {}
        cat_dir_patterns = {}

        for cat, patterns in key_patterns.items():
            cat_file_patterns[cat] = []
            cat_dir_patterns[cat] = []
            for p in patterns:
                if p.endswith("/"):
                    cat_dir_patterns[cat].append(p.rstrip("/"))
                else:
                    cat_file_patterns[cat].append(p)

        for root, dirs, files in os.walk(self.working_dir):
            dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith('.')]

            root_path = Path(root)

            # Check directories
            for d in dirs:
                for cat, patterns in cat_dir_patterns.items():
                    if d in patterns:
                         results[cat].append(root_path / d)

            # Check files
            for f in files:
                for cat, patterns in cat_file_patterns.items():
                    for p in patterns:
                        if fnmatch.fnmatch(f, p):
                            results[cat].append(root_path / f)

        return results

    def _basic_structure(self) -> str:
        try:
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
