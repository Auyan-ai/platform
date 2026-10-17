"""Prueba del enmascarado: python3 .claude/skills/verify/scripts/test_evidence_md.py"""
import importlib.util
import json
import os
import tempfile
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

    def test_keeps_decimals_like_costs(self) -> None:
        s = "{'total_tokens': 9405, 'total_cost': 0.0123456789} coste 3.5843"
        self.assertEqual(em.mask(s), s)
        self.assertEqual(em.mask("tel 612.345.678"), "tel [tel ***78]")


RUN = "9f8059bc-0036-4486-8e49-f14818278d97"
TRACE = "0b6c7c4e-1111-4222-8333-444455556666"


class SimulationTest(unittest.TestCase):
    def test_one_row_per_run_with_counts_cost_and_trace(self) -> None:
        row = {"id": RUN, "tenant": "marea-studio", "scenario": "CE-06: Cliente con 2 órdenes",
               "status": "passed", "termination_reason": "goal_achieved", "turns_count": 4,
               "judge": 8.5, "judge_goal": "true", "assertions_passed": 1, "assertions_total": 1,
               "cost_cents": 3.5843, "langsmith_trace_id": TRACE,
               "conversation_id": "7b307a56-b59f-4d91-b953-04e4e6b8d32a", "inbound": 2, "outbound": 2}
        with tempfile.TemporaryDirectory() as tmp:
            em.EVID_DIR = tmp
            with open(os.path.join(tmp, f"20261017-120000-sim-{RUN}.txt"), "w") as f:
                f.write(f"## run\n{json.dumps(row)}\n## messages\n agent_ai | outbound | escribe a ana@gmail.com\n")
            with open(os.path.join(tmp, f"20261017-120001-trace-{TRACE}.txt"), "w") as f:
                f.write(f"http=200 trace_id={TRACE}\n{{'name': 'simulation_run', 'total_cost': 0.0358432}}\n")
            md = em.compose_simulation([RUN])
        self.assertIn("| CE-06: Cliente con 2 órdenes | passed | 8.5 | goal_achieved | 4 | 2/2 | $0.0358 |", md)
        self.assertIn("'total_cost': 0.0358432", md)
        self.assertIn("a***@gmail.com", md)


if __name__ == "__main__":
    unittest.main()
