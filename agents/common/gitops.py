"""
GitOps — Basic git operations for the free tier.

Provides auto-commit, pre-commit secret scanning, status, log, and rollback.
"""

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Patterns that suggest hardcoded secrets
SECRET_PATTERNS = [
    (r'sk-[a-zA-Z0-9]{20,}', "OpenAI API key"),
    (r'sk-ant-[a-zA-Z0-9\-]{20,}', "Anthropic API key"),
    (r'ghp_[a-zA-Z0-9]{36,}', "GitHub personal access token"),
    (r'github_pat_[a-zA-Z0-9_]{20,}', "GitHub fine-grained PAT"),
    (r'gho_[a-zA-Z0-9]{36,}', "GitHub OAuth token"),
    (r'glpat-[a-zA-Z0-9\-]{20,}', "GitLab personal access token"),
    (r'xoxb-[a-zA-Z0-9\-]+', "Slack bot token"),
    (r'xoxp-[a-zA-Z0-9\-]+', "Slack user token"),
    (r'AKIA[0-9A-Z]{16}', "AWS access key"),
    (r'(?i)(?:api[_-]?key|apikey|secret[_-]?key|token|password|passwd)\s*[=:]\s*["\']?[a-zA-Z0-9\-_.]{16,}', "Possible hardcoded secret"),
]

# Files that should generally not be committed
SENSITIVE_FILES = [
    ".env",
    ".env.local",
    ".env.production",
    "auth-profiles.json",
    "credentials.json",
    "secrets.yaml",
    "secrets.yml",
]

# Large file threshold (1MB)
LARGE_FILE_THRESHOLD = 1_000_000


class GitOps:
    """Basic git operations for project management."""

    def __init__(self, workspace_path: str):
        self.workspace = Path(workspace_path).resolve()

    def _run(self, *args, **kwargs) -> subprocess.CompletedProcess:
        """Run a git command in the workspace."""
        return subprocess.run(
            *args,
            capture_output=True,
            text=True,
            cwd=str(self.workspace),
            timeout=30,
            **kwargs,
        )

    def init_repo(self) -> bool:
        """Initialize a git repo if not already one."""
        git_dir = self.workspace / ".git"
        if git_dir.exists():
            logger.info("Git repo already initialized")
            return True

        result = self._run(["git", "init"])
        if result.returncode == 0:
            logger.info(f"Initialized git repo at {self.workspace}")
            # Create .gitignore if it doesn't exist
            gitignore = self.workspace / ".gitignore"
            if not gitignore.exists():
                gitignore.write_text(
                    "# Secrets and environment\n"
                    ".env\n.env.*\n"
                    "auth-profiles.json\n"
                    "credentials.json\n"
                    "\n# Data\n"
                    "*.db\ndata/\n"
                    "\n# Python\n"
                    "__pycache__/\n*.pyc\n.venv/\nvenv/\n"
                    "\n# OS\n"
                    ".DS_Store\nThumbs.db\n"
                )
            return True
        else:
            logger.error(f"git init failed: {result.stderr}")
            return False

    def auto_commit(self, message: str, files: Optional[list[str]] = None) -> Optional[str]:
        """
        Stage and commit changes with a meaningful message.
        Returns commit hash or None on failure.
        """
        # Pre-commit check
        warnings = self.pre_commit_check()
        if warnings:
            logger.warning(f"Pre-commit warnings: {warnings}")
            # Don't block, just warn — the pre-commit hook will block if installed

        # Stage files
        if files:
            for f in files:
                self._run(["git", "add", f])
        else:
            self._run(["git", "add", "-A"])

        # Check if there's anything to commit
        status = self._run(["git", "status", "--porcelain"])
        if not status.stdout.strip():
            logger.info("Nothing to commit")
            return None

        # Commit
        result = self._run(["git", "commit", "-m", message])
        if result.returncode == 0:
            # Extract commit hash
            hash_result = self._run(["git", "rev-parse", "HEAD"])
            commit_hash = hash_result.stdout.strip()
            logger.info(f"Committed: {commit_hash[:8]} — {message}")
            return commit_hash
        else:
            logger.error(f"Commit failed: {result.stderr}")
            return None

    def pre_commit_check(self) -> list[str]:
        """
        Scan staged files for secrets, sensitive files, and large binaries.
        Returns list of warnings.
        """
        warnings = []

        # Get staged files
        result = self._run(["git", "diff", "--cached", "--name-only"])
        if result.returncode != 0:
            # Maybe not a git repo yet — scan all files
            result = self._run(["git", "status", "--porcelain"])
            if result.returncode != 0:
                return []

        staged_files = [
            line.strip().lstrip("MADRCU? ")
            for line in result.stdout.strip().split("\n")
            if line.strip()
        ]

        for filepath in staged_files:
            # Check for sensitive filenames
            basename = os.path.basename(filepath)
            if basename in SENSITIVE_FILES:
                warnings.append(f"🚨 Sensitive file staged: {filepath}")
                continue

            # Check file size
            full_path = self.workspace / filepath
            if full_path.exists() and full_path.is_file():
                size = full_path.stat().st_size
                if size > LARGE_FILE_THRESHOLD:
                    warnings.append(
                        f"⚠️ Large file ({size // 1024}KB): {filepath}"
                    )

                # Scan text files for secret patterns
                if size < 500_000:  # Don't scan huge files
                    try:
                        content = full_path.read_text(errors="ignore")
                        for pattern, desc in SECRET_PATTERNS:
                            if re.search(pattern, content):
                                warnings.append(
                                    f"🔑 Possible {desc} in: {filepath}"
                                )
                                break  # One warning per file is enough
                    except Exception:
                        pass

        return warnings

    def get_status(self) -> dict:
        """Git status summary."""
        result = self._run(["git", "status", "--porcelain", "-b"])
        if result.returncode != 0:
            return {"error": "Not a git repository", "branch": None, "files": []}

        lines = result.stdout.strip().split("\n")
        branch_line = lines[0] if lines else ""
        branch = branch_line.replace("## ", "").split("...")[0] if branch_line.startswith("##") else "unknown"

        file_changes = []
        for line in lines[1:]:
            if line.strip():
                status_code = line[:2].strip()
                filename = line[3:].strip()
                file_changes.append({"status": status_code, "file": filename})

        return {
            "branch": branch,
            "files": file_changes,
            "clean": len(file_changes) == 0,
        }

    def get_log(self, limit: int = 10) -> list[dict]:
        """Recent commit history."""
        result = self._run([
            "git", "log", f"-{limit}",
            "--format=%H|%h|%s|%an|%ai",
        ])
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split("|", 4)
            if len(parts) >= 5:
                commits.append({
                    "hash": parts[0],
                    "short_hash": parts[1],
                    "message": parts[2],
                    "author": parts[3],
                    "date": parts[4],
                })
        return commits

    def rollback(self, commit_hash: Optional[str] = None) -> bool:
        """Revert last commit or a specific commit."""
        if commit_hash:
            result = self._run(["git", "revert", "--no-edit", commit_hash])
        else:
            result = self._run(["git", "revert", "--no-edit", "HEAD"])

        if result.returncode == 0:
            logger.info(f"Rolled back {'to ' + commit_hash if commit_hash else 'last commit'}")
            return True
        else:
            logger.error(f"Rollback failed: {result.stderr}")
            return False
