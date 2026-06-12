import os
from github import Github, Auth
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

gh = Github(auth=Auth.Token(os.environ["GITHUB_TOKEN"]))
mcp = FastMCP("relay")


def _repo(repo_name: str):
    """Helper to get a repo object — accepts 'owner/repo' or just 'repo' (uses authenticated user)."""
    if "/" in repo_name:
        return gh.get_repo(repo_name)
    return gh.get_user().get_repo(repo_name)


@mcp.tool()
def list_repos() -> str:
    """List all repositories accessible to the authenticated GitHub user."""
    repos = gh.get_user().get_repos()
    lines = [f"- {r.full_name} ({'private' if r.private else 'public'})" for r in repos]
    return "\n".join(lines) if lines else "No repositories found."


@mcp.tool()
def list_issues(repo_name: str, state: str = "open") -> str:
    """
    List issues for a repository.
    
    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        state: 'open', 'closed', or 'all' (default: 'open')
    """
    repo = _repo(repo_name)
    issues = repo.get_issues(state=state)
    lines = []
    for issue in issues:
        if issue.pull_request:
            continue  # skip PRs which also appear as issues
        lines.append(f"#{issue.number} [{issue.state}] {issue.title} — {issue.html_url}")
    return "\n".join(lines) if lines else f"No {state} issues found."


@mcp.tool()
def get_issue(repo_name: str, issue_number: int) -> str:
    """
    Get details of a specific issue.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        issue_number: The issue number
    """
    repo = _repo(repo_name)
    issue = repo.get_issue(issue_number)
    comments = list(issue.get_comments())
    comment_text = "\n".join(
        [f"  [{c.user.login}]: {c.body}" for c in comments]
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
def list_pull_requests(repo_name: str, state: str = "open") -> str:
    """
    List pull requests for a repository.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        state: 'open', 'closed', or 'all' (default: 'open')
    """
    repo = _repo(repo_name)
    prs = repo.get_pulls(state=state)
    lines = []
    for pr in prs:
        lines.append(
            f"#{pr.number} [{pr.state}] {pr.title}\n"
            f"  Author: {pr.user.login} | {pr.head.ref} → {pr.base.ref}\n"
            f"  URL: {pr.html_url}"
        )
    return "\n\n".join(lines) if lines else f"No {state} pull requests found."


@mcp.tool()
def get_pull_request(repo_name: str, pr_number: int) -> str:
    """
    Get details of a specific pull request including changed files.

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
def summarize_recent_activity(repo_name: str, days: int = 7) -> str:
    """
    Summarize recent commits, opened issues, and merged PRs for a repo.

    Args:
        repo_name: Repository name as 'owner/repo' or just 'repo'
        days: How many days back to look (default: 7)
    """
    from datetime import datetime, timedelta, timezone
    repo = _repo(repo_name)
    since = datetime.now(timezone.utc) - timedelta(days=days)

    commits = list(repo.get_commits(since=since))
    issues = [i for i in repo.get_issues(state="all", since=since) if not i.pull_request]
    prs = [p for p in repo.get_pulls(state="closed") if p.merged_at and p.merged_at >= since]

    return (
        f"Activity in '{repo_name}' over the last {days} days:\n\n"
        f"Commits ({len(commits)}):\n" +
        "\n".join([f"  - {c.commit.message.splitlines()[0]} ({c.commit.author.name})" for c in commits[:10]]) +
        f"\n\nOpened/Updated Issues ({len(issues)}):\n" +
        "\n".join([f"  #{i.number} {i.title} [{i.state}]" for i in issues[:10]]) +
        f"\n\nMerged PRs ({len(prs)}):\n" +
        "\n".join([f"  #{p.number} {p.title}" for p in prs[:10]])
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
