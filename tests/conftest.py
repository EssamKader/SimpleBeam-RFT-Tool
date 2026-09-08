import os
import sys

_LIB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "RFTBeamDetailing.extension",
    "lib",
)
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)
if os.path.dirname(os.path.abspath(__file__)) not in sys.path:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fake_revit_api  # noqa: E402

fake_revit_api.install()
