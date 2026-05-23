#!/usr/bin/env python3
"""
Release automation script.

Generates release notes from commits and creates GitHub releases.
Follows Conventional Commits specification for categorization.

Usage:
    python scripts/release.py --bump patch   # 0.1.0 -> 0.1.1
    python scripts/release.py --bump minor   # 0.1.0 -> 0.2.0
    python scripts/release.py --bump major   # 0.1.0 -> 1.0.0
    python scripts/release.py --version 1.2.3  # Set specific version
    python scripts/release.py --dry-run      # Preview without creating
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# Conventional Commits categories
COMMIT_CATEGORIES = {
    "feat": ("Features", "New features and enhancements"),
    "fix": ("Bug Fixes", "Bug fixes and patches"),
    "perf": ("Performance", "Performance improvements"),
    "refactor": ("Refactoring", "Code refactoring"),
    "docs": ("Documentation", "Documentation updates"),
    "test": ("Tests", "Test additions and updates"),
    "ci": ("CI/CD", "CI/CD pipeline changes"),
    "chore": ("Chores", "Maintenance and chores"),
    "build": ("Build", "Build system changes"),
    "style": ("Style", "Code style changes"),
}

# Breaking change indicator
BREAKING_CHANGE_PATTERN = re.compile(r"BREAKING CHANGE:|!")


@dataclass
class Commit:
    """Represents a parsed commit."""

    hash: str
    type: str
    scope: str | None
    description: str
    body: str
    is_breaking: bool
    raw_message: str


def run_command(cmd: list[str], check: bool = True) -> str:
    """Run a shell command and return output."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=check)
    return result.stdout.strip()


def get_current_version() -> str:
    """Get current version from pyproject.toml."""
    pyproject = Path("pyproject.toml")
    if not pyproject.exists():
        return "0.0.0"

    content = pyproject.read_text()
    match = re.search(r'version\s*=\s*"([^"]+)"', content)
    return match.group(1) if match else "0.0.0"


def bump_version(current: str, bump_type: str) -> str:
    """Bump version based on type (major, minor, patch)."""
    parts = current.split(".")
    if len(parts) != 3:
        parts = ["0", "0", "0"]

    major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])

    if bump_type == "major":
        return f"{major + 1}.0.0"
    elif bump_type == "minor":
        return f"{major}.{minor + 1}.0"
    else:  # patch
        return f"{major}.{minor}.{patch + 1}"


def get_last_tag() -> str | None:
    """Get the last git tag."""
    try:
        return run_command(["git", "describe", "--tags", "--abbrev=0"])
    except subprocess.CalledProcessError:
        return None


def get_commits_since_tag(tag: str | None) -> list[str]:
    """Get commit messages since the last tag."""
    if tag:
        cmd = ["git", "log", f"{tag}..HEAD", "--pretty=format:%H|%s|%b|END_COMMIT"]
    else:
        cmd = ["git", "log", "--pretty=format:%H|%s|%b|END_COMMIT"]

    output = run_command(cmd, check=False)
    if not output:
        return []

    return output.split("|END_COMMIT")


def parse_commit(raw: str) -> Commit | None:
    """Parse a raw commit string into a Commit object."""
    if not raw.strip():
        return None

    parts = raw.strip().split("|", 2)
    if len(parts) < 2:
        return None

    commit_hash = parts[0].strip()
    subject = parts[1].strip()
    body = parts[2].strip() if len(parts) > 2 else ""

    # Parse conventional commit format: type(scope): description
    pattern = r"^(\w+)(?:\(([^)]+)\))?(!)?:\s*(.+)$"
    match = re.match(pattern, subject)

    if match:
        commit_type = match.group(1).lower()
        scope = match.group(2)
        is_breaking = bool(match.group(3)) or bool(BREAKING_CHANGE_PATTERN.search(body))
        description = match.group(4)
    else:
        # Non-conventional commit
        commit_type = "other"
        scope = None
        is_breaking = bool(BREAKING_CHANGE_PATTERN.search(body))
        description = subject

    return Commit(
        hash=commit_hash[:7],
        type=commit_type,
        scope=scope,
        description=description,
        body=body,
        is_breaking=is_breaking,
        raw_message=subject,
    )


def categorize_commits(commits: list[Commit]) -> dict[str, list[Commit]]:
    """Categorize commits by type."""
    categories: dict[str, list[Commit]] = {}

    for commit in commits:
        category = commit.type if commit.type in COMMIT_CATEGORIES else "other"

        if category not in categories:
            categories[category] = []
        categories[category].append(commit)

    return categories


