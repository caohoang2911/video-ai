"""Inline-SVG chart helpers: valid SVG on normal input, safe on empty/single/all-equal
(no divide-by-zero, no NaN coordinates)."""

from __future__ import annotations

from ai_operator.web import charts


def _ok(svg: str) -> None:
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert "nan" not in svg.lower()  # no NaN coordinates leaked from a zero-span scale


def test_sparkline_empty_is_no_data():
    svg = charts.sparkline([])
    _ok(svg)
    assert "chưa có dữ liệu" in svg


def test_sparkline_single_point_draws_a_dot():
    svg = charts.sparkline([5])
    _ok(svg)
    assert "<circle" in svg


def test_sparkline_all_equal_no_division_error():
    svg = charts.sparkline([3, 3, 3])
    _ok(svg)
    assert "<polyline" in svg


def test_sparkline_normal_series():
    svg = charts.sparkline([1, 9, 4, 7])
    _ok(svg)
    assert "<polyline" in svg and "<path" in svg


def test_bar_chart_empty_and_normal():
    _ok(charts.bar_chart([]))
    svg = charts.bar_chart([1, 2, 3])
    _ok(svg)
    assert svg.count("<rect") == 3


def test_views_sparkline_wrapper():
    _ok(charts.views_sparkline([10, 20, 30]))
