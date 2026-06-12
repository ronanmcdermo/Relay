import os
from github import Github, Auth
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")

gh = Github(auth=Auth.Token(os.environ["GITHUB_TOKEN"]))

# 1. Who is this token authenticating as?
user = gh.get_user()
print("Authenticated as:", user.login)

# 2. Can it see the Relay repo directly?
try:
    repo = gh.get_repo(f"{user.login}/Relay")
    print("✓ Direct access to Relay works:", repo.full_name, "| private:", repo.private)
except Exception as e:
    print("✗ Cannot access Relay directly:", e)

# 3. What does the list endpoint return, by affiliation?
print("\n--- get_repos() default ---")
print([r.full_name for r in user.get_repos()])

print("\n--- get_repos(affiliation='owner') ---")
print([r.full_name for r in user.get_repos(affiliation="owner")])