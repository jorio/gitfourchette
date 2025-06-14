# -----------------------------------------------------------------------------
# Copyright (C) 2025 Iliyas Jorio.
# This file is part of GitFourchette, distributed under the GNU GPL v3.
# For full terms, see the included LICENSE file.
# -----------------------------------------------------------------------------

# In December 2024, GitFourchette migrated to gettext due to shortcomings
# in Qt Linguist tooling for Python:
# - In PyQt6, self.tr() incorrectly returns non-localized text when called
#   from a subclass of the class that defines the string;
# - pylupdate6 forces a context in contextless tr() calls.
# - pyside6-lupdate yields better results, but it isn't readily available on
#   some Linux distros, causing friction for contributors;
# - pyside6-lupdate ignores plurals in translate() (explicit context);
# - pyside6-lupdate -pluralsonly (for English) doesn't play well with Weblate.
#
# Benefits of gettext:
# - It just works. No weird edge cases causing English text to pop up in an
#   otherwise complete localization;
# - POEdit or xgettext/msgmerge are easier to install for contributors;
# - Weblate has great support for gettext;
# - Custom gettext functions allow for reduced visual noise in the code;
# - English plurals are defined straight from the code. No need for "actual
#   English" translations of "developer English" strings such as "%n file(s)".

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
