import tempfile
from unittest.mock import patch
from textual_cli_agent.config import ConfigManager


def test_config_manager_creation():
    """Test ConfigManager creates directories and initializes properly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": tmpdir}):
            config = ConfigManager("test-app")
            assert config.config_file_path.parent.exists()
            assert config.config_file_path.parent.name == "test-app"


def test_config_get_set():
    """Test basic get/set operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": tmpdir}):
            config = ConfigManager("test-app")

            # Test default value
            assert config.get("nonexistent", "default") == "default"

            # Test set and get
            config.set("test_key", "test_value")
            assert config.get("test_key") == "test_value"


def test_config_persistence():
    """Test config persists between instances."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": tmpdir}):
            # First instance
            config1 = ConfigManager("test-app")
            config1.set("persist_test", "persistent_value")

            # Second instance should load the same value
            config2 = ConfigManager("test-app")
            assert config2.get("persist_test") == "persistent_value"


def test_config_update():
    """Test bulk update operations."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": tmpdir}):
            config = ConfigManager("test-app")

            updates = {"auto_continue": True, "max_rounds": 8, "temperature": 0.7}
            config.update(updates)

            assert config.get("auto_continue") is True
            assert config.get("max_rounds") == 8
            assert config.get("temperature") == 0.7


def test_config_get_all():
    """Test getting all config values."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.dict("os.environ", {"XDG_CONFIG_HOME": tmpdir}):
            config = ConfigManager("test-app")

            config.update({"key1": "value1", "key2": "value2"})

            all_config = config.get_all()
            assert all_config["key1"] == "value1"
            assert all_config["key2"] == "value2"
