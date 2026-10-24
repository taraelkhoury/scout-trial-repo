import tempfile
import unittest
from pathlib import Path

from app import (
    authenticate,
    create_order,
    get_orders,
    initialize_database,
    update_product,
)


class DeliveryAppTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.sqlite3"
        self.credentials = initialize_database(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_demo_passwords_authenticate_and_sql_like_username_is_rejected(self):
        self.assertEqual(self.credentials, {"admin": "admin", "alex": "alex"})
        admin = authenticate(self.db_path, "admin", "admin")
        self.assertEqual(admin["role"], "admin")
        alex = authenticate(self.db_path, "alex", "alex")
        self.assertEqual(alex["role"], "user")
        self.assertIsNone(authenticate(self.db_path, "admin--", "anything"))
        self.assertIsNone(authenticate(self.db_path, "admin", "wrong"))

    def test_database_initialization_sets_demo_passwords_on_existing_database(self):
        initialize_database(self.db_path)
        self.assertEqual(authenticate(self.db_path, "admin", "admin")["role"], "admin")
        self.assertEqual(authenticate(self.db_path, "alex", "alex")["role"], "user")

    def test_order_total_is_calculated_from_database_prices(self):
        customer = authenticate(self.db_path, "alex", self.credentials["alex"])
        order_id = create_order(
            self.db_path, customer["id"], [{"product_id": 1, "quantity": 2}]
        )
        orders = get_orders(self.db_path, customer["id"], customer["role"])
        self.assertEqual(orders[0]["id"], order_id)
        self.assertEqual(orders[0]["total_cents"], 798)

    def test_orders_reject_zero_negative_and_boolean_quantities(self):
        customer = authenticate(self.db_path, "alex", self.credentials["alex"])
        for quantity in (0, -1, True):
            with self.subTest(quantity=quantity):
                with self.assertRaises(ValueError):
                    create_order(
                        self.db_path,
                        customer["id"],
                        [{"product_id": 1, "quantity": quantity}],
                    )

    def test_customer_cannot_edit_product(self):
        customer = authenticate(self.db_path, "alex", self.credentials["alex"])
        with self.assertRaises(PermissionError):
            update_product(
                self.db_path, customer["role"], 1, "Changed", 100, True
            )

    def test_admin_can_edit_product(self):
        admin = authenticate(self.db_path, "admin", self.credentials["admin"])
        update_product(
            self.db_path, admin["role"], 1, "Local pears", 425, False
        )
        customer = authenticate(self.db_path, "alex", self.credentials["alex"])
        with self.assertRaises(ValueError):
            create_order(
                self.db_path, customer["id"], [{"product_id": 1, "quantity": 1}]
            )

    def test_delivery_instructions_are_saved_and_scoped_to_owner_and_admin(self):
        customer = authenticate(self.db_path, "alex", "alex")
        admin = authenticate(self.db_path, "admin", "admin")
        note = "Leave by the side door."
        order_id = create_order(
            self.db_path, customer["id"], [{"product_id": 1, "quantity": 1}], note
        )
        self.assertEqual(get_orders(self.db_path, customer["id"], "user")[0]["delivery_instructions"], note)
        self.assertEqual(get_orders(self.db_path, admin["id"], "admin")[0]["id"], order_id)
        self.assertEqual(get_orders(self.db_path, admin["id"], "user"), [])

    def test_delivery_instructions_validation(self):
        customer = authenticate(self.db_path, "alex", "alex")
        for note in (None, 123, "x" * 2001):
            with self.subTest(note_type=type(note).__name__):
                with self.assertRaises(ValueError):
                    create_order(self.db_path, customer["id"], [{"product_id": 1, "quantity": 1}], note)

    def test_customers_only_receive_their_own_orders(self):
        admin = authenticate(self.db_path, "admin", self.credentials["admin"])
        customer = authenticate(self.db_path, "alex", self.credentials["alex"])
        create_order(self.db_path, customer["id"], [{"product_id": 1, "quantity": 1}])
        create_order(self.db_path, admin["id"], [{"product_id": 2, "quantity": 1}])
        all_orders = get_orders(self.db_path, admin["id"], admin["role"])
        customer_orders = get_orders(self.db_path, customer["id"], customer["role"])
        self.assertEqual(len(all_orders), 2)
        self.assertEqual([order["username"] for order in customer_orders], ["alex"])


if __name__ == "__main__":
    unittest.main()
