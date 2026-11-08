"""A small starting test suite for the order desk."""

from pathlib import Path
import tempfile
import unittest

from supplydesk.service import OrderService


class OrderSmokeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.service = OrderService(self.path)

    def test_regular_pickup_quote(self):
        quote = self.service.quote("regular", [{"product_id": "notebook", "quantity": 2}])
        self.assertEqual(quote["subtotal_cents"], 1000)
        self.assertEqual(quote["discount_cents"], 0)
        self.assertEqual(quote["delivery_cents"], 0)
        self.assertEqual(quote["total_cents"], 1000)

    def test_student_delivery_quote(self):
        quote = self.service.quote("student", [{"product_id": "hoodie", "quantity": 2}], "delivery")
        self.assertEqual(quote["discount_cents"], 800)
        self.assertEqual(quote["delivery_cents"], 600)
        self.assertEqual(quote["total_cents"], 7800)

    def test_order_can_be_reopened(self):
        order = self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        self.assertEqual(order["order_id"], "ORD-0001")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(OrderService(self.path).get_order(order["order_id"]), order)

    def test_cancel_order_restores_stock(self):
        before = self.service.catalog()
        order = self.service.place_order("regular", [{"product_id": "pen-pack", "quantity": 2}])
        cancelled = self.service.cancel_order(order["order_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.service.catalog(), before)

    #Normal behavior
    def test_regular_delivery_place_order(self):
        order = self.service.place_order("regular", [{"product_id": "hoodie", "quantity": 5}], "delivery")
        hoodie = next(p for p in self.service.catalog() if p["product_id"] == "hoodie")
        self.assertEqual(hoodie["stock"], 0)
        self.assertEqual(order["subtotal_cents"], 20000)
        self.assertEqual(order["discount_cents"], 0)
        self.assertEqual(order["delivery_cents"], 0)
        self.assertEqual(order["total_cents"], 20000)
        self.assertEqual(order["order_id"], "ORD-0001")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(OrderService(self.path).get_order(order["order_id"]), order)

    # Boundary: student subtotal exactly 5000 cents should get the 10% discount
    def test_student_discount_at_exact_threshold(self):
        quote = self.service.quote("student", [{"product_id": "bag", "quantity": 2}])
        self.assertEqual(quote["subtotal_cents"], 5000)
        self.assertEqual(quote["discount_cents"], 500)   # spec: "at least 5,000"
        self.assertEqual(quote["total_cents"], 4500)

    # Boundary: delivery becomes free at exactly 10000 cents
    def test_delivery_free_at_exact_threshold(self):
        quote = self.service.quote("regular", [{"product_id": "bag", "quantity": 4}], "delivery")
        self.assertEqual(quote["subtotal_cents"], 10000)
        self.assertEqual(quote["delivery_cents"], 0)

    # Boundary: ordering again after stock reaches 0 is rejected
    def test_order_rejected_when_stock_is_zero(self):
        self.service.place_order("regular", [{"product_id": "hoodie", "quantity": 5}])
        with self.assertRaises(ValueError):
            self.service.place_order("regular", [{"product_id": "hoodie", "quantity": 1}])
    
    # Invalid: unsupported customer, fulfillment, product, and empty list
    def test_invalid_request_values_rejected(self):
        bad_requests = [
            ("teacher", [{"product_id": "mug", "quantity": 1}], "pickup"),
            ("regular", [{"product_id": "mug", "quantity": 1}], "drone"),
            ("regular", [{"product_id": "laptop", "quantity": 1}], "pickup"),
            ("regular", [], "pickup"),
        ]
        for customer, items, fulfillment in bad_requests:
            with self.subTest(customer=customer, items=items, fulfillment=fulfillment):
                with self.assertRaises(ValueError):
                    self.service.place_order(customer, items, fulfillment)

    # Invalid: quantities outside 1..99 or not a real int
    def test_invalid_quantities_rejected(self):
        for quantity in (0, 100, "2", "two", 1.5, True):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValueError):
                    self.service.quote("regular", [{"product_id": "notebook", "quantity": quantity}])

    # Invalid: a rejected order must not change stock, history, or order numbering
    def test_rejected_order_changes_nothing(self):
        before = self.service.catalog()
        with self.assertRaises(ValueError):
            self.service.place_order("regular", [{"product_id": "mug", "quantity": 1},
                                                 {"product_id": "laptop", "quantity": 1}])
        self.assertEqual(self.service.catalog(), before)
        self.assertEqual(self.service.list_orders(), [])
        order = self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        self.assertEqual(order["order_id"], "ORD-0001")

    def test_unknown_order_id_rejected(self):
        with self.assertRaises(ValueError):
            self.service.get_order("ORD-9999")
        with self.assertRaises(ValueError):
            self.service.cancel_order("ORD-9999")

    # Suspected defect: combined quantity on duplicate lines must not exceed stock (5 hoodies)
    def test_duplicate_lines_exceeding_stock_rejected(self):
        with self.assertRaises(ValueError):
            self.service.place_order("regular", [{"product_id": "hoodie", "quantity": 3},
                                                 {"product_id": "hoodie", "quantity": 3}])

    # Suspected defect: cancelling twice must not restore stock twice
    def test_cancel_twice_does_not_restore_stock_twice(self):
        before = self.service.catalog()
        order = self.service.place_order("regular", [{"product_id": "mug", "quantity": 2}])
        self.service.cancel_order(order["order_id"])
        again = self.service.cancel_order(order["order_id"])
        self.assertEqual(again["status"], "cancelled")
        self.assertEqual(self.service.catalog(), before)        

if __name__ == "__main__":
    unittest.main()
