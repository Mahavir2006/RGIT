"""Alembic migrations must build the same schema as the ORM models.

The rest of the suite builds tables with ``metadata.create_all``, so without this test a model
change could silently diverge from the migration that production databases actually run.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.conftest import REPO_ROOT


def _alembic(args: list[str], db_path: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}"}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_migrations_upgrade_downgrade_and_match_models(tmp_path: Path) -> None:
    db_path = tmp_path / "migrations.db"

    upgrade = _alembic(["upgrade", "head"], db_path)
    assert upgrade.returncode == 0, upgrade.stderr

    check = _alembic(["check"], db_path)
    assert check.returncode == 0, f"models and migrations have drifted:\n{check.stderr}"

    downgrade = _alembic(["downgrade", "base"], db_path)
    assert downgrade.returncode == 0, downgrade.stderr

    reupgrade = _alembic(["upgrade", "head"], db_path)
    assert reupgrade.returncode == 0, reupgrade.stderr
