"""Shared test setup.

Windows: load cvxpy (and through it osqp) before pandas, pyarrow or scikit-learn. Those
packages load their own copies of the Microsoft C++ runtime (msvcp140.dll); pyarrow's is
old (14.28), and whichever copy loads first is used by every later compiled library in the
process. Loaded after it, cvxpy's compiled core crashes with an access violation (D-026).
pytest imports this file before any test module, so this import runs first.
"""

import cvxpy  # noqa: F401
import optbinning  # noqa: F401
