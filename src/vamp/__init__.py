__all__ = [
    "robots",
    "png_to_heightfield",
    "configure_robot_and_planner_with_kwargs",
    "problem_dict_to_vamp",
    "results_to_dict",
    "Environment",
    "Attachment",
    "Sphere",
    "Cuboid",
    "Cylinder",
    "RRTCSettings",
    "PRMSettings",
    "PRMNeighborParams",
    "FCITSettings",
    "FCITNeighborParams",
    "AORRTCSettings",
    "SimplifySettings",
    "SimplifyRoutine",
    "filter_pointcloud",
    ]

from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union, List
import importlib

from numpy import float32
from numpy.typing import NDArray

from .constants import *
from . import _core
from ._core import Sphere as Sphere
from ._core import Cuboid as Cuboid
from ._core import Cylinder as Cylinder
from ._core import Attachment as Attachment
from ._core import Environment as Environment
from ._core import PRMNeighborParams as PRMNeighborParams
from ._core import PRMSettings as PRMSettings
from ._core import RRTCSettings as RRTCSettings
from ._core import FCITNeighborParams as FCITNeighborParams
from ._core import FCITSettings as FCITSettings
from ._core import AORRTCSettings as AORRTCSettings
from ._core import SimplifyRoutine as SimplifyRoutine
from ._core import SimplifySettings as SimplifySettings
from ._core import filter_pointcloud as filter_pointcloud

robots = _core.robots()

for robot in robots:
    globals()[robot] = getattr(_core, robot)
    __all__.append(robot)


def png_to_heightfield(
    filename: Path,
    center: Tuple[float, float, float],
    scaling: Tuple[float, float, float],
    ):
    import numpy as np
    from PIL import Image

    image = Image.open(filename).convert("L")
    array = np.asarray(image) * 1 / 255.0
    array = np.flip(array, axis = 0)

    return _core.make_heightfield(center, scaling, array.shape, list(array.flatten()))


def configure_robot_and_planner_with_kwargs(robot_name: str, planner_name: str, **kwargs):
    robot_module = getattr(_core, robot_name)
    try:
        planner_func = getattr(robot_module, planner_name)
    except AttributeError:
        raise ValueError(f"Robot {robot_name} does not support planner {planner_name}!")

    if planner_name == "rrtc":
        plan_settings = RRTCSettings()
        plan_settings.range = ROBOT_RRT_RANGES[robot_name]
    elif planner_name == "prm":
        plan_settings = PRMSettings(PRMNeighborParams(robot_module.dimension(), robot_module.space_measure()))
    elif planner_name == "fcit":
        plan_settings = FCITSettings(
            FCITNeighborParams(robot_module.dimension(), robot_module.space_measure())
            )
    elif planner_name == "aorrtc":
        plan_settings = AORRTCSettings()
        plan_settings.rrtc.range = ROBOT_RRT_RANGES[robot_name]
    else:
        raise NotImplementedError(f"Automatic setup for planner {planner_name} is not implemented yet!")

    plan_settings.max_iterations = DEFAULT_ITERATIONS
    plan_settings.max_samples = DEFAULT_ITERATIONS

    for k, v in kwargs.items():
        if hasattr(plan_settings, k):
            print(f"Setting planner - {k}: {v}")
            setattr(plan_settings, k, v)

    # AORRTC Internal
    for k, v in kwargs.items():
        if "rrtc_" in k:
            sk = k.replace("rrtc_", "")
            if hasattr(plan_settings.rrtc, sk):
                print(f"Setting planner - {sk}: {v}")
                setattr(plan_settings.rrtc, sk, v)

    simp_settings = SimplifySettings()

    for k, v in kwargs.items():
        if "simplification_" in k:
            sk = k.replace("simplification_", "")
            if hasattr(simp_settings, sk):
                print(f"Setting simplification - {sk}: {v}")
                if sk == "operations":
                    v = [getattr(SimplifyRoutine, r) for r in v]

                setattr(simp_settings, sk, v)

        subs = ["reduce", "shortcut", "bspline", "perturb"]
        for sub in subs:
            if sub not in k:
                continue

            sk = k.replace(f"{sub}_", "")
            sub_setting = getattr(simp_settings, sub)
            if hasattr(sub_setting, sk):
                print(f"Setting simplification - {sub} - {sk}: {v}")
                setattr(sub_setting, sk, v)

    if planner_name == "aorrtc":
        plan_settings.simplify = simp_settings

    return robot_module, planner_func, plan_settings, simp_settings


def problem_dict_to_vamp(
        problem: Dict[str, List[Dict[str, Union[float, NDArray[float32]]]]],
        ignore_names: List[str] = []
    ) -> Environment:
    env = Environment()
    for obj in problem["sphere"]:
        if obj['name'] not in ignore_names:
            sphere = Sphere(obj["position"], obj["radius"])
            sphere.name = obj['name']
            env.add_sphere(sphere)

    # HACK: The "box" problem in MBM requires a top down grasp of the cylinder, so to avoid capsule
    # overapproximation we instead overapproximate with a box
    if problem["problem"] == "box":
        for obj in problem["cylinder"]:
            if obj["name"] in ignore_names:
                continue

            cuboid = Cuboid(
                obj["position"],
                obj["orientation_euler_xyz"],
                [obj["radius"], obj["radius"], obj["length"] / 2],
                )
            cuboid.name = obj["name"]
            env.add_cuboid(cuboid)
    else:
        for obj in problem["cylinder"]:
            if obj["name"] in ignore_names:
                continue

            cylinder = Cylinder(
                obj["position"],
                obj["orientation_euler_xyz"],
                obj["radius"],
                obj["length"],
                )

            cylinder.name = obj['name']
            env.add_capsule(cylinder)

    for obj in problem["box"]:
        if obj["name"] not in ignore_names:
            cuboid = Cuboid(obj["position"], obj["orientation_euler_xyz"], obj["half_extents"])
            cuboid.name = obj['name']
            env.add_cuboid(cuboid)

    return env


def results_to_dict(
    planning_result,
    simplification_result = None,
    ) -> Dict[str, Any]:

    try:
        import pandas as pd
    except ImportError:
        raise RuntimeError("pandas is not installed!")

    data = {
        "planning_time": pd.Timedelta(nanoseconds = planning_result.nanoseconds),
        "planning_iterations": planning_result.iterations,
        "solved": bool(planning_result.path),
        "planning_graph_size": sum(planning_result.size),
        "initial_path_vertices": len(planning_result.path),
        "initial_path_cost": planning_result.path.cost(),
        }

    if simplification_result:
        simp_data = {
            "simplification_time": pd.Timedelta(nanoseconds = simplification_result.nanoseconds),
            "simplified_path_vertices": len(simplification_result.path),
            "simplified_path_cost": simplification_result.path.cost(),
            }
    else:
        simp_data = {
            "simplification_time": pd.Timedelta(nanoseconds = 0),
            "simplified_path_vertices": data["initial_path_vertices"],
            "simplified_path_cost": data["initial_path_cost"],
            }

    data.update(simp_data)
    data.update({
        "total_time": data["planning_time"] + data["simplification_time"],
        })

    return data


def __dir__() -> List[str]:
    symbols = set(globals().keys())
    symbols -= {"_core"}
    return list(symbols)
