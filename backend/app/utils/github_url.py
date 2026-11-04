"""
GitHub URL parsing, validation, and accessibility verification utilities.
"""
import re
import urllib.parse
from typing import Optional
import httpx
from pydantic import BaseModel

class GitHubURLValidationError(ValueError):
    """Raised when a provided URL is not a valid, supported GitHub repository URL."""
    pass

class RepositoryNotFoundError(Exception):
    """Raised when a repository does not exist or is private on GitHub."""
    pass

class RepositoryAccessibilityError(Exception):
    """Raised when GitHub cannot be contacted to verify repository status."""
    pass

class ParsedGitHubRepo(BaseModel):
    owner: str
    repo: str
    canonical_url: str
    clone_url: str

# Reserved GitHub root path segments that cannot be repository owners
RESERVED_GITHUB_PATHS = {
    "settings",
    "pricing",
    "features",
    "marketplace",
    "explore",
    "topics",
    "trending",
    "collections",
    "events",
    "sponsors",
    "orgs",
    "organizations",
    "login",
    "join",
    "logout",
    "about",
    "contact",
    "security",
    "site",
    "notifications",
    "dashboard",
    "pulls",
    "issues",
}

# GitHub username: 1-39 alphanumeric characters or single hyphens, not starting/ending with hyphen
GITHUB_OWNER_PATTERN = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9]|-(?=[a-zA-Z0-9])){0,38}$")

# GitHub repository name: 1-100 alphanumeric, hyphens, underscores, or dots (cannot be '.' or '..')
GITHUB_REPO_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{1,100}$")

def parse_and_validate_github_url(raw_url: str) -> ParsedGitHubRepo:
    """
    Parses and strictly validates a GitHub repository URL.

    Supported formats:
        - https://github.com/owner/repository
        - https://github.com/owner/repository/
        - https://github.com/owner/repository.git
        - http://... (normalized to https)
        - URLs with query parameters or fragments (safely stripped)

    Rejects:
        - Non-string or empty inputs
        - Non-GitHub hosts (e.g. gitlab.com, bitbucket.org)
        - Single-segment profile/organization URLs (e.g. https://github.com/owner)
        - Deep paths (e.g. https://github.com/owner/repo/pull/1)
        - Reserved GitHub system paths
        - Invalid characters in owner or repository name

    Returns:
        ParsedGitHubRepo containing owner, repo, canonical_url, and clone_url.

    Raises:
        GitHubURLValidationError: If URL fails validation with a clear reason.
    """
    if not raw_url or not isinstance(raw_url, str):
        raise GitHubURLValidationError("Repository URL must be a non-empty string.")

    cleaned = raw_url.strip()
    if not cleaned:
        raise GitHubURLValidationError("Repository URL cannot be blank.")

    try:
        parsed = urllib.parse.urlparse(cleaned)
    except Exception as exc:
        raise GitHubURLValidationError(f"Malformed URL structure: {exc}") from exc

    # Protocol check
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise GitHubURLValidationError(
            f"Unsupported URL protocol '{parsed.scheme}'. Only HTTP and HTTPS GitHub URLs are supported."
        )

    # Host check
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc != "github.com":
        raise GitHubURLValidationError(
            f"Not a GitHub repository URL. Expected 'github.com', got '{parsed.netloc}'."
        )

    # Path segments check (ignoring query parameters and fragments)
    path_segments = [seg for seg in parsed.path.strip("/").split("/") if seg]

    if len(path_segments) == 0:
        raise GitHubURLValidationError("GitHub URL must include both owner and repository name.")

    if len(path_segments) == 1:
        segment = path_segments[0]
        if segment.lower() in RESERVED_GITHUB_PATHS:
            raise GitHubURLValidationError(f"Invalid repository path: '{segment}' is a reserved GitHub page.")
        raise GitHubURLValidationError(
            f"Provided URL is a GitHub profile or organization without a repository: '{cleaned}'."
        )

    if len(path_segments) > 2:
        raise GitHubURLValidationError(
            f"Unsupported deep GitHub URL: '{cleaned}'. Only top-level repository URLs are accepted "
            "(e.g., https://github.com/owner/repository)."
        )

    owner, repo_raw = path_segments[0], path_segments[1]

    # Check reserved routes
    if owner.lower() in RESERVED_GITHUB_PATHS:
        raise GitHubURLValidationError(f"Invalid repository owner: '{owner}' is a reserved GitHub route.")

    # Strip .git suffix if present
    if repo_raw.endswith(".git"):
        repo = repo_raw[:-4]
    else:
        repo = repo_raw

    # Validate owner name format
    if not GITHUB_OWNER_PATTERN.match(owner):
        raise GitHubURLValidationError(
            f"Invalid GitHub owner/organization name: '{owner}'. "
            "Must be 1-39 alphanumeric characters or hyphens (not starting/ending with hyphen)."
        )

    # Validate repository name format
    if not repo or repo in (".", "..") or not GITHUB_REPO_PATTERN.match(repo):
        raise GitHubURLValidationError(
            f"Invalid repository name: '{repo_raw}'. "
            "Must be 1-100 characters containing alphanumeric, hyphens, underscores, or periods."
        )

    canonical_url = f"https://github.com/{owner}/{repo}"
    clone_url = f"https://github.com/{owner}/{repo}.git"

    return ParsedGitHubRepo(
        owner=owner,
        repo=repo,
        canonical_url=canonical_url,
        clone_url=clone_url,
    )

def is_valid_github_url(url: str) -> bool:
    """Convenience boolean helper for URL validity check."""
    try:
        parse_and_validate_github_url(url)
        return True
    except GitHubURLValidationError:
        return False

def verify_repository_accessible(canonical_url: str, timeout: float = 8.0) -> bool:
    """
    Verifies that a repository exists and is publicly accessible on GitHub.
    Uses httpx to check the repository URL.

    Returns:
        True if repository is accessible (HTTP 200).

    Raises:
        RepositoryNotFoundError: If repository returns HTTP 404 (does not exist or is private).
        RepositoryAccessibilityError: If network error or non-200/404 response.
    """
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(
                canonical_url,
                headers={"User-Agent": "RepoGenie-Bot/0.2.0 (Repository Ingestion Verifier)"},
            )
            if response.status_code == 200:
                return True
            if response.status_code == 404:
                raise RepositoryNotFoundError(
                    f"Repository '{canonical_url}' was not found or is private on GitHub."
                )
            raise RepositoryAccessibilityError(
                f"GitHub returned unexpected status code {response.status_code} for '{canonical_url}'."
            )
    except httpx.TimeoutException as exc:
        raise RepositoryAccessibilityError(
            f"Timed out while attempting to contact GitHub for '{canonical_url}'."
        ) from exc
    except httpx.RequestError as exc:
        raise RepositoryAccessibilityError(
            f"Network error while connecting to GitHub: {exc}"
        ) from exc
