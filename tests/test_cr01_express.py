"""Tests for CR-01: express delivery."""

import io, json, tempfile, unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from supplydesk.cli import main
from supplydesk.menu import run_menu
from supplydesk.service import OrderService


class ExpressDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.service = OrderService(self.path)

    # CR examples 1 and 2: fee 1200, discount on merchandise only
    def test_cr_examples(self):
        cases = [
            ("regular", "notebook", 2, 1000, 0, 2200),
            ("student", "hoodie", 2, 8000, 800, 8400),
        ]
        for customer, product, qty, subtotal, discount, total in cases:
            with self.subTest(customer=customer, product=product):
                quote = self.service.quote(customer, [{"product_id": product, "quantity": qty}], "express")
                self.assertEqual(quote["fulfillment"], "express")
                self.assertEqual(quote["subtotal_cents"], subtotal)
                self.assertEqual(quote["discount_cents"], discount)
                self.assertEqual(quote["delivery_cents"], 1200)
                self.assertEqual(quote["total_cents"], total)

    # CR example 3 + requirement 2: express fee is never waived; standard stays free over $100
    def test_express_fee_never_waived(self):
        items = [{"product_id": "hoodie", "quantity": 3}]
        self.assertEqual(self.service.quote("regular", items, "delivery")["total_cents"], 12000)
        express = self.service.quote("regular", items, "express")
        self.assertEqual(express["delivery_cents"], 1200)
        self.assertEqual(express["total_cents"], 13200)

    # Requirement 5: quote and order agree; order kept after reopen and cancel
    def test_express_order_retained_through_reopen_and_cancel(self):
        items = [{"product_id": "hoodie", "quantity": 2}]
        quote = self.service.quote("student", items, "express")
        order = self.service.place_order("student", items, "express")
        for key in quote:
            self.assertEqual(order[key], quote[key])
        reopened = OrderService(self.path)
        self.assertEqual(reopened.get_order(order["order_id"]), order)
        cancelled = reopened.cancel_order(order["order_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        for key in ("fulfillment", "items", "delivery_cents", "discount_cents", "total_cents"):
            self.assertEqual(cancelled[key], order[key])
        hoodie = next(p for p in reopened.catalog() if p["product_id"] == "hoodie")
        self.assertEqual(hoodie["stock"], 5)

    # Requirement 6: other fulfillment values still rejected
    def test_other_fulfillment_values_still_invalid(self):
        for value in ("Express", "overnight", ""):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.service.quote("regular", [{"product_id": "mug", "quantity": 1}], value)

    # Requirement 1: individual command (the exact example from CR-01)
    def test_cli_express_quote(self):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = main(["--data", str(self.path), "quote", "--customer", "student",
                         "--fulfillment", "express", "--item", "hoodie:2"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue())["total_cents"], 8400)

    # Requirements 1 and 7: interactive menu accepts express and the prompt mentions it
    def test_menu_express_quote(self):
        answers = iter(["2", "student", "hoodie", "2", "", "express", "0"])
        prompts = []
        def fake_input(prompt=""):
            prompts.append(prompt)
            return next(answers)
        out = io.StringIO()
        with patch("builtins.input", fake_input), redirect_stdout(out):
            run_menu(self.service)
        self.assertIn("Delivery: $12.00", out.getvalue())
        self.assertIn("Total: $84.00", out.getvalue())
        self.assertTrue(any("express" in p for p in prompts if p.startswith("Fulfillment")))