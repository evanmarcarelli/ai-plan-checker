"""Code adoption layer.

Answers "for this jurisdiction, which code editions + amendments apply, and
which corpus layers should we search?" — the maintained adoption map plus an
address -> jurisdiction -> adoption record -> layer-stack resolver.
"""
from app.code_library.adoption.resolver import (
    AdoptionResolver,
    ResolvedStack,
    get_resolver,
)
from app.code_library.adoption.schema import AdoptionRecord

__all__ = ["AdoptionResolver", "ResolvedStack", "get_resolver", "AdoptionRecord"]
