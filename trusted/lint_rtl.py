"""Conservative counter-MVP RTL gate. Not a sandbox substitute.

Only ANSI-port, single-module Verilog without strings, macros or system tasks is
admitted.  This intentionally rejects many valid but unnecessary Verilog forms.
"""
from __future__ import annotations

import re
from .oracle import FAMILIES

MAX_RTL_BYTES = 16_384


def strip_comments(src: str) -> str:
    """Lex comments without letting // inside /*...*/ or unterminated blocks escape."""
    out, i, n = [], 0, len(src)
    while i < n:
        if src.startswith('//', i):
            j = src.find('\n', i + 2)
            if j == -1:
                break
            out.append('\n')
            i = j + 1
        elif src.startswith('/*', i):
            j = src.find('*/', i + 2)
            if j == -1:
                raise ValueError('unterminated_block_comment')
            if '/*' in src[i + 2:j]:
                raise ValueError('nested_block_comment')
            out.append(' ' + '\n' * src[i:j+2].count('\n'))
            i = j + 2
        else:
            out.append(src[i]); i += 1
    return ''.join(out)


FORBIDDEN = re.compile(
    r'\b(?:initial|final|force|release|fork|join|join_any|join_none|import|export|'
    r'assign\s+strength|specify|endspecify|primitive|endprimitive|'
    r'bind|defparam|generate|endgenerate|interface|program|'
    r'event|wait|disable|forever|repeat|while|class|checker)\b'
)
MODULE = re.compile(r'\A\s*module\s+dut\s*\((?P<ports>[^()]*)\)\s*;'
                    r'(?P<body>.*?)\bendmodule\s*\Z', re.S)
PORT = re.compile(r'\s*(input|output)\s+(?:(?:wire|reg|logic)\s+)?'
                  r'(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?([a-zA-Z_]\w*)\s*\Z')


def _scan(src: str) -> tuple[str | None, list[str]]:
    errs = []
    if not isinstance(src, str) or not src:
        return None, ['empty_rtl']
    try:
        raw = src.encode('ascii')
    except UnicodeEncodeError:
        return None, ['non_ascii_rtl']
    if len(raw) > MAX_RTL_BYTES:
        return None, ['rtl_too_large']
    if any(ord(c) < 32 and c not in '\n\r\t' for c in src):
        return None, ['control_character']
    try:
        body = strip_comments(src)
    except ValueError as e:
        return None, [str(e)]
    # For four-bit counter, no construct below is necessary. Reject, do not attempt
    # to interpret strings/escaped identifiers/conditional preprocessing.
    for token, name in [('$', 'system_task'), ('`', 'preprocessor'),
                        ('\\', 'escaped_identifier'), ('"', 'string_literal'),
                        ("'\"", 'string_literal'), ('#', 'delay_or_parameter')]:
        if token in body:
            errs.append('forbidden:' + name)
    if FORBIDDEN.search(body):
        errs.append('forbidden:keyword')
    if re.search(r'\bmodule\b', body) and len(re.findall(r'\bmodule\b', body)) != 1:
        errs.append('multiple_modules')
    return body, errs


def static_lint(src: str) -> tuple[bool, list[str]]:
    body, errs = _scan(src)
    if body is None:
        return False, errs
    m = MODULE.fullmatch(body)
    if not m:
        errs.append('module_structure')
    return not errs, errs


def validate_interface(src: str, family: str) -> tuple[bool, list[str]]:
    if family not in FAMILIES:
        return False, ['unsupported_family']
    body, errors = _scan(src)
    if body is None or errors:
        return False, errors
    m = MODULE.fullmatch(body)
    if not m:
        return False, ['module_structure']
    given = {}
    for decl in m['ports'].split(','):
        p = PORT.fullmatch(decl)
        if not p:
            errors.append('non_ansi_or_invalid_port')
            continue
        direction, hi, lo, name = p.groups()
        if name in given:
            errors.append('duplicate_port:' + name)
        width = 1 if hi is None else (int(hi) - int(lo) + 1 if lo == '0' else -1)
        given[name] = (direction, width)
    if given != FAMILIES[family]['ports']:
        errors.append('port_map_mismatch:' + repr(given))
    return not errors, errors
