"""Operations used by the command-line order desk."""

from supplydesk.storage import JsonStore
from supplydesk.storage import JsonStore

CUSTOMER_TYPES = ("regular", "student")
FULFILLMENT_OPTIONS = ("pickup", "delivery")

MIN_QUANTITY = 1
MAX_QUANTITY = 99

STUDENT_DISCOUNT_PERCENT = 10
STUDENT_DISCOUNT_THRESHOLD_CENTS = 5000
DELIVERY_FEE_CENTS = 600
FREE_DELIVERY_THRESHOLD_CENTS = 10000

def _percent_rounded_half_up(amount_cents, percent):
    """Integer percentage of a cent amount; half a cent rounds up."""
    return (amount_cents * percent + 50) // 100

def _find_product(catalog, product_id):
    """Return the catalog entry with this ID, or None if there is none."""
    for product in catalog:
        if product["product_id"] == product_id:
            return product
    return None

def _find_order(orders, order_id):
    """Return the order with this ID, or raise ValueError."""
    for order in orders:
        if order["order_id"] == order_id:
            return order
    raise ValueError("Unknown order: " + order_id)

class OrderService:
    def __init__(self, state_path=".supplydesk/state.json"):
        self.store = JsonStore(state_path)

    def catalog(self):
        return self.store.load()["catalog"]

    def _build_quote(self, state, customer_type, items, fulfillment):
        """Validate a request and price it. Shared by quote() and place_order()."""
        if customer_type not in ("regular", "student"):
            raise ValueError("Customer type must be regular or student.")
        if fulfillment not in ("pickup", "delivery"):
            raise ValueError("Fulfillment must be pickup or delivery.")
        if not isinstance(items, list) or not items:
            raise ValueError("An order must contain at least one item.")
        lines = []
        requested = {}
        subtotal = 0

        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each item must contain a product_id and quantity.")
            product = None
            product = _find_product(state["catalog"], item.get("product_id"))
            if product is None:
                raise ValueError("Unknown product.")
            quantity = item.get("quantity")
            if type(quantity) is not int or quantity < MIN_QUANTITY or quantity > MAX_QUANTITY:
                raise ValueError(f"Quantity must be an integer from {MIN_QUANTITY} to {MAX_QUANTITY}.")
            requested[product["product_id"]] = requested.get(product["product_id"], 0) + quantity
            if requested[product["product_id"]] > product["stock"]:
                raise ValueError("Not enough stock for " + product["product_id"] + ".")
            line_total = product["unit_price_cents"] * quantity
            subtotal += line_total
            lines.append({
                "product_id": product["product_id"],
                "name": product["name"],
                "unit_price_cents": product["unit_price_cents"],
                "quantity": quantity,
                "line_total_cents": line_total,
            })
        if customer_type not in CUSTOMER_TYPES:
            raise ValueError("Customer type must be regular or student.")
        if fulfillment not in FULFILLMENT_OPTIONS:
            raise ValueError("Fulfillment must be pickup or delivery.")
        
        discount = 0
        delivery = 0
        if customer_type == "student" and subtotal >= STUDENT_DISCOUNT_THRESHOLD_CENTS:
            discount = _percent_rounded_half_up(subtotal, STUDENT_DISCOUNT_PERCENT)
        if fulfillment == "delivery" and subtotal - discount < FREE_DELIVERY_THRESHOLD_CENTS:
            delivery = DELIVERY_FEE_CENTS
        return {
            "customer_type": customer_type,
            "fulfillment": fulfillment,
            "items": lines,
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "delivery_cents": delivery,
            "total_cents": subtotal - discount + delivery,
        }    

    def quote(self, customer_type, items, fulfillment="pickup"):
        state = self.store.load()
        return self._build_quote(state, customer_type, items, fulfillment)

    def place_order(self, customer_type, items, fulfillment="pickup"):
        state = self.store.load()
        priced = self._build_quote(state, customer_type, items, fulfillment)
        order = {
            "order_id": "ORD-" + str(state["next_order_number"]).zfill(4),
            "status": "placed",
            **priced,
        }
        for line in priced["items"]:
            product = _find_product(state["catalog"], line["product_id"])
            if product is not None:
                product["stock"] -= line["quantity"]
        state["next_order_number"] += 1
        state["orders"].append(order)
        self.store.save(state)
        return order

    def list_orders(self):
        return self.store.load()["orders"]

    def get_order(self, order_id):
        return _find_order(self.store.load()["orders"], order_id)

    def cancel_order(self, order_id):
        state = self.store.load()
        order = _find_order(state["orders"], order_id)           
        if order["status"] == "cancelled":
            return order
    
        for line in order["items"]:
            product = _find_product(state["catalog"], line["product_id"])
            if product is not None:
                product["stock"] += line["quantity"]
        order["status"] = "cancelled"
        self.store.save(state)
        return order
