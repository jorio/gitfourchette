# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

from gitfourchette.qt import *


class FilterChangeContext:
    """
    Context manager wrapper for QSortFilterProxyModel.beginFilterChange and
    endFilterChange. Backwards compatible with Qt versions 6.10 and older
    which lack these functions.
    """

    def __init__(self, model: QSortFilterProxyModel):
        self.model = model

    def __enter__(self):
        try:  # Qt 6.9+
            self.model.beginFilterChange()
        except AttributeError:  # pragma: no cover - TODO: Remove once we can drop compatibility with Qt <6.9
            pass  # Let __exit__ do the actual work

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:  # Qt 6.10+
            self.model.endFilterChange(QSortFilterProxyModel.Direction.Rows)
        except AttributeError:  # pragma: no cover - TODO: Remove once we can drop compatibility with Qt <6.10
            self.model.invalidateFilter()
