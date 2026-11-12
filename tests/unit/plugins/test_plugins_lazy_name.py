"""The lazy name `skye.Plugins` and the name in the `skye.plugins` facade (task 14.3, Requirement 56.1)."""


def test_plugins_is_a_lazy_name_of_skye_and_the_facade_name():
    """Task 14.3: `skye.Plugins` and `skye.plugins.Plugins` are the class of `skye.base.plugins`, and `import skye` does not load it."""
    import subprocess
    import sys

    import skye
    import skye.plugins
    from skye.base.plugins import Plugins

    assert skye.Plugins is Plugins
    assert skye.plugins.Plugins is Plugins
    assert "Plugins" in skye.__all__
    assert "Plugins" in skye.plugins.__all__
    code = "import sys, skye; print('skye.base.plugins' in sys.modules); skye.Plugins; print('skye.base.plugins' in sys.modules)"
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    before, after = done.stdout.split()
    assert before == "False" and after == "True"
