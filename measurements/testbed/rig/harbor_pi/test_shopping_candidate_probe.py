"""Baseline comparison only; no Docker or model calls."""
import unittest
from harbor_pi.shopping_candidate_probe import matches


class ShoppingCandidateTests(unittest.TestCase):
    def test_baseline_must_match_both_original_counts(self):
        labels = {'InitialGroups': '2', 'InitialCustomers': '7'}
        self.assertTrue(matches(labels, {'InitialGroups': 2, 'InitialCustomers': 7}))
        self.assertFalse(matches(labels, {'InitialGroups': 2, 'InitialCustomers': 8}))
        self.assertFalse(matches(labels, {}))


if __name__ == '__main__':
    unittest.main()
