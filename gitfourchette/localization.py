# -----------------------------------------------------------------------------
# Copyright (C) 2026 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

"""
Bridge to gettext translations. Use _, _n, _np, _p to localize English text.
"""

from gettext import GNUTranslations
from gettext import NullTranslations


_translator = NullTranslations()


def installGettextTranslator(path: str = "") -> bool:
    """
    Load translations from a gettext '.mo' file.

    Return True if the translations were successfully loaded.

    If the given path is empty or doesn't exist, fall back to
    American English and return False.
    """

    global _translator

    if path:
        try:
            with open(path, 'rb') as fp:
                _translator = GNUTranslations(fp)
                return True
        except OSError:
            pass

    _translator = NullTranslations()
    return False


def _(message: str, *args, **kwargs) -> str:
    message = _translator.gettext(message)
    if args or kwargs:
        message = message.format(*args, **kwargs)
    return message


def _n(singular: str, plural: str, n: int, *args, **kwargs) -> str:
    return _translator.ngettext(singular, plural, n).format(*args, **kwargs, n=n)


def _np(context: str, singular: str, plural: str, n: int) -> str:
    return _translator.npgettext(context, singular, plural, n).format(n=n)


def _p(context: str, message: str, *args, **kwargs) -> str:
    message = _translator.pgettext(context, message)
    if args or kwargs:
        message = message.format(*args, **kwargs)
    return message


__all__ = [
    "_",
    "_n",
    "_np",
    "_p",
    "installGettextTranslator",
]
