"""
Tutorial Case Initializer Tool

This tool finds the most relevant tutorial case based on user requirements
and initializes the target case path with files from the selected tutorial.
"""

import os
import shutil
import json
import re
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from principia_core.metrics.tracker import MetricsTracker


class TutorialInitializer:
    """
    Tool for initializing case directories based on tutorial cases.

    This tool:
    1. Scans tutorial directories to find complete OpenFOAM cases
    2. Uses LLM to find the most relevant tutorial based on user requirements
    3. Copies the selected tutorial files to initialize the target case
    """

    def __init__(self, llm=None):
        self.llm = llm
        self.tutorial_cases_cache = {}

    def find_complete_cases(self, tutorial_path: str) -> List[Dict[str, Any]]:
        """
        遍历教程路径，找到所有完整的OpenFOAM案例。
        完整案例的条件：包含 Allrun 和 Allclean 文件。

        Args:
            tutorial_path: 教程根目录路径

        Returns:
            List of dictionaries containing case information:
            - path: absolute path to the case
            - relative_path: relative path from tutorial_path
            - readme_content: content of README file if exists
            - description: extracted description from case structure
        """
        cache_key = os.path.abspath(tutorial_path)
        if cache_key in self.tutorial_cases_cache:
            print(f"Using cached tutorial case scan: {tutorial_path}")
            return self.tutorial_cases_cache[cache_key]

        if not os.path.exists(tutorial_path):
            print(f"Tutorial path does not exist: {tutorial_path}")
            return []

        complete_cases = []

        def scan_directory(current_path: str, relative_path: str = ""):
            """递归扫描目录寻找完整案例"""
            try:
                for item in os.listdir(current_path):
                    item_path = os.path.join(current_path, item)
                    item_relative = os.path.join(relative_path, item) if relative_path else item

                    if os.path.isdir(item_path):
                        # 检查是否为完整案例
                        allrun_path = os.path.join(item_path, "Allrun")
                        allclean_path = os.path.join(item_path, "Allclean")

                        if os.path.exists(allrun_path) and os.path.exists(allclean_path):
                            # 这是一个完整的案例
                            case_info = {
                                "path": item_path,
                                "relative_path": item_relative,
                                "readme_content": self._read_readme(item_path),
                                "description": self._extract_case_description(item_path)
                            }
                            complete_cases.append(case_info)
                            print(f"Found complete case: {item_relative}")
                        else:
                            # 继续递归搜索子目录
                            scan_directory(item_path, item_relative)
            except PermissionError:
                print(f"Permission denied accessing: {current_path}")
            except Exception as e:
                print(f"Error scanning {current_path}: {e}")

        print(f"Scanning tutorial directory: {tutorial_path}")
        scan_directory(tutorial_path)

        print(f"Found {len(complete_cases)} complete cases")
        self.tutorial_cases_cache[cache_key] = complete_cases
        return complete_cases

    def _read_readme(self, case_path: str) -> Optional[str]:
        """读取案例目录中的README文件"""
        readme_files = ["README", "README.txt", "README.md", "readme", "Readme.txt"]

        for readme_file in readme_files:
            readme_path = os.path.join(case_path, readme_file)
            if os.path.exists(readme_path):
                try:
                    with open(readme_path, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception as e:
                    print(f"Error reading {readme_path}: {e}")
        return None

    def _extract_case_description(self, case_path: str) -> str:
        """从案例结构中提取描述信息"""
        description_parts = []

        # 从路径名推断
        case_name = os.path.basename(case_path)
        description_parts.append(f"Case: {case_name}")

        # 检查求解器类型
        control_dict_path = os.path.join(case_path, "system", "controlDict")
        if os.path.exists(control_dict_path):
            try:
                with open(control_dict_path, 'r') as f:
                    content = f.read()
                    # 简单的求解器提取
                    if "application" in content:
                        lines = content.split('\n')
                        for line in lines:
                            if line.strip().startswith("application"):
                                solver = line.split()[-1].rstrip(';')
                                description_parts.append(f"Solver: {solver}")
                                break
            except Exception:
                pass

        # 检查物理模型
        physics_info = []
        constant_path = os.path.join(case_path, "constant")

        # 检查湍流模型
        turbulence_props = os.path.join(constant_path, "turbulenceProperties")
        if os.path.exists(turbulence_props):
            physics_info.append("turbulence")

        # 检查传输属性
        transport_props = os.path.join(constant_path, "transportProperties")
        if os.path.exists(transport_props):
            physics_info.append("transport")

        # 检查热物理属性
        thermophys_props = os.path.join(constant_path, "thermophysicalProperties")
        if os.path.exists(thermophys_props):
            physics_info.append("thermophysics")

        # 检查相属性
        phase_props = os.path.join(constant_path, "phaseProperties")
        if os.path.exists(phase_props):
            physics_info.append("multiphase")

        if physics_info:
            description_parts.append(f"Physics: {', '.join(physics_info)}")

        # 检查初始场文件
        zero_path = os.path.join(case_path, "0")
        if os.path.exists(zero_path):
            fields = []
            for item in os.listdir(zero_path):
                if os.path.isfile(os.path.join(zero_path, item)):
                    fields.append(item)
            if fields:
                description_parts.append(f"Fields: {', '.join(sorted(fields))}")

        return " | ".join(description_parts)

    def find_relevant_tutorial_cases(self, user_request: str, tutorial_cases: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        """
        从知识库的教程案例中找到最相关的案例，使用TutorialInitializer的LLM方法。

        Args:
            user_request: 用户需求描述
            tutorial_cases: 从knowledge manager获取的教程案例列表
            top_k: 返回的相关案例数量

        Returns:
            List of the most relevant case information dictionaries
        """
        if not tutorial_cases:
            return []

        if not self.llm:
            print("Warning: No LLM available. Falling back to deterministic tutorial matching.")
            return self._deterministic_case_matches(user_request, tutorial_cases, top_k)

        # Use the find_multiple_relevant_cases method
        relevant_cases = self.find_multiple_relevant_cases(user_request, tutorial_cases, top_k)

        return relevant_cases

    def _case_search_text(self, case: Dict[str, Any]) -> str:
        """Builds a compact text blob for deterministic tutorial matching."""
        parts = [
            str(case.get("relative_path") or ""),
            str(case.get("description") or ""),
            str(case.get("readme_content") or "")[:4000],
        ]
        return "\n".join(parts).lower()

    def _rank_cases_deterministically(
        self,
        user_request: str,
        tutorial_cases: List[Dict[str, Any]],
    ) -> List[Tuple[int, Dict[str, Any]]]:
        """Ranks tutorial cases without selecting an unrelated first-case fallback."""
        request = (user_request or "").lower()
        if not request:
            return []

        request_aliases: List[Tuple[Tuple[str, ...], Tuple[str, ...], Tuple[str, ...], int]] = [
            (
                (
                    "axisymmetriccharge",
                    "axisymmetric charge",
                    "axisymmetric",
                    "surface burst",
                    "ground burst",
                    "scaled distance",
                    "scaled-distance",
                    "hopkinson",
                    "触地",
                    "地表",
                    "比例距离",
                ),
                ("axisymmetriccharge", "axisymmetric", "charge"),
                ("solids4foam", "solid", "flap"),
                70,
            ),
            (
                ("building3d", "building", "facade", "wall pressure", "建筑", "外立面", "迎爆面"),
                ("building3d", "building3dworkshop", "building"),
                ("solids4foam", "flap"),
                70,
            ),
            (
                (
                    "internaldetonation",
                    "internal detonation",
                    "internal blast",
                    "confined",
                    "vented",
                    "burstingwindow",
                    "bursting window",
                    "内部",
                    "室内",
                    "受限",
                    "通风",
                    "泄爆",
                    "出口",
                    "管道",
                ),
                ("internaldetonation", "burstingwindow", "internal"),
                ("solids4foam", "flap"),
                80,
            ),
            (
                ("shock tube", "shocktube", "sod", "激波管"),
                ("shocktube", "shock_tube", "shock"),
                ("solids4foam", "flap"),
                70,
            ),
            (
                ("detonation", "charge", "爆轰", "炸药", "爆炸"),
                ("detonation", "charge", "blast"),
                ("solids4foam",),
                25,
            ),
        ]

        request_tokens = {
            token
            for token in re.findall(r"[a-z0-9_]{3,}|[\u4e00-\u9fff]{2,}", request)
            if token not in {"please", "with", "case", "test", "smoke", "short", "very", "不要", "一个"}
        }

        ranked: List[Tuple[int, Dict[str, Any]]] = []
        for case in tutorial_cases:
            text = self._case_search_text(case)
            path = str(case.get("relative_path") or "").lower()
            score = 0

            for request_terms, desired_terms, negative_terms, weight in request_aliases:
                if not any(term in request for term in request_terms):
                    continue
                if any(term in path for term in desired_terms):
                    score += weight
                elif any(term in text for term in desired_terms):
                    score += max(10, weight // 3)
                if any(term in path for term in negative_terms):
                    score -= max(10, weight // 2)

            for token in request_tokens:
                if token in path:
                    score += 4
                elif token in text:
                    score += 1

            surface_scaled_distance_request = any(
                term in request
                for term in (
                    "surface burst",
                    "ground burst",
                    "scaled distance",
                    "scaled-distance",
                    "hopkinson",
                    "触地",
                    "地表",
                    "比例距离",
                )
            )
            if surface_scaled_distance_request:
                if "axisymmetriccharge" in path:
                    score += 180
                if "twochargedetonation" in path or "twocharge" in path:
                    score -= 80

            obstacle_reflection_request = any(
                term in request
                for term in (
                    "hemicylinder",
                    "semi-cylinder",
                    "semi cylinder",
                    "cylinder obstacle",
                    "obstacle reflection",
                    "movingcone",
                    "半圆柱",
                    "圆柱",
                    "障碍物",
                    "反射",
                    "绕流",
                )
            )
            mapped_layout_request = any(
                term in request
                for term in (
                    "sector",
                    "wedge",
                    "mapped layout",
                    "building corner",
                    "corner diffraction",
                    "建筑转角",
                    "转角",
                    "挡墙",
                )
            )
            if obstacle_reflection_request:
                if "building3dworkshop" in path:
                    score += 180
                elif path.endswith("blastfoam/building3d"):
                    score += 90
                elif "movingcone" in path:
                    score += 45
                if "mappedbuilding3d" in path and not mapped_layout_request:
                    score -= 120

            if "blast" in request and "blast" in path:
                score += 8
            if any(term in request for term in ("爆炸", "爆轰", "blast", "charge")) and "solids4foam" in path:
                score -= 15
            if any(
                term in request
                for term in (
                    "blast",
                    "爆炸",
                    "爆轰",
                    "建筑",
                    "内部",
                    "室内",
                    "受限",
                    "通风",
                    "泄爆",
                    "pressure",
                    "overpressure",
                )
            ):
                if path.startswith("blastfoam/"):
                    score += 20
                if path.startswith("setrefinedfields/"):
                    score -= 35

            if score > 0:
                ranked.append((score, case))

        ranked.sort(key=lambda item: (item[0], item[1].get("relative_path", "")), reverse=True)
        return ranked

    def _deterministic_case_matches(
        self,
        user_request: str,
        tutorial_cases: List[Dict[str, Any]],
        top_k: int,
    ) -> List[Dict[str, Any]]:
        ranked = self._rank_cases_deterministically(user_request, tutorial_cases)
        if not ranked:
            print("Deterministic tutorial matching found no supported candidates.")
            return []

        selected = [case for _score, case in ranked[:top_k]]
        print("Deterministic tutorial matching selected:")
        for score, case in ranked[:top_k]:
            print(f"  score={score}: {case.get('relative_path')}")
        return selected

    def find_multiple_relevant_cases(self, user_request: str, tutorial_cases: List[Dict[str, Any]], top_k: int = 3) -> List[Dict[str, Any]]:
        """
        使用LLM找到多个最相关的教程案例

        Args:
            user_request: 用户需求描述
            tutorial_cases: 可用的教程案例列表
            top_k: 返回的相关案例数量

        Returns:
            List of the most relevant case information dictionaries
        """
        if not tutorial_cases:
            print("No tutorial cases available for comparison")
            return []

        if not self.llm:
            print("No LLM available, using deterministic tutorial matching")
            return self._deterministic_case_matches(user_request, tutorial_cases, top_k)

        # 准备案例信息用于LLM分析
        cases_info = []
        for i, case in enumerate(tutorial_cases):
            case_summary = {
                "index": i,
                "path": case["relative_path"],
                "description": case["description"],
                "readme": case["readme_content"][:500] if case["readme_content"] else "No README available"
            }
            cases_info.append(case_summary)

        # 构建提示词
        system_prompt = f"""You are an OpenFOAM expert helping to select the {top_k} most relevant tutorial cases for a user's simulation requirements.

Analyze the user request and compare it with the available tutorial cases. Consider:
- Physics phenomena (flow type, turbulence, heat transfer, multiphase, etc.)
- Solver type requirements
- Geometry complexity
- Boundary condition types
- Material properties

Return the indices (0-based) of the {top_k} most relevant cases in order of relevance.

Response format: Only return a JSON array of integers, e.g. [3, 7, 1]"""

        user_prompt = f"""User Request: {user_request}

Available Tutorial Cases:
{json.dumps(cases_info, indent=2)}

Which {top_k} case indices are most relevant for this user request? Return as a JSON array."""

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            response = self.llm.invoke(messages)

            # Track tokens
            tracker = MetricsTracker()
            usage = getattr(response, 'usage_metadata', None) or {}
            agent_name = tracker.current_agent or "TutorialInitializer"
            tracker.record_llm_call(
                agent_name=agent_name,
                input_tokens=usage.get('input_tokens', 0),
                output_tokens=usage.get('output_tokens', 0),
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else 'unknown'
            )

            # 解析响应获取索引列表
            try:
                import re
                # Try to extract JSON array from response
                json_match = re.search(r'\[.*\]', response.content)
                if json_match:
                    indices_str = json_match.group(0)
                    indices = json.loads(indices_str)
                else:
                    # If not wrapped in proper JSON format, try to parse list-like string
                    indices_str = response.content.strip()
                    indices_str = indices_str.replace('[', '').replace(']', '').replace(' ', '')
                    indices = [int(idx) for idx in indices_str.split(',') if idx]

                # Filter valid indices
                valid_indices = [idx for idx in indices if 0 <= idx < len(tutorial_cases)]

                # Ensure we don't exceed the requested number of cases
                valid_indices = valid_indices[:top_k]

                if not valid_indices:
                    print("No valid indices returned, using deterministic tutorial matching")
                    return self._deterministic_case_matches(user_request, tutorial_cases, top_k)

                # Get the selected cases
                selected_cases = [tutorial_cases[idx] for idx in valid_indices]
                print(f"LLM selected {len(selected_cases)} cases")
                for idx, case in zip(valid_indices, selected_cases):
                    print(f"  Case index {idx}: {case['relative_path']}")

                ranked = self._rank_cases_deterministically(user_request, tutorial_cases)
                if ranked:
                    score_by_path = {
                        case.get("relative_path"): score
                        for score, case in ranked
                    }
                    top_score, top_case = ranked[0]
                    selected_score = score_by_path.get(selected_cases[0].get("relative_path"), 0)
                    if top_score >= 30 and selected_score <= 0:
                        print(
                            "LLM selected a tutorial with no deterministic support; "
                            f"using deterministic match {top_case.get('relative_path')} instead."
                        )
                        return [case for _score, case in ranked[:top_k]]

                return selected_cases

            except Exception as e:
                print(f"Could not parse LLM response as list of indices: {e}. Response: {response.content}")
                return self._deterministic_case_matches(user_request, tutorial_cases, top_k)

        except Exception as e:
            print(f"Error in LLM case selection: {e}")
            return self._deterministic_case_matches(user_request, tutorial_cases, top_k)

    def copy_case_files(self, source_case_path: str, target_case_path: str) -> bool:
        """
        将选定的教程案例文件复制到目标案例路径

        Args:
            source_case_path: 源教程案例路径
            target_case_path: 目标案例路径

        Returns:
            True if successful, False otherwise
        """
        try:
            # 确保目标目录存在
            os.makedirs(target_case_path, exist_ok=True)

            # 复制源案例目录下的所有文件和文件夹
            copied_items = []

            for item in os.listdir(source_case_path):
                source_item = os.path.join(source_case_path, item)
                target_item = os.path.join(target_case_path, item)

                if os.path.isdir(source_item):
                    # 复制目录
                    if os.path.exists(target_item):
                        shutil.rmtree(target_item)
                    shutil.copytree(source_item, target_item)
                    copied_items.append(f"directory: {item}")
                    print(f"Copied directory: {item}")
                elif os.path.isfile(source_item):
                    # 复制文件
                    shutil.copy2(source_item, target_item)
                    copied_items.append(f"file: {item}")
                    print(f"Copied file: {item}")

            print(f"Successfully initialized case from tutorial: {source_case_path}")
            print(f"Copied items: {copied_items}")
            return True

        except Exception as e:
            print(f"Error copying case files: {e}")
            return False

    def initialize_case_from_tutorial_with_selected_case(self, selected_case: Dict[str, Any], target_case_path: str) -> Dict[str, Any]:
        """
        使用已选择的教程案例初始化目标案例目录

        Args:
            selected_case: 已选择的教程案例信息（来自find_relevant_tutorial_cases）
            target_case_path: 目标案例路径

        Returns:
            Dictionary with initialization results:
            - success: bool
            - selected_case: dict or None
            - message: str
        """
        print(f"Initializing case from selected tutorial...")
        print(f"Selected case: {selected_case.get('path', 'Unknown')}")
        print(f"Target case path: {target_case_path}")

        # Get the tutorial case path from the selected case
        case_path = selected_case.get('path', '')
        if not case_path:
            return {
                "success": False,
                "selected_case": selected_case,
                "message": "Selected case does not have a valid case_path"
            }

        # Build the full tutorial path
        BLASTFOAM_TUTORIALS = os.getenv("BLASTFOAM_TUTORIALS")
        if not BLASTFOAM_TUTORIALS:
            return {
                "success": False,
                "selected_case": selected_case,
                "message": "BLASTFOAM_TUTORIALS environment variable not set"
            }

        tutorial_path = os.path.join(BLASTFOAM_TUTORIALS, case_path)

        if not os.path.exists(tutorial_path):
            return {
                "success": False,
                "selected_case": selected_case,
                "message": f"Tutorial case path does not exist: {tutorial_path}"
            }

        # Copy the tutorial case files to target path
        success = self.copy_case_files(tutorial_path, target_case_path)

        return {
            "success": success,
            "selected_case": selected_case,
            "message": f"Successfully initialized from {case_path}" if success
                      else f"Failed to copy files from {case_path}"
        }


def register_tutorial_tools(graph=None) -> Dict[str, Any]:
    """
    Register tutorial initialization tools for use with the tool registry.

    Args:
        graph: Optional legacy compatibility argument; ignored.

    Returns:
        Dictionary of tutorial tools
    """
    # This will be populated when the tool is actually used with an LLM instance
    return {
        "initialize_case_from_tutorial": None  # Placeholder - will be set by agent
    }
