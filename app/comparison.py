"""两条已保存追迹结果的等价性比较。

按 seg_index 对齐两条追迹的状态（status / reason）与各分段字段：浮点字段以
统一的绝对误差容差判断（|a - b| ≤ tol 即视为相等），坐标与折射率等标量用
位置容差、方向分量用方向容差；字符串字段（status、reason、event）精确比较；
命中点等可空字段仅在两侧均存在时比较误差，恰有一侧为空也算差异。任一侧
缺失的分段（缺段）单独报告。本模块只读入参字典，不修改数据库原记录。

字段比较顺序（即 first_difference 的选取顺序）：先 status、reason 两个跟踪
级字段，再按 seg_index 升序、段内按 origin/direction/n_medium/hit_point/
event/n_after 的固定字段顺序比较。
"""
from __future__ import annotations

from typing import Any

# 段字段规范：(字段名, 在段字典中的取值路径, 容差种类)
# kind: position 用位置容差，direction 用方向容差，exact 为字符串精确比较
_SEGMENT_FIELD_SPECS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("origin.x", ("origin", "x"), "position"),
    ("origin.y", ("origin", "y"), "position"),
    ("direction.x", ("direction", "x"), "direction"),
    ("direction.y", ("direction", "y"), "direction"),
    ("n_medium", ("n_medium",), "position"),
    ("hit_point.x", ("hit_point", "x"), "position"),
    ("hit_point.y", ("hit_point", "y"), "position"),
    ("event", ("event",), "exact"),
    ("n_after", ("n_after",), "position"),
)


def _dig(segment: dict, path: tuple[str, ...]) -> Any:
    """按路径取段内嵌套值（如 hit_point.x）；父级为 None 时返回 None。"""
    value: Any = segment
    for key in path:
        if value is None:
            return None
        value = value[key]
    return value


def _float_equal(a: float | None, b: float | None, tol: float) -> bool:
    """统一浮点容差比较：|a - b| ≤ tol 视为相等；None 仅与 None 相等。"""
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= tol


def _field_entry(
    seg_index: int | None,
    field: str,
    left_value: Any,
    right_value: Any,
    abs_error: float | None = None,
) -> dict:
    """构造一个字段差异条目（seg_index 为 None 表示跟踪级字段）。"""
    return {
        "seg_index": seg_index,
        "field": field,
        "left_value": left_value,
        "right_value": right_value,
        "abs_error": abs_error,
        "missing_side": None,
    }


def _missing_segment_entry(seg_index: int, missing_side: str) -> dict:
    """构造一个缺段差异条目：field / 左右值 / 误差均为 None，仅给出缺段侧。"""
    return {
        "seg_index": seg_index,
        "field": None,
        "left_value": None,
        "right_value": None,
        "abs_error": None,
        "missing_side": missing_side,
    }


def compare_traces(
    left: dict,
    right: dict,
    position_tolerance: float,
    direction_tolerance: float,
) -> dict:
    """比较两条已保存追迹，返回等价性、状态差异、首个差异与全部分段差异。

    left / right 为 db.get_trace 返回的完整追迹字典；两个容差均为非负绝对
    误差。差异按规范顺序收集，第一个即 first_difference；不存在任何状态或
    分段差异时 equivalent 为 True。
    """
    ordered_diffs: list[dict] = []  # 跟踪级差异在前、段差异按索引/字段在后

    # 跟踪级状态字段：status、reason 均为精确比较
    status_equal = left["status"] == right["status"]
    reason_equal = left["reason"] == right["reason"]
    if not status_equal:
        ordered_diffs.append(
            _field_entry(None, "status", left["status"], right["status"])
        )
    if not reason_equal:
        ordered_diffs.append(
            _field_entry(None, "reason", left["reason"], right["reason"])
        )

    # 分段按 seg_index 对齐（不依赖两侧段数相同或连续）
    left_segments = {s["seg_index"]: s for s in left["segments"]}
    right_segments = {s["seg_index"]: s for s in right["segments"]}
    all_indices = sorted(set(left_segments) | set(right_segments))

    segment_differences: list[dict] = []
    for index in all_indices:
        left_seg = left_segments.get(index)
        right_seg = right_segments.get(index)
        if left_seg is None or right_seg is None:
            entry = _missing_segment_entry(
                index, "left" if left_seg is None else "right"
            )
            segment_differences.append(entry)
            ordered_diffs.append(entry)
            continue

        for field, path, kind in _SEGMENT_FIELD_SPECS:
            left_value = _dig(left_seg, path)
            right_value = _dig(right_seg, path)
            if kind == "exact":
                differs = left_value != right_value
                abs_error = None
            else:
                tol = (
                    position_tolerance if kind == "position" else direction_tolerance
                )
                differs = not _float_equal(left_value, right_value, tol)
                abs_error = (
                    None
                    if left_value is None or right_value is None
                    else abs(left_value - right_value)
                )
            if differs:
                entry = _field_entry(
                    index, field, left_value, right_value, abs_error
                )
                segment_differences.append(entry)
                ordered_diffs.append(entry)

    return {
        "left_trace_id": left["id"],
        "right_trace_id": right["id"],
        "position_tolerance": position_tolerance,
        "direction_tolerance": direction_tolerance,
        "equivalent": not ordered_diffs,
        "status_difference": {
            "equal": status_equal and reason_equal,
            "status_equal": status_equal,
            "reason_equal": reason_equal,
            "left_status": left["status"],
            "right_status": right["status"],
            "left_reason": left["reason"],
            "right_reason": right["reason"],
        },
        "first_difference": ordered_diffs[0] if ordered_diffs else None,
        "segment_differences": segment_differences,
    }
