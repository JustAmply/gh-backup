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

    def test_offsite_repository_requires_password_file_and_positive_retention(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            errors = validate_environment(
                {
                    "GITHUB_TOKEN": "secret-token",
                    "BACKUP_DATA_DIR": temp_dir,
                    "BACKUP_MIN_FREE_GB": "0",
                    "RESTIC_REPOSITORY": "s3:example.invalid/archive",
                    "RESTIC_PASSWORD_FILE": str(Path(temp_dir) / "missing"),
                    "BACKUP_RETENTION_DAILY": "0",
                    "BACKUP_RETENTION_WEEKLY": "-1",
                    "BACKUP_RETENTION_MONTHLY": "many",
                }
            )

            self.assertIn("RESTIC_PASSWORD_FILE is not readable", errors[0])
            self.assertIn("BACKUP_RETENTION_DAILY must be greater than zero", errors)
            self.assertIn("BACKUP_RETENTION_WEEKLY must be greater than zero", errors)
            self.assertIn("BACKUP_RETENTION_MONTHLY must be an integer", errors)


if __name__ == "__main__":
    unittest.main()
