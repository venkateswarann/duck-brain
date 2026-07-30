#!/usr/bin/env python3
"""Validate the robot description in assets/ before trusting the 3D viewer.

Catches the failure modes that make the Viz page render a scrambled or
giant duck instead of a robot:

  * meshes referenced by the URDF but missing from disk
  * meshes whose units disagree with the URDF (the print/ STLs are in
    millimetres, the robot description STLs are in metres)
  * a link tree that does not assemble into a robot of the expected size

Run:  python3 scripts/check_robot_assets.py
"""

from __future__ import annotations

import math
import struct
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

# Open Duck Mini v2 is ~42 cm tall with legs extended, ~20 cm wide at the head.
EXPECTED_HEIGHT_M = (0.25, 0.55)
EXPECTED_WIDTH_M = (0.10, 0.35)


def fail(msg: str) -> None:
    print(f"FAIL  {msg}")


def ok(msg: str) -> None:
    print(f"ok    {msg}")


# --- tiny 4x4 matrix helpers (avoids a numpy dependency for a CLI check) ---


def mat_identity() -> list[list[float]]:
    return [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]


def mat_mul(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def mat_from_origin(xyz: tuple[float, float, float], rpy: tuple[float, float, float]) -> list[list[float]]:
    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    # URDF convention: R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    r = [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]
    m = mat_identity()
    for i in range(3):
        for j in range(3):
            m[i][j] = r[i][j]
        m[i][3] = xyz[i]
    return m


def transform_point(m: list[list[float]], p: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(m[i][0] * p[0] + m[i][1] * p[1] + m[i][2] * p[2] + m[i][3] for i in range(3))  # type: ignore[return-value]


def parse_origin(elem) -> list[list[float]]:
    if elem is None:
        return mat_identity()
    origin = elem.find("origin")
    if origin is None:
        return mat_identity()
    xyz = tuple(float(v) for v in (origin.get("xyz") or "0 0 0").split())
    rpy = tuple(float(v) for v in (origin.get("rpy") or "0 0 0").split())
    return mat_from_origin(xyz, rpy)  # type: ignore[arg-type]


def stl_bbox(path: Path) -> tuple[int, tuple[float, float, float], tuple[float, float, float]]:
    """Return (triangle_count, min_xyz, max_xyz) for a binary or ASCII STL."""
    data = path.read_bytes()
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3

    if data[:5].lower().lstrip().startswith(b"solid") and b"facet" in data[:2048]:
        count = 0
        for line in data.decode("utf-8", errors="replace").splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == "vertex":
                for j in range(3):
                    v = float(parts[j + 1])
                    lo[j] = min(lo[j], v)
                    hi[j] = max(hi[j], v)
                count += 1
        return count // 3, tuple(lo), tuple(hi)  # type: ignore[return-value]

    tri_count = struct.unpack("<I", data[80:84])[0]
    offset = 84
    for _ in range(tri_count):
        if offset + 50 > len(data):
            break
        for v in range(3):
            base = offset + 12 + v * 12
            x, y, z = struct.unpack("<fff", data[base : base + 12])
            for j, c in enumerate((x, y, z)):
                lo[j] = min(lo[j], c)
                hi[j] = max(hi[j], c)
        offset += 50
    return tri_count, tuple(lo), tuple(hi)  # type: ignore[return-value]


def main() -> int:
    urdf_path = ASSETS / "robot.urdf"
    if not urdf_path.exists():
        fail(f"{urdf_path} not found")
        return 1

    root = ET.parse(urdf_path).getroot()
    links = {l.get("name"): l for l in root.findall("link")}
    joints = root.findall("joint")
    problems = 0

    print(f"URDF: {urdf_path.relative_to(ROOT)}")
    print(f"  links={len(links)} joints={len(joints)}")
    movable = [j for j in joints if j.get("type") in ("revolute", "continuous", "prismatic")]
    print(f"  movable joints={len(movable)}: {', '.join(sorted(j.get('name') or '' for j in movable))}")
    print()

    # --- 1. every referenced mesh exists ---
    refs: set[str] = set()
    for mesh in root.iter("mesh"):
        fn = mesh.get("filename") or ""
        refs.add(fn.split("/")[-1])
    missing = sorted(r for r in refs if not (ASSETS / r).exists())
    if missing:
        fail(f"{len(missing)} referenced mesh(es) missing from assets/: {', '.join(missing)}")
        problems += 1
    else:
        ok(f"all {len(refs)} referenced meshes present in assets/")

    present = {p.name for p in ASSETS.glob("*.stl")}
    extra = sorted(present - refs)
    if extra:
        print(f"note  {len(extra)} unreferenced stl(s) in assets/: {', '.join(extra)}")

    # --- 2. mesh units agree with the URDF (which declares no scale) ---
    scaled = [m for m in root.iter("mesh") if m.get("scale")]
    urdf_scale = scaled[0].get("scale") if scaled else None
    if urdf_scale:
        print(f"note  URDF declares mesh scale={urdf_scale}")

    biggest = 0.0
    biggest_name = ""
    for name in sorted(refs):
        p = ASSETS / name
        if not p.exists():
            continue
        _, lo, hi = stl_bbox(p)
        span = max(hi[i] - lo[i] for i in range(3))
        if span > biggest:
            biggest, biggest_name = span, name
    if biggest > 5.0:
        fail(
            f"meshes look like millimetres (largest span {biggest:.1f} in {biggest_name}) "
            f"but URDF origins are metres and no mesh scale is declared. "
            f"Copy the STLs from mini_bdx/robots/open_duck_mini_v2/, not from print/."
        )
        problems += 1
    else:
        ok(f"mesh units consistent with metres (largest span {biggest:.4f} m in {biggest_name})")

    # --- 3. the tree assembles into a duck of the right size ---
    child_joints: dict[str, list] = {}
    children = set()
    for j in joints:
        # An ElementTree node with no children is falsy, so these must be
        # compared against None explicitly rather than with `or`.
        parent_el = j.find("parent")
        child_el = j.find("child")
        parent = parent_el.get("link") if parent_el is not None else None
        child = child_el.get("link") if child_el is not None else None
        if parent and child:
            child_joints.setdefault(parent, []).append((child, j))
            children.add(child)
    roots = [n for n in links if n not in children]
    if len(roots) != 1:
        fail(f"expected exactly one root link, found {len(roots)}: {roots}")
        problems += 1
    base = roots[0] if roots else next(iter(links))
    print(f"\nroot link: {base}")

    # Forward kinematics at the zero pose.
    world: dict[str, list[list[float]]] = {base: mat_identity()}
    stack = [base]
    visited = set()
    while stack:
        link = stack.pop()
        if link in visited:
            continue
        visited.add(link)
        for child, joint in child_joints.get(link, []):
            world[child] = mat_mul(world[link], parse_origin(joint))
            stack.append(child)

    unreached = sorted(set(links) - set(world))
    if unreached:
        fail(f"{len(unreached)} link(s) unreachable from root (broken tree): {', '.join(unreached[:8])}")
        problems += 1
    else:
        ok(f"all {len(links)} links reachable from root — tree is connected")

    lo_all = [float("inf")] * 3
    hi_all = [float("-inf")] * 3
    bbox_cache: dict[str, tuple] = {}
    placed = 0
    for name, link in links.items():
        link_tf = world.get(name)
        if link_tf is None:
            continue
        for visual in link.findall("visual"):
            mesh = visual.find("geometry/mesh")
            if mesh is None:
                continue
            fn = (mesh.get("filename") or "").split("/")[-1]
            path = ASSETS / fn
            if not path.exists():
                continue
            if fn not in bbox_cache:
                bbox_cache[fn] = stl_bbox(path)
            _, lo, hi = bbox_cache[fn]
            tf = mat_mul(link_tf, parse_origin(visual))
            for cx in (lo[0], hi[0]):
                for cy in (lo[1], hi[1]):
                    for cz in (lo[2], hi[2]):
                        wx, wy, wz = transform_point(tf, (cx, cy, cz))
                        for j, c in enumerate((wx, wy, wz)):
                            lo_all[j] = min(lo_all[j], c)
                            hi_all[j] = max(hi_all[j], c)
            placed += 1

    if not placed:
        fail("no visual meshes could be placed")
        return 1

    size = [hi_all[i] - lo_all[i] for i in range(3)]
    print(f"\nassembled {placed} visual meshes at the zero pose")
    print(f"  bounding box  x={size[0]:.3f} m  y={size[1]:.3f} m  z={size[2]:.3f} m (Z is up)")
    print(f"  z range       {lo_all[2]:.3f} .. {hi_all[2]:.3f} m")

    height = size[2]
    width = max(size[0], size[1])
    if not (EXPECTED_HEIGHT_M[0] <= height <= EXPECTED_HEIGHT_M[1]):
        fail(f"height {height:.3f} m outside expected {EXPECTED_HEIGHT_M} for Open Duck Mini v2")
        problems += 1
    else:
        ok(f"height {height:.3f} m matches a ~42 cm duck")
    if not (EXPECTED_WIDTH_M[0] <= width <= EXPECTED_WIDTH_M[1]):
        fail(f"width {width:.3f} m outside expected {EXPECTED_WIDTH_M}")
        problems += 1
    else:
        ok(f"width {width:.3f} m is plausible")

    # A collapsed assembly (meshes far larger than their joint offsets) shows up
    # as a body many times bigger than the span between joint origins.
    joint_lo = [float("inf")] * 3
    joint_hi = [float("-inf")] * 3
    for tf in world.values():
        for j in range(3):
            joint_lo[j] = min(joint_lo[j], tf[j][3])
            joint_hi[j] = max(joint_hi[j], tf[j][3])
    joint_span = max(joint_hi[i] - joint_lo[i] for i in range(3))
    ratio = max(size) / joint_span if joint_span else float("inf")
    print(f"  joint-origin span {joint_span:.3f} m; mesh/joint size ratio {ratio:.2f}")
    if ratio > 5.0:
        fail(f"meshes dwarf the joint layout (ratio {ratio:.1f}) — parts will overlap instead of forming a duck")
        problems += 1
    else:
        ok(f"mesh extent is consistent with the joint layout (ratio {ratio:.2f})")

    print()
    if problems:
        print(f"RESULT: {problems} problem(s) found")
        return 1
    print("RESULT: robot description looks good")
    return 0


if __name__ == "__main__":
    sys.exit(main())
