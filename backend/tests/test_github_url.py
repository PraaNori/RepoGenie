"""
Unit tests for GitHub URL processing and validation utility.
"""
from unittest.mock import MagicMock, patch
import httpx
import pytest
from app.utils.github_url import (
    GitHubURLValidationError,
    ParsedGitHubRepo,
    RepositoryAccessibilityError,
    RepositoryNotFoundError,
    is_valid_github_url,
    parse_and_validate_github_url,
    verify_repository_accessible,
)

def test_valid_standard_github_url():
    parsed = parse_and_validate_github_url("https://github.com/fastapi/fastapi")
    assert isinstance(parsed, ParsedGitHubRepo)
    assert parsed.owner == "fastapi"
    assert parsed.repo == "fastapi"
    assert parsed.canonical_url == "https://github.com/fastapi/fastapi"
    assert parsed.clone_url == "https://github.com/fastapi/fastapi.git"
    assert is_valid_github_url("https://github.com/fastapi/fastapi") is True

def test_valid_url_ending_in_git():
    parsed = parse_and_validate_github_url("https://github.com/facebook/react.git")
    assert parsed.owner == "facebook"
    assert parsed.repo == "react"
    assert parsed.canonical_url == "https://github.com/facebook/react"
    assert parsed.clone_url == "https://github.com/facebook/react.git"

def test_valid_url_with_trailing_slash():
    parsed = parse_and_validate_github_url("https://github.com/pallets/flask/")
    assert parsed.owner == "pallets"
    assert parsed.repo == "flask"
    assert parsed.canonical_url == "https://github.com/pallets/flask"

def test_valid_url_with_query_and_fragment():
    parsed = parse_and_validate_github_url(
        "https://github.com/psf/requests.git?tab=readme-ov-file#installation"
    )
    assert parsed.owner == "psf"
    assert parsed.repo == "requests"
    assert parsed.canonical_url == "https://github.com/psf/requests"

def test_valid_url_with_www_and_http():
    parsed = parse_and_validate_github_url("http://www.github.com/expressjs/express")
    assert parsed.owner == "expressjs"
    assert parsed.repo == "express"
    assert parsed.canonical_url == "https://github.com/expressjs/express"

def test_invalid_urls():
    for invalid in ["", "   ", "not-a-url", "htp://github.com/owner/repo"]:
        with pytest.raises(GitHubURLValidationError):
            parse_and_validate_github_url(invalid)
        assert is_valid_github_url(invalid) is False

def test_non_github_urls():
    for non_gh in [
        "https://gitlab.com/owner/repository",
        "https://bitbucket.org/owner/repository",
        "https://google.com/search?q=test",
    ]:
        with pytest.raises(GitHubURLValidationError) as exc:
            parse_and_validate_github_url(non_gh)
        assert "Not a GitHub repository URL" in str(exc.value)

def test_missing_repository_name():
    for missing in ["https://github.com", "https://github.com/"]:
        with pytest.raises(GitHubURLValidationError) as exc:
            parse_and_validate_github_url(missing)
        assert "must include both owner and repository name" in str(exc.value)

def test_github_profile_urls():
    for profile in ["https://github.com/torvalds", "https://github.com/torvalds/"]:
        with pytest.raises(GitHubURLValidationError) as exc:
            parse_and_validate_github_url(profile)
        assert "profile or organization without a repository" in str(exc.value)

def test_github_organization_urls():
    for org in ["https://github.com/orgs/myorg", "https://github.com/organizations/myorg"]:
        with pytest.raises(GitHubURLValidationError) as exc:
            parse_and_validate_github_url(org)
        assert "reserved GitHub" in str(exc.value) or "without a repository" in str(exc.value)

def test_deep_unsupported_urls():
    for deep in [
        "https://github.com/fastapi/fastapi/pull/123",
        "https://github.com/fastapi/fastapi/tree/main/src",
        "https://github.com/fastapi/fastapi/issues",
    ]:
        with pytest.raises(GitHubURLValidationError) as exc:
            parse_and_validate_github_url(deep)
        assert "Unsupported deep GitHub URL" in str(exc.value)

def test_verify_repository_accessible_success():
    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_get.return_value = mock_resp

        assert verify_repository_accessible("https://github.com/fastapi/fastapi") is True

def test_verify_repository_accessible_not_found():
    with patch("httpx.Client.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_get.return_value = mock_resp

        with pytest.raises(RepositoryNotFoundError):
            verify_repository_accessible("https://github.com/nonexistent/repo")

def test_verify_repository_accessible_network_error():
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = httpx.ConnectError("Failed to connect")

        with pytest.raises(RepositoryAccessibilityError):
            verify_repository_accessible("https://github.com/fastapi/fastapi")
