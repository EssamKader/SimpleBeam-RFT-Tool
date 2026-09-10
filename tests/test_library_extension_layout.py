# -*- coding: utf-8 -*-
"""Guards the layout that lets a SECOND element reuse this library (#64).

pyRevit puts a UI extension's own ``lib/`` folder on **that extension's**
module path only. While ``rft`` lived in ``SimpleBeamRFT.extension/lib/``,
a future ``ColumnRFT.extension`` could not have imported it: the shared
code was real but unreachable.

The mechanism that fixes it is a **library extension** — a folder whose
name ends in ``.lib``. From pyRevit's own
``pyrevitlib/pyrevit/extensions/extensionmgr.py``::

    def _update_extension_search_paths(ui_ext, lib_ext_list, pyrvt_paths):
        for lib_ext in lib_ext_list:
            ui_ext.add_module_path(lib_ext.directory)

``get_installed_ui_extensions`` collects every ``.lib`` under the
registered search roots and adds each one to the module path of *every* UI
extension.

Two properties of that mechanism are load-bearing, and each has its own
test below because each fails SILENTLY — the tool keeps working on this
machine while the next element cannot import anything:

1. The path added is the ``.lib`` **directory itself**, not a ``lib/``
   subfolder inside it, so the package must sit at ``RFT.lib/rft``.
2. An extension's own internal ``lib/`` paths are added **first** and
   therefore take **precedence** over ``.lib`` paths. A leftover copy
   inside the UI extension would shadow the shared one, and the shadowing
   copy is the one that would drift.

None of this can be verified by importing anything: under pytest the
package is on ``sys.path`` because ``tests/conftest.py`` puts it there.
Only the on-disk layout tells the truth, so these tests ask the
filesystem.
"""

import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_EXT = os.path.join(REPO_ROOT, "SimpleBeamRFT.extension")
LIB_EXT = os.path.join(REPO_ROOT, "RFT.lib")


def test_the_library_extension_folder_name_ends_in_lib():
    """``LibraryExtension.matches`` is a suffix test on the folder name.

    ``LIB_EXTENSION_POSTFIX = '.lib'`` in pyRevit's
    ``extensions/__init__.py``, and ``matches`` is
    ``component_path.lower().endswith(cls.type_id)``. Rename the folder to
    ``RFT-lib`` or ``RFTlib`` and pyRevit stops treating it as a library
    extension entirely — it becomes an ordinary folder that nothing is
    told about.
    """
    assert os.path.isdir(LIB_EXT), (
        "the shared library extension is missing: expected %s"
        % os.path.relpath(LIB_EXT, REPO_ROOT))
    assert os.path.basename(LIB_EXT).lower().endswith(".lib"), (
        "%r does not end in .lib, so pyRevit will not add it to any "
        "extension's module path" % os.path.basename(LIB_EXT))


def test_the_package_sits_directly_in_the_library_extension():
    """``RFT.lib/rft/``, never ``RFT.lib/lib/rft/``.

    pyRevit adds ``lib_ext.directory`` — the ``.lib`` folder itself. A
    ``lib/`` level inside it is the intuitive layout (it mirrors a UI
    extension) and it is wrong: ``import rft`` would fail because what is
    on the path is the parent of ``lib``, not of ``rft``.
    """
    assert os.path.isfile(os.path.join(LIB_EXT, "rft", "__init__.py")), (
        "expected the package at RFT.lib/rft/__init__.py -- pyRevit puts "
        "the .lib folder itself on the module path, so a lib/ level "
        "inside it would make `import rft` fail")
    assert not os.path.isdir(os.path.join(LIB_EXT, "lib")), (
        "RFT.lib/lib/ exists: the .lib folder itself is what goes on the "
        "module path, so this extra level breaks the import")


def test_the_ui_extension_does_not_shadow_the_shared_library():
    """No ``rft`` package anywhere inside the UI extension.

    pyRevit's own comment on the matter: paths internal to the extension
    and tool bundles "have already been set inside the extension bundles
    and will take precedence over paths added by this method". So a
    leftover ``SimpleBeamRFT.extension/lib/rft/`` wins over ``RFT.lib``,
    and it wins invisibly — the beam tool keeps working while every other
    element loads a different copy.

    Checked as "no ``rft`` package under the UI extension at all" rather
    than "no ``lib/`` folder", because any internal module path has the
    same effect.
    """
    shadowing = []
    for dirpath, dirnames, filenames in os.walk(UI_EXT):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        if os.path.basename(dirpath) == "rft" and "__init__.py" in filenames:
            shadowing.append(
                os.path.relpath(dirpath, REPO_ROOT).replace("\\", "/"))

    assert not shadowing, (
        "these copies of the rft package live inside the UI extension and "
        "take PRECEDENCE over RFT.lib, so the shared library would be "
        "silently unused: %s" % shadowing)


def test_both_extensions_are_under_one_search_root():
    """The registered pyRevit search path is the folder that CONTAINS the
    extensions, and it must contain both.

    This is why the move needed no re-registration: ``RFT.lib`` and
    ``SimpleBeamRFT.extension`` are siblings at the repo root, which is
    already the registered root. Nest either one a level deeper and
    ``get_installed_ui_extensions`` stops finding it without saying so.
    """
    assert os.path.dirname(LIB_EXT) == os.path.dirname(UI_EXT) == REPO_ROOT, (
        "RFT.lib and SimpleBeamRFT.extension must be siblings at the repo "
        "root, which is the registered pyRevit search path")
