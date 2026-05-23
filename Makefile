.PHONY: help install dev test lint format clean release release-patch release-minor release-major release-dry-run changelog docker-build docker-run

# Default target
help:
	@echo "SRE Bot - Available Commands"
	@echo ""
	@echo "Development:"
	@echo "  make install      Install dependencies"
	@echo "  make dev          Install with dev dependencies"
	@echo "  make test         Run tests"
	@echo "  make lint         Run linter (ruff)"
	@echo "  make format       Format code (ruff)"
	@echo "  make clean        Clean build artifacts"
	@echo ""
	@echo "Release:"
	@echo "  make release-patch    Create patch release (0.0.X)"
	@echo "  make release-minor    Create minor release (0.X.0)"
	@echo "  make release-major    Create major release (X.0.0)"
	@echo "  make release-dry-run  Preview release without creating"
	@echo "  make changelog        Generate changelog preview"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build     Build Docker image"
	@echo "  make docker-run       Run Docker container"

# =============================================================================
# Development
# =============================================================================

install:
	pip install -e .

dev:
	pip install -e ".[dev]"
	pre-commit install

test:
	pytest tests/ -v --cov=sre_bot --cov-report=term-missing

lint:
	ruff check src/ tests/
	ruff format --check src/ tests/

format:
	ruff check --fix src/ tests/
	ruff format src/ tests/

clean:
	rm -rf build/ dist/ *.egg-info
	rm -rf .pytest_cache/ .ruff_cache/ .mypy_cache/
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

# =============================================================================
# Release
# =============================================================================

release-patch:
	@echo "Creating patch release..."
	python scripts/release.py --bump patch --push

release-minor:
	@echo "Creating minor release..."
	python scripts/release.py --bump minor --push

release-major:
	@echo "Creating major release..."
	python scripts/release.py --bump major --push

release-dry-run:
	@echo "Dry run - previewing release..."
	python scripts/release.py --bump patch --dry-run

changelog:
	@echo "Generating changelog preview..."
	python scripts/release.py --dry-run --output CHANGELOG_PREVIEW.md
	@cat CHANGELOG_PREVIEW.md
	@rm -f CHANGELOG_PREVIEW.md

# Create a specific version release
# Usage: make release VERSION=1.2.3
release:
ifdef VERSION
	@echo "Creating release v$(VERSION)..."
	python scripts/release.py --version $(VERSION) --push
else
	@echo "Error: VERSION is required"
	@echo "Usage: make release VERSION=1.2.3"
	@exit 1
endif

# =============================================================================
# Docker
# =============================================================================

DOCKER_IMAGE = sre-bot
DOCKER_TAG = latest

docker-build:
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

docker-run:
	docker run --rm -it \
		--env-file .env \
		-p 8000:8000 \
		$(DOCKER_IMAGE):$(DOCKER_TAG)

# Build with specific version tag
# Usage: make docker-release VERSION=1.2.3
docker-release:
ifdef VERSION
	docker build -t $(DOCKER_IMAGE):$(VERSION) -t $(DOCKER_IMAGE):latest .
else
	@echo "Error: VERSION is required"
	@echo "Usage: make docker-release VERSION=1.2.3"
	@exit 1
endif

# =============================================================================
# CI/CD Helpers
# =============================================================================

# Verify everything is ready for release
pre-release: lint test
	@echo "Pre-release checks passed!"

# Show current version
version:
	@python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])"

# Show git tags
tags:
	@git tag -l --sort=-v:refname | head -10

# Show commits since last tag
commits-since-tag:
	@LAST_TAG=$$(git describe --tags --abbrev=0 2>/dev/null || echo ""); \
	if [ -n "$$LAST_TAG" ]; then \
		echo "Commits since $$LAST_TAG:"; \
		git log $$LAST_TAG..HEAD --oneline; \
	else \
		echo "No tags found. All commits:"; \
		git log --oneline | head -20; \
	fi
