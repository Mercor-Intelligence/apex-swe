import importlib


def test_common_package_importable():
    module = importlib.import_module("common")
    assert module.__doc__ is not None
