"""Utility functions for RepoGenie."""
import re
from typing import Optional, Tuple

GITHUB_URL_PATTERN = re.compile(
    r"^https?://github\.com/(?P<owner>[a-zA-Z0-9_.-]+)/(?P<repo>[a-zA-Z0-9_.-]+?)(?:\.git)?/?$"
)

def parse_github_url(url: str) -> Optional[Tuple[str, str]]:
    """
    Parses a GitHub URL into (owner, repo_name).
    Returns None if URL is invalid.
    """
    cleaned = url.strip()
    match = GITHUB_URL_PATTERN.match(cleaned)
    if not match:
        return None
    owner = match.group("owner")
    repo = match.group("repo")
    return owner, repo