def generate_release_notes(
    commits: list[Commit],
    version: str,
    previous_tag: str | None,
) -> str:
    """Generate markdown release notes."""
    lines = []

    # Header
    lines.append(f"# Release v{version}")
    lines.append("")
    lines.append(f"**Release Date:** {datetime.now().strftime('%Y-%m-%d')}")
    lines.append("")

    if previous_tag:
        lines.append(f"**Full Changelog:** [{previous_tag}...v{version}]")
    lines.append("")

    # Check for breaking changes
    breaking_commits = [c for c in commits if c.is_breaking]
    if breaking_commits:
        lines.append("## Breaking Changes")
        lines.append("")
        for commit in breaking_commits:
            scope_str = f"**{commit.scope}:** " if commit.scope else ""
            lines.append(f"- {scope_str}{commit.description} ({commit.hash})")
        lines.append("")

    # Categorize and write commits
    categories = categorize_commits(commits)

    # Order categories by importance
    category_order = [
        "feat",
        "fix",
        "perf",
        "refactor",
        "docs",
        "test",
        "ci",
        "build",
        "chore",
        "style",
        "other",
    ]

    for cat_key in category_order:
        if cat_key not in categories:
            continue

        cat_commits = categories[cat_key]
        if not cat_commits:
            continue

        # Get category title
        title = COMMIT_CATEGORIES[cat_key][0] if cat_key in COMMIT_CATEGORIES else "Other Changes"

        lines.append(f"## {title}")
        lines.append("")

        for commit in cat_commits:
            scope_str = f"**{commit.scope}:** " if commit.scope else ""
            lines.append(f"- {scope_str}{commit.description} ({commit.hash})")

        lines.append("")

    # Stats
    lines.append("---")
    lines.append("")
    lines.append(f"*{len(commits)} commits in this release*")

    return "\n".join(lines)


def update_pyproject_version(new_version: str) -> None:
    """Update version in pyproject.toml."""
    pyproject = Path("pyproject.toml")
    content = pyproject.read_text()
    updated = re.sub(
        r'version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        content,
    )
    pyproject.write_text(updated)


def create_tag(version: str, release_notes: str) -> None:
    """Create and push a git tag."""
    tag_name = f"v{version}"

    # Create annotated tag with release notes
    run_command(["git", "tag", "-a", tag_name, "-m", release_notes])
    print(f"Created tag: {tag_name}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Create releases with auto-generated notes")
    parser.add_argument(
        "--bump",
        choices=["major", "minor", "patch"],
        help="Version bump type",
    )
    parser.add_argument(
        "--version",
        help="Specific version to set (e.g., 1.2.3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview release notes without creating tag",
    )
    parser.add_argument(
        "--push",
        action="store_true",
        help="Push tag to remote after creation",
    )
    parser.add_argument(
        "--output",
        help="Write release notes to file",
    )

    args = parser.parse_args()

    # Determine new version
    current_version = get_current_version()
    print(f"Current version: {current_version}")

    if args.version:
        new_version = args.version
    elif args.bump:
        new_version = bump_version(current_version, args.bump)
    else:
        # Default to patch bump
        new_version = bump_version(current_version, "patch")

    print(f"New version: {new_version}")

    # Get commits since last tag
    last_tag = get_last_tag()
    print(f"Last tag: {last_tag or 'None (first release)'}")

    raw_commits = get_commits_since_tag(last_tag)
    commits = [c for c in (parse_commit(rc) for rc in raw_commits) if c is not None]

    if not commits:
        print("No commits found since last tag.")
        return 1

    print(f"Found {len(commits)} commits since last tag")

    # Generate release notes
    release_notes = generate_release_notes(commits, new_version, last_tag)

    # Output release notes
    print("\n" + "=" * 60)
    print("RELEASE NOTES")
    print("=" * 60)
    print(release_notes)
    print("=" * 60 + "\n")

    if args.output:
        Path(args.output).write_text(release_notes)
        print(f"Release notes written to: {args.output}")

    if args.dry_run:
        print("[DRY RUN] No changes made.")
        return 0

    # Update version in pyproject.toml
    update_pyproject_version(new_version)
    print(f"Updated pyproject.toml version to {new_version}")

    # Commit version change
    run_command(["git", "add", "pyproject.toml"])
    run_command(["git", "commit", "-m", f"chore(release): bump version to {new_version}"])
    print("Committed version bump")

    # Create tag
    create_tag(new_version, release_notes)

    if args.push:
        run_command(["git", "push"])
        run_command(["git", "push", "--tags"])
        print("Pushed changes and tags to remote")

    print(f"\nRelease v{new_version} created successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
