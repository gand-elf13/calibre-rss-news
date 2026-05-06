# recipe_loader.py – load a .recipe file and return instantiated recipe class

import sys
import os
import importlib.util
import shutil
import tempfile
import logging
import types

logger = logging.getLogger("recipe_loader")

# Names exported from our stubs that are base classes (skip when searching for the recipe class)
_BASE_CLASS_NAMES = frozenset(['BasicNewsRecipe', 'Browser', 'PersistentTemporaryFile'])


def _ensure_calibre_stubs():
    """Ensure calibre.* stubs are wired up. Safe to call multiple times."""
    if 'calibre.web.feeds.news' not in sys.modules:
        from calibre_compat import install
        install()


def load_recipe_file(path):
    """
    Load a .recipe file and return an instantiated recipe object.
    The recipe class is identified as the first class that subclasses BasicNewsRecipe.
    """
    _ensure_calibre_stubs()
    from calibre_compat import BasicNewsRecipe

    # .recipe files are Python — copy with .py extension so importlib is happy
    tmp_dir = tempfile.mkdtemp(prefix='calibre_rss_')
    try:
        py_path = os.path.join(tmp_dir, 'recipe_module.py')
        shutil.copy(path, py_path)

        spec = importlib.util.spec_from_file_location('_calibre_recipe', py_path)
        mod  = importlib.util.module_from_spec(spec)

        # Give the module a clean but plausible __package__ so relative imports work
        mod.__package__ = ''
        spec.loader.exec_module(mod)

        # Find the recipe class
        for name in dir(mod):
            if name in _BASE_CLASS_NAMES:
                continue
            obj = getattr(mod, name)
            if (
                isinstance(obj, type)
                and issubclass(obj, BasicNewsRecipe)
                and obj is not BasicNewsRecipe
            ):
                logger.debug(f"Found recipe class: {name}")
                return obj()

        raise RuntimeError(f"No BasicNewsRecipe subclass found in {path}")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
