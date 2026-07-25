"""Bus name expansion and per-sheet bus connectivity graph (GH #25).

Pure bus logic, isolated from the rest of the analyzer: stdlib-only and no
imports from analyze_schematic. Replicates KiCad's bus semantics: ordered
vector expansion, group/labeled-group buses (dot-joined members), nested
groups, bus_alias resolution inside groups, and the _{...}/^{...}/~{...}
text-markup exclusion.
"""

import re

_VECTOR_RE = re.compile(r"^(?P<prefix>[^\[\]{}\s]+)\[(?P<a>\d+)\.\.(?P<b>\d+)\]$")
_GROUP_RE = re.compile(r"^(?P<prefix>[^\[\]{}\s]*)\{(?P<members>[^{}]+)\}$")
_MAX_DEPTH = 4


def expand_bus_name(name, aliases=None, _depth=0):
    """Ordered member expansion for a KiCad bus name; None if not a bus."""
    if _depth > _MAX_DEPTH or not isinstance(name, str) or not name:
        return None
    m = _VECTOR_RE.match(name)
    if m:
        a, b = int(m.group("a")), int(m.group("b"))
        step = 1 if b >= a else -1
        return [f"{m.group('prefix')}{i}" for i in range(a, b + step, step)]
    m = _GROUP_RE.match(name)
    if m:
        prefix = m.group("prefix")
        # _{...}/^{...}/~{...} is KiCad subscript/superscript/overline
        # markup on a plain net name, not a bus group.
        if prefix.endswith(("_", "^", "~")):
            return None
        members = []
        for tok in m.group("members").split():
            if aliases and tok in aliases:
                sub = []
                for am in aliases[tok]:
                    nested = expand_bus_name(am, aliases, _depth + 1)
                    sub.extend(nested if nested else [am])
            else:
                sub = expand_bus_name(tok, aliases, _depth + 1) or [tok]
            for member in sub:
                members.append(f"{prefix}.{member}" if prefix else member)
        return members or None
    return None
