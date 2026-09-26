"""Unit tests for toy calculator fixture."""

from calculator import add, divide, multiply, subtract


def test_add():
    assert add(2, 3) == 5

def test_subtract():
    assert subtract(5, 2) == 3

def test_multiply():
    assert multiply(3, 4) == 12

def test_divide_normal():
    assert divide(10, 2) == 5
