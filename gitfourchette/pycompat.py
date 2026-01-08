# NOTE: Some parts adapted from cpython

import enum as _enum
import glob as _glob
import multiprocessing as _multiprocessing
import sys as _sys


# Use same multiprocessing default start method as Python 3.14 on Linux
if (_sys.version_info < (3, 14)
        and _sys.platform not in ["darwin", "win32"]
        and _multiprocessing.get_start_method(True) is None):
    _multiprocessing.set_start_method("forkserver")


# Python 3.10 compatibility (enum.StrEnum is new in Python 3.11)
if not hasattr(_enum, "StrEnum"):
    class _StrEnumCompat(str, _enum.Enum):
        def __new__(cls, *values):
            if len(values) != 1 or not isinstance(values[0], str):
                raise ValueError("StrEnum value must be a 1-value tuple containing a string")
            value = str(*values)
            member = str.__new__(cls, value)
            member._value_ = value
            return member

        def __str__(self):
            return self._value_

    _enum.StrEnum = _StrEnumCompat


# Python 3.10, 3.11, 3.12 compatibility (glob.translate is new Python 3.13)
# Adapted from cpython/Lib/glob.py
if not hasattr(_glob, "translate"):
    def _globTranslate(pat: str, recursive: bool, include_hidden: bool):
        if not recursive:
            raise NotImplementedError()
        if not include_hidden:
            raise NotImplementedError()

        import re
        seps = "/"
        escaped_seps = ''.join(map(re.escape, seps))
        any_sep = escaped_seps
        not_sep = f'[^{escaped_seps}]'
        one_last_segment = f'{not_sep}+'
        one_segment = f'{one_last_segment}{any_sep}'
        any_segments = f'(?:.+{any_sep})?'
        any_last_segments = '.*'

        results = []
        parts = re.split(any_sep, pat)
        last_part_idx = len(parts) - 1
        for idx, part in enumerate(parts):
            if part == '*':
                results.append(one_segment if idx < last_part_idx else one_last_segment)
            elif part == '**':
                if idx < last_part_idx:
                    if parts[idx + 1] != '**':
                        results.append(any_segments)
                else:
                    results.append(any_last_segments)
            else:
                if part:
                    results.extend(_fnmatch_translate(part, f'{not_sep}*', not_sep))
                if idx < last_part_idx:
                    results.append(any_sep)
        res = ''.join(results)
        return fr'(?s:{res})\Z'

    def _fnmatch_translate(pat, star, question_mark):
        import re
        import functools
        _re_setops_sub = re.compile(r'([&~|])').sub
        _re_escape = functools.lru_cache(maxsize=512)(re.escape)

        res = []
        add = res.append

        i, n = 0, len(pat)
        while i < n:
            c = pat[i]
            i = i + 1
            if c == '*':
                # store the position of the wildcard
                add(star)
                # compress consecutive `*` into one
                while i < n and pat[i] == '*':
                    i += 1
            elif c == '?':
                add(question_mark)
            elif c == '[':
                j = i
                if j < n and pat[j] == '!':
                    j = j + 1
                if j < n and pat[j] == ']':
                    j = j + 1
                while j < n and pat[j] != ']':
                    j = j + 1
                if j >= n:
                    add('\\[')
                else:
                    stuff = pat[i:j]
                    if '-' not in stuff:
                        stuff = stuff.replace('\\', r'\\')
                    else:
                        chunks = []
                        k = i + 2 if pat[i] == '!' else i + 1
                        while True:
                            k = pat.find('-', k, j)
                            if k < 0:
                                break
                            chunks.append(pat[i:k])
                            i = k + 1
                            k = k + 3
                        chunk = pat[i:j]
                        if chunk:
                            chunks.append(chunk)
                        else:
                            chunks[-1] += '-'
                        # Remove empty ranges -- invalid in RE.
                        for k in range(len(chunks) - 1, 0, -1):
                            if chunks[k - 1][-1] > chunks[k][0]:
                                chunks[k - 1] = chunks[k - 1][:-1] + chunks[k][1:]
                                del chunks[k]
                        # Escape backslashes and hyphens for set difference (--).
                        # Hyphens that create ranges shouldn't be escaped.
                        stuff = '-'.join(s.replace('\\', r'\\').replace('-', r'\-')
                                         for s in chunks)
                    i = j + 1
                    if not stuff:
                        # Empty range: never match.
                        add('(?!)')
                    elif stuff == '!':
                        # Negated empty range: match any character.
                        add('.')
                    else:
                        # Escape set operations (&&, ~~ and ||).
                        stuff = _re_setops_sub(r'\\\1', stuff)
                        if stuff[0] == '!':
                            stuff = '^' + stuff[1:]
                        elif stuff[0] in ('^', '['):
                            stuff = '\\' + stuff
                        add(f'[{stuff}]')
            else:
                add(_re_escape(c))
        assert i == n
        return res

    _glob.translate = _globTranslate
