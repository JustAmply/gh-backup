import unittest

from gh_backup.coverage import CoveragePolicy, missing_required_options


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
            "not supported by pinned github-backup 0.61.5",
        )
        self.assertIn("pull_reviews", policy.unsupported)

    def test_capability_check_reports_options_missing_from_pinned_tool(self) -> None:
        policy = CoveragePolicy.load_default()
        help_text = " ".join(policy.required_tool_options - {"--security-advisories"})

        self.assertEqual(
            missing_required_options(policy, help_text), ["--security-advisories"]
        )


if __name__ == "__main__":
    unittest.main()
