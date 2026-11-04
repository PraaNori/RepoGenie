"""Legacy validation utility, forwards to github_url parser."""
from typing import Optional, Tuple
from .github_url import (
    GitHubURLValidationError,
    parse_and_validate_github_url,
)

def parse_github_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Parses a GitHub URL into (owner, repo_name).
    Returns None if URL is invalid.
    """
    try:
        parsed = parse_and_validate_github_url(url)
        return parsed.owner, parsed.repo
    except (GitHubURLValidationError, Exception):
        return None
