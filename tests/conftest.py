import os
import sys

# pyRevit puts a LIBRARY extension's own directory on the module path of
# every UI extension, so `RFT.lib` (not a `lib/` inside it) is what the
# `rft` package sits in -- see docs/reuse-for-new-elements.md.
_LIB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "RFT.lib",
)
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_revit_api  # noqa: E402

fake_revit_api.install()
