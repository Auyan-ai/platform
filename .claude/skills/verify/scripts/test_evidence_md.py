"""Prueba del enmascarado: python3 .claude/skills/verify/scripts/test_evidence_md.py"""
import importlib.util
import os
import unittest

spec = importlib.util.spec_from_file_location("evidence_md", os.path.join(os.path.dirname(__file__), "evidence-md.py"))
em = importlib.util.module_from_spec(spec)
spec.loader.exec_module(em)


class MaskTest(unittest.TestCase):
    def test_email(self) -> None:
        self.assertEqual(em.mask("escribe a maria.lopez@gmail.com ya"), "escribe a m***@gmail.com ya")

    def test_phones(self) -> None:
        self.assertEqual(em.mask("llama al +34 612 345 678"), "llama al [tel ***78]")
        self.assertEqual(em.mask("tel (600) 123-4567"), "tel [tel ***67]")

    def test_keeps_uuids_dates_and_short_numbers(self) -> None:
        s = "id b6f6495a-a490-404f-85f1-6b06d803f328 el 2026-10-12 14:29:54.432413+00, pedido #1234, 9405 tokens"
        self.assertEqual(em.mask(s), s)


if __name__ == "__main__":
    unittest.main()
