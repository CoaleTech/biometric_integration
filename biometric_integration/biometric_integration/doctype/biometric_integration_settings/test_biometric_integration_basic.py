import frappe
from frappe.tests.utils import FrappeTestCase

class TestBiometricIntegrationBasic(FrappeTestCase):
    def test_imports(self):
        """Test that all core modules can be imported"""
        try:
            from biometric_integration.biometric_integration.doctype.biometric_device.biometric_device import BiometricDevice
            from biometric_integration.biometric_integration.doctype.biometric_device_command.biometric_device_command import add_command
            from biometric_integration.biometric_integration.doctype.biometric_device_user.biometric_device_user import get_or_create_user_by_pin
            from biometric_integration.commands.utils import get_status_logic
            import biometric_integration.api
            self.assertTrue(True, "All imports successful")
        except Exception as e:
            self.fail(f"Import failed: {e}")

    def test_user_creation(self):
        """Test user creation functionality"""
        from biometric_integration.biometric_integration.doctype.biometric_device_user.biometric_device_user import get_or_create_user_by_pin

        # Test creating a new user
        user = get_or_create_user_by_pin("TEST001", "Test User")
        self.assertIsNotNone(user)
        self.assertEqual(user.user_id, "TEST001")

        # Test getting existing user
        user2 = get_or_create_user_by_pin("TEST001")
        self.assertEqual(user.name, user2.name)

    def test_status_logic(self):
        """Test status logic"""
        from biometric_integration.commands.utils import get_status_logic

        status = get_status_logic("test_site")
        self.assertIn("status", status)
        self.assertEqual(status["status"], "disabled")  # Should be disabled by default