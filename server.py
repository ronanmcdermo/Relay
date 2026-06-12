"""
Relay MCP server — exposes a focused set of GitHub operations as MCP tools.

Run directly over stdio; the Slack bot spawns this and speaks JSON-RPC to it.
Each tool returns a plain string formatted for display in Slack.
"""
import os
import functools
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from github import Github, Auth
from github.GithubException import GithubException
from mcp.server.fastmcp import FastMCP

load_dotenv(Path(__file__).parent / ".env")

gh = Github(auth=Auth.Token(os.environ["GITHUB_TOKEN"]))
mcp = FastMCP("relay")


def handle_github_errors(func):
    """Turn GitHub API exceptions into readable messages instead of raw tracebacks."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GithubException as e:
            msg = e.data.get("message", str(e)) if isinstance(e.data, dict) else str(e)
            return f"GitHub error ({e.status}): {msg}"
        except Exception as e:
            return f"Unexpected error: {e}"
    return wrapper


def _repo(repo_name: str):
    """Resolve a repo from 'owner/repo' or a bare 'repo' (owned by the authenticated user)."""
    if "/" in repo_name:
        return gh.get_repo(repo_name)
    return gh.get_user().get_repo(repo_name)


@mcp.tool()
@handle_github_errors
def list_repos() -> str:
    """List all repositories accessible to the authenticated GitHub user."""
    repos = gh.get_user().get_repos()
    lines = [f"- {r.full_name} ({'private' if r.private else 'public'})" for r in repos]
    return "\n".join(lines) if lines else "No repositories found."


@mcp.tool()
@handle_github_errors
def list_issues(repo_name: str, state: str = "open") -> str:
    """
    List issues for a repository.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        state: 'open', 'closed', or 'all' (default: 'open')
    """
    repo = _repo(repo_name)
    lines = [
        f"#{issue.number} [{issue.state}] {issue.title} — {issue.html_url}"
        for issue in repo.get_issues(state=state)
        if not issue.pull_request  # PRs also surface as issues; skip them
    ]
    return "\n".join(lines) if lines else f"No {state} issues found."


@mcp.tool()
@handle_github_errors
def get_issue(repo_name: str, issue_number: int) -> str:
    """
    Get details of a specific issue, including its comments.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        issue_number: The issue number
    """
    repo = _repo(repo_name)
    issue = repo.get_issue(issue_number)
    comments = list(issue.get_comments())
    comment_text = "\n".join(
        f"  [{c.user.login}]: {c.body}" for c in comments
    ) if comments else "  No comments."
    return (
        f"#{issue.number}: {issue.title}\n"
        f"State: {issue.state}\n"
        f"Author: {issue.user.login}\n"
        f"Body: {issue.body or 'No description.'}\n"
        f"Comments:\n{comment_text}\n"
        f"URL: {issue.html_url}"
    )


@mcp.tool()
@handle_github_errors
def create_issue(repo_name: str, title: str, body: str = "") -> str:
    """
    Create a new issue in a repository.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        title: Title of the issue
        body: Optional description/body of the issue
    """
    repo = _repo(repo_name)
    issue = repo.create_issue(title=title, body=body)
    return f"Created issue #{issue.number}: {issue.title}\n{issue.html_url}"


@mcp.tool()
@handle_github_errors
def close_issue(repo_name: str, issue_number: int) -> str:
    """
    Close an issue.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        issue_number: The issue number to close
    """
    repo = _repo(repo_name)
    issue = repo.get_issue(issue_number)
    issue.edit(state="closed")
    return f"Closed issue #{issue.number}: {issue.title}"


@mcp.tool()
@handle_github_errors
def list_pull_requests(repo_name: str, state: str = "open") -> str:
    """
    List pull requests for a repository.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        state: 'open', 'closed', or 'all' (default: 'open')
    """
    repo = _repo(repo_name)
    lines = [
        f"#{pr.number} [{pr.state}] {pr.title}\n"
        f"  Author: {pr.user.login} | {pr.head.ref} → {pr.base.ref}\n"
        f"  URL: {pr.html_url}"
        for pr in repo.get_pulls(state=state)
    ]
    return "\n\n".join(lines) if lines else f"No {state} pull requests found."


@mcp.tool()
@handle_github_errors
def get_pull_request(repo_name: str, pr_number: int) -> str:
    """
    Get details of a specific pull request, including changed files.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        pr_number: The pull request number
    """
    repo = _repo(repo_name)
    pr = repo.get_pull(pr_number)
    files = [f.filename for f in pr.get_files()]
    return (
        f"#{pr.number}: {pr.title}\n"
        f"State: {pr.state} | Merged: {pr.merged}\n"
        f"Author: {pr.user.login}\n"
        f"Branch: {pr.head.ref} → {pr.base.ref}\n"
        f"Body: {pr.body or 'No description.'}\n"
        f"Changed files ({pr.changed_files}): {', '.join(files)}\n"
        f"Commits: {pr.commits} | +{pr.additions} / -{pr.deletions}\n"
        f"URL: {pr.html_url}"
    )


@mcp.tool()
@handle_github_errors
def summarize_recent_activity(repo_name: str, days: int = 7) -> str:
    """
    Summarize recent commits, opened/updated issues, and merged PRs for a repo.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        days: How many days back to look (default: 7)
    """
    repo = _repo(repo_name)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    commits = list(repo.get_commits(since=since))
    issues = [i for i in repo.get_issues(state="all", since=since) if not i.pull_request]
    merged_prs = [p for p in repo.get_pulls(state="closed") if p.merged_at and p.merged_at >= since]

    commit_lines = "\n".join(
        f"  - {c.commit.message.splitlines()[0]} ({c.commit.author.name})" for c in commits[:10]
    ) or "  None"
    issue_lines = "\n".join(
        f"  #{i.number} {i.title} [{i.state}]" for i in issues[:10]
    ) or "  None"
    pr_lines = "\n".join(
        f"  #{p.number} {p.title}" for p in merged_prs[:10]
    ) or "  None"

    return (
        f"Activity in '{repo_name}' over the last {days} days:\n\n"
        f"Commits ({len(commits)}):\n{commit_lines}\n\n"
        f"Opened/Updated Issues ({len(issues)}):\n{issue_lines}\n\n"
        f"Merged PRs ({len(merged_prs)}):\n{pr_lines}"
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")