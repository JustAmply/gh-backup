import tempfile
import unittest
from pathlib import Path

from gh_backup.coverage import (
    CoveragePolicy,
    load_pinned_version,
    missing_required_options,
)


class CoveragePolicyTests(unittest.TestCase):
    def test_default_policy_declares_enabled_and_unsupported_resources(self) -> None:
        policy = CoveragePolicy.load_default()

        organization_args = policy.metadata_arguments("organization")
        user_args = policy.metadata_arguments("user")
        self.assertIn("--security-advisories", organization_args)
        self.assertIn("--fork", organization_args)
        self.assertIn("--gists", user_args)
        self.assertIn("--followers", user_args)
        self.assertEqual(
            policy.unsupported["discussions"],
            "not enabled by the current metadata coverage policy",
        )
        self.assertIn("pull_reviews", policy.unsupported)
        self.assertEqual(policy.pinned_version, load_pinned_version())

    def test_pinned_version_requires_one_exact_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            requirement = Path(temp_dir) / "github-backup.txt"
            requirement.write_text(
                "# Runtime backup client\ngithub-backup==1.2.3\n",
                encoding="utf-8",
            )

            self.assertEqual(load_pinned_version(requirement), "1.2.3")

            requirement.write_text("github-backup>=1.2.3\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly one"):
                load_pinned_version(requirement)

    def test_capability_check_reports_options_missing_from_pinned_tool(self) -> None:
        policy = CoveragePolicy.load_default()
        help_text = " ".join(policy.required_tool_options - {"--security-advisories"})

        self.assertEqual(
            missing_required_options(policy, help_text), ["--security-advisories"]
        )


if __name__ == "__main__":
    unittest.main()
