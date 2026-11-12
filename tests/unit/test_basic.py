"""Basic test to verify test infrastructure."""


def test_import_skye():
    """Test that skye package can be imported."""
    import skye

    assert skye.__version__ == "0.2.0"


def test_import_interfaces():
    """Test that interfaces module can be imported."""
    import skye.base.interfaces

    assert skye.base.interfaces is not None


def test_import_providers():
    """Test that providers module can be imported."""
    import skye.models

    assert skye.models is not None
