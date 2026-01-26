"""PRD Agent - Generates PRD from feature descriptions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from swecli.models.config import AppConfig
from swecli.ralph.models.prd import RalphPRD


PRD_GENERATION_PROMPT = """You are a product manager creating a PRD (Product Requirements Document) for a software feature.

Given the feature description below, create a structured PRD with user stories.

## Feature Description
{description}

## Requirements

Create a PRD with:
1. A descriptive project name
2. 3-6 user stories that break down the feature into implementable chunks
3. Each story should have clear acceptance criteria
4. Stories should be ordered by priority (1 = highest priority, implement first)

## Output Format

Return ONLY valid JSON in this exact format:
```json
{{
  "project": "Project Name",
  "branchName": "ralph/feature-slug",
  "description": "High-level description of the feature",
  "userStories": [
    {{
      "id": "US-001",
      "title": "Short descriptive title",
      "description": "As a [user], I want [feature] so that [benefit]",
      "acceptanceCriteria": [
        "Criterion 1",
        "Criterion 2"
      ],
      "priority": 1,
      "passes": false,
      "notes": ""
    }}
  ]
}}
```

## Guidelines

- Keep stories small and focused (1-2 hours of work each)
- Order stories so dependencies come first
- Make acceptance criteria testable and specific
- Include technical criteria like "typecheck passes" where appropriate
- The branch name should be `ralph/` followed by a kebab-case slug

Return ONLY the JSON, no other text.
"""


class PRDAgent:
    """Agent for generating PRDs from feature descriptions."""

    def __init__(self, config: AppConfig, working_dir: Path):
        """Initialize PRD agent.

        Args:
            config: Application configuration
            working_dir: Working directory for the project
        """
        self.config = config
        self.working_dir = working_dir

    def generate_prd(
        self,
        description: str,
        branch_name: Optional[str] = None,
    ) -> RalphPRD:
        """Generate a PRD from a feature description.

        Args:
            description: Feature description
            branch_name: Optional branch name override

        Returns:
            Generated RalphPRD

        Raises:
            ValueError: If PRD generation fails
        """
        from swecli.core.agents.components import (
            create_http_client,
            build_max_tokens_param,
            build_temperature_param,
        )

        # Build the prompt
        prompt = PRD_GENERATION_PROMPT.format(description=description)

        # Call LLM
        http_client = create_http_client(self.config)

        payload = {
            "model": self.config.model,
            "messages": [
                {"role": "user", "content": prompt},
            ],
            **build_temperature_param(self.config.model, 0.7),
            **build_max_tokens_param(self.config.model, 4096),
        }

        result = http_client.post_json(payload)

        if not result.success or result.response is None:
            raise ValueError(f"LLM call failed: {result.error}")

        if result.response.status_code != 200:
            raise ValueError(f"API error {result.response.status_code}: {result.response.text}")

        response_data = result.response.json()
        content = response_data["choices"][0]["message"]["content"]

        # Parse the JSON from the response
        prd_data = self._extract_json(content)

        # Override branch name if provided
        if branch_name:
            prd_data["branchName"] = branch_name

        # Validate and return
        return RalphPRD.model_validate(prd_data)

    def _extract_json(self, content: str) -> dict:
        """Extract JSON from LLM response.

        Args:
            content: LLM response content

        Returns:
            Parsed JSON dict

        Raises:
            ValueError: If JSON extraction fails
        """
        # Try to find JSON in code blocks
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", content, re.DOTALL)
        if json_match:
            json_str = json_match.group(1).strip()
        else:
            # Try to parse the entire content as JSON
            json_str = content.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Failed to parse PRD JSON: {e}\nContent: {content[:500]}") from e

    def _generate_branch_name(self, description: str) -> str:
        """Generate a branch name from the description.

        Args:
            description: Feature description

        Returns:
            Branch name like 'ralph/feature-slug'
        """
        # Take first few words, slugify
        words = description.lower().split()[:4]
        slug = "-".join(re.sub(r"[^a-z0-9]", "", w) for w in words if w)
        return f"ralph/{slug}"
