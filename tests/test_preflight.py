import tempfile
import unittest
from pathlib import Path

from gh_backup.preflight import validate_environment


class PreflightTests(unittest.TestCase):
    def test_invalid_operational_values_are_reported_together(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            errors = validate_environment(
                {
                    "GITHUB_TOKEN": "secret-token",
                    "BACKUP_DATA_DIR": temp_dir,
                    "RUN_ON_STARTUP": "sometimes",
                    "GHORG_INCLUDE_SUBMODULES": "perhaps",
                    "BACKUP_MAX_AGE_HOURS": "0",
                    "BACKUP_MIN_FREE_GB": "-1",
                }
            )

            self.assertEqual(
                errors,
                [
                    "RUN_ON_STARTUP must be a boolean value",
                    "GHORG_INCLUDE_SUBMODULES must be a boolean value",
                    "BACKUP_MAX_AGE_HOURS must be greater than zero",
                    "BACKUP_MIN_FREE_GB must not be negative",
                ],
            )
            self.assertTrue(Path(temp_dir).is_dir())


if __name__ == "__main__":
    unittest.main()
