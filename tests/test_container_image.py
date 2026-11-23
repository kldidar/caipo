"""The container image of the public instance keeps the rules of ADR-0024 and ADR-0008."""

import re
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPOSITORY / "Dockerfile").read_text(encoding="utf-8")
IGNORED = (REPOSITORY / ".dockerignore").read_text(encoding="utf-8").split()


def test_every_base_image_is_pinned_to_a_version() -> None:
    images = re.findall(r"^FROM\s+(\S+)", DOCKERFILE, flags=re.MULTILINE)
    images += re.findall(r"COPY\s+--from=(\S+:\S+)", DOCKERFILE)

    assert images
    for image in images:
        assert re.search(r":\d+\.\d+\.\d+", image), image


def test_the_application_runs_as_a_user_that_is_not_root() -> None:
    final_stage = DOCKERFILE.rsplit("\nFROM ", 1)[1]

    users = re.findall(r"^USER\s+(\S+)", final_stage, flags=re.MULTILINE)
    assert users and users[-1] not in {"root", "0"}


def test_no_migration_runs_when_the_container_starts() -> None:
    command = re.findall(r"^CMD\s+(.+)$", DOCKERFILE, flags=re.MULTILINE)

    assert len(command) == 1
    assert "migrate" not in command[0] and "gunicorn" in command[0]


def test_no_secret_local_data_or_test_goes_into_the_image() -> None:
    for pattern in (".env", ".env.*", ".git", ".venv", "**/tests", "data"):
        assert pattern in IGNORED, pattern
