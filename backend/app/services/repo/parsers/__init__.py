from typing import Dict, List, Optional

from .base import BaseLanguageParser
from .c_parser import CParser
from .cpp_parser import CppParser
from .go_parser import GoParser
from .java_parser import JavaParser
from .javascript_parser import JavaScriptParser
from .python_parser import PythonParser
from .rust_parser import RustParser
from .typescript_parser import TypeScriptParser

PARSERS: List[BaseLanguageParser] = [
    PythonParser(),
    JavaScriptParser(),
    TypeScriptParser(),
    GoParser(),
    RustParser(),
    JavaParser(),
    CParser(),
    CppParser(),
]

EXTENSION_MAP: Dict[str, BaseLanguageParser] = {}
LANGUAGE_MAP: Dict[str, BaseLanguageParser] = {}

for parser in PARSERS:
    LANGUAGE_MAP[parser.language_name.lower()] = parser
    for ext in parser.supported_extensions:
        EXTENSION_MAP[ext.lower()] = parser

def get_parser_for_extension(ext: str) -> Optional[BaseLanguageParser]:
    if not ext:
        return None
    return EXTENSION_MAP.get(ext.lower())

def get_parser_for_language(lang: str) -> Optional[BaseLanguageParser]:
    if not lang:
        return None
    return LANGUAGE_MAP.get(lang.lower())

def get_supported_languages() -> List[str]:
    return [p.language_name for p in PARSERS]

__all__ = [
    "BaseLanguageParser",
    "CParser",
    "CppParser",
    "GoParser",
    "JavaParser",
    "JavaScriptParser",
    "PARSERS",
    "PythonParser",
    "RustParser",
    "TypeScriptParser",
    "get_parser_for_extension",
    "get_parser_for_language",
    "get_supported_languages",
]
