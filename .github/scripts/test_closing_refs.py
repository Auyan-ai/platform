import unittest

from closing_refs import closing_refs


class ClosingRefsTest(unittest.TestCase):
    def test_multiple_refs(self) -> None:
        body = "Closes #1\nFixes #22 y resolves #333"
        self.assertEqual(closing_refs(body), [1, 22, 333])

    def test_case_insensitive_and_variants(self) -> None:
        body = "CLOSES #1, fixed #2, Resolved: #3, closed #4, FIX #5, resolve #6"
        self.assertEqual(closing_refs(body), [1, 2, 3, 4, 5, 6])

    def test_refs_ignored(self) -> None:
        self.assertEqual(closing_refs("Refs #9\nrefs #10\nCloses #11"), [11])

    def test_empty_body(self) -> None:
        self.assertEqual(closing_refs(""), [])
        self.assertEqual(closing_refs(None), [])

    def test_duplicates_collapsed(self) -> None:
        self.assertEqual(closing_refs("Closes #5\nFixes #5"), [5])

    def test_no_false_positive_inside_words(self) -> None:
        self.assertEqual(closing_refs("prefix #7 y disclose #8"), [])


if __name__ == "__main__":
    unittest.main()
