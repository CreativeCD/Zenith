"""Unit tests for harness/tools/ast_tools.py (get_symbol, find_references, get_imports, list_symbols)."""

from harness.contracts import ResultStatus
from harness.tools.ast_tools import (
    find_references,
    get_imports,
    get_symbol,
    list_symbols,
)

SAMPLE_CODE = '''import os
from sys import path, version_info

# Configuration constant
DEFAULT_TIMEOUT = 30

class Calculator:
    """A mathematical calculation utility."""
    
    def __init__(self, precision: int = 2):
        self.precision = precision

    def add(self, a: float, b: float) -> float:
        """Add two numbers together."""
        return round(a + b, self.precision)

    def divide(self, a: float, b: float) -> float:
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        return a / b


def compute_metrics(x: int) -> int:
    calc = Calculator(precision=4)
    return calc.add(x, 10.5)
'''


def test_list_symbols(tmp_path):
    f = tmp_path / "calc_module.py"
    f.write_text(SAMPLE_CODE)

    res = list_symbols("calc_module.py", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "class Calculator" in res.raw_output
    assert "def compute_metrics" in res.raw_output
    assert "DEFAULT_TIMEOUT" in res.raw_output


def test_get_symbol_class(tmp_path):
    f = tmp_path / "calc_module.py"
    f.write_text(SAMPLE_CODE)

    res = get_symbol("calc_module.py", "Calculator", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "class Calculator" in res.raw_output
    assert "A mathematical calculation utility" in res.raw_output
    assert "def add" in res.raw_output
    assert "def divide" in res.raw_output


def test_get_symbol_function(tmp_path):
    f = tmp_path / "calc_module.py"
    f.write_text(SAMPLE_CODE)

    res = get_symbol("calc_module.py", "compute_metrics", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "def compute_metrics(x: int) -> int:" in res.raw_output


def test_get_symbol_missing(tmp_path):
    f = tmp_path / "calc_module.py"
    f.write_text(SAMPLE_CODE)

    res = get_symbol("calc_module.py", "non_existent_func", repo_root=str(tmp_path))
    assert res.status == ResultStatus.FAIL
    assert "not found" in res.raw_output


def test_get_imports(tmp_path):
    f = tmp_path / "calc_module.py"
    f.write_text(SAMPLE_CODE)

    res = get_imports("calc_module.py", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "import os" in res.raw_output
    assert "from sys import path, version_info" in res.raw_output


def test_find_references(tmp_path):
    f = tmp_path / "calc_module.py"
    f.write_text(SAMPLE_CODE)

    res = find_references("calc_module.py", "Calculator", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "calc = Calculator(precision=4)" in res.raw_output


def test_get_symbol_class_method(tmp_path):
    f = tmp_path / "calc_module.py"
    f.write_text(SAMPLE_CODE)

    res = get_symbol("calc_module.py", "Calculator.add", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "def add(self, a: float, b: float) -> float:" in res.raw_output
    assert "Add two numbers together." in res.raw_output


def test_get_symbol_non_python(tmp_path):
    js_code = """// User authentication service
export class AuthService {
    // Authenticate a bearer token
    login(token) {
        return token.valid;
    }
}
"""
    f = tmp_path / "auth.js"
    f.write_text(js_code)

    res = get_symbol("auth.js", "AuthService", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "AuthService in auth.js" in res.raw_output


def test_get_imports_multiline(tmp_path):
    code = """from typing import (
    Dict,
    List,
    Optional,
)
import sys
"""
    f = tmp_path / "types_test.py"
    f.write_text(code)

    res = get_imports("types_test.py", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "Dict, List, Optional" in res.raw_output


def test_find_references_directory_and_line_numbers(tmp_path):
    f1 = tmp_path / "src" / "worker.py"
    f1.parent.mkdir(parents=True)
    f1.write_text("line_1 = 1\nline_2 = 2\ntarget_call()\nline_4 = 4\n")

    res = find_references("src", "target_call", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "worker.py:3" in res.raw_output
    # Line 2 and line 4 context should have their accurate line numbers
    assert "   2:  line_2 = 2" in res.raw_output
    assert "   3:> target_call()" in res.raw_output
    assert "   4:  line_4 = 4" in res.raw_output


def test_get_symbol_class_attribute(tmp_path):
    """Verify get_symbol resolves class attributes and typed annotations."""
    code = """class AppConfig:
    TIMEOUT: int = 60
    API_KEY = "secret"
"""
    f = tmp_path / "config.py"
    f.write_text(code)

    res1 = get_symbol("config.py", "AppConfig.TIMEOUT", repo_root=str(tmp_path))
    assert res1.status == ResultStatus.SUCCESS
    assert "TIMEOUT: int = 60" in res1.raw_output

    res2 = get_symbol("config.py", "AppConfig.API_KEY", repo_root=str(tmp_path))
    assert res2.status == ResultStatus.SUCCESS
    assert 'API_KEY = "secret"' in res2.raw_output


def test_get_imports_conditional(tmp_path):
    """Verify get_imports captures imports nested inside if TYPE_CHECKING blocks."""
    code = """import sys
if TYPE_CHECKING:
    from typing import Sequence, Mapping
try:
    import ujson as json
except ImportError:
    import json
"""
    f = tmp_path / "deep_imports.py"
    f.write_text(code)

    res = get_imports("deep_imports.py", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "Sequence, Mapping" in res.raw_output
    assert "ujson" in res.raw_output
    assert "import sys" in res.raw_output


def test_list_symbols_typed_annotation(tmp_path):
    """Verify list_symbols includes typed module constants (AnnAssign)."""
    code = """DEFAULT_PORT: int = 8080
DEBUG_MODE: bool = False
MAX_RETRIES = 5
def run():
    pass
"""
    f = tmp_path / "constants.py"
    f.write_text(code)

    from harness.tools.ast_tools import list_symbols
    res = list_symbols("constants.py", repo_root=str(tmp_path))
    assert res.status == ResultStatus.SUCCESS
    assert "const DEFAULT_PORT" in res.raw_output
    assert "const DEBUG_MODE" in res.raw_output
    assert "const MAX_RETRIES" in res.raw_output
    assert "def run" in res.raw_output

