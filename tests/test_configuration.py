import tempfile
import unittest
from pathlib import Path

from gh_backup.configuration import ConfigurationError, OperationalConfig


class OperationalConfigTests(unittest.TestCase):
    def test_configuration_normalizes_targets_and_boolean_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = OperationalConfig.from_environment(
                {
                    "GITHUB_OWNER": "OctoCat",
                    "GITHUB_ORGS": " my-org,MY-ORG,octocat,other ",
                    "GITHUB_TOKEN": "secret-token\r\n",
                    "BACKUP_DATA_DIR": temp_dir,
                    "BACKUP_MIN_FREE_GB": "0",
                    "GHORG_INCLUDE_SUBMODULES": "YES",
                }
            )

            self.assertEqual(config.backup.owner, "OctoCat")
            self.assertEqual(config.backup.orgs, ("my-org", "other"))
            self.assertEqual(config.backup.token, "secret-token")
            self.assertEqual(config.backup.data_dir, Path(temp_dir))
            self.assertTrue(config.backup.include_submodules)

    def test_configuration_reads_a_token_file_without_token_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            token_file = Path(temp_dir) / "github-token"
            token_file.write_text("file-secret\n", encoding="utf-8")

            config = OperationalConfig.from_environment(
                {
                    "GITHUB_OWNER": "OctoCat",
                    "GITHUB_TOKEN_FILE": str(token_file),
                    "BACKUP_DATA_DIR": temp_dir,
                    "BACKUP_MIN_FREE_GB": "0",
                }
            )

            self.assertEqual(config.backup.token, "file-secret")
            self.assertEqual(config.backup.token_file, token_file)

    def test_configuration_reports_all_invalid_values_together(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaises(ConfigurationError) as raised:
                OperationalConfig.from_environment(
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
                raised.exception.errors,
                (
                    "RUN_ON_STARTUP must be a boolean value",
                    "GHORG_INCLUDE_SUBMODULES must be a boolean value",
                    "BACKUP_MAX_AGE_HOURS must be greater than zero",
                    "BACKUP_MIN_FREE_GB must not be negative",
                ),
            )


if __name__ == "__main__":
    unittest.main()
