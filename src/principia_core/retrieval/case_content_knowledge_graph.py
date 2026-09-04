
import json
import os
import re
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Optional
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    def load_dotenv(*_args, **_kwargs):  # type: ignore[no-redef]
        return False
from langchain_openai import ChatOpenAI
from principia_core.config.llm_profiles import chat_openai_kwargs
from principia_core.config.retrieval_llm import resolve_retrieval_llm_config
from principia_core.metrics.tracker import MetricsTracker

# Add project root to path for module imports
project_root = Path(__file__).resolve().parents[3]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


KG_RETRIEVAL_MAX_ITERATIONS_ENV = "KG_RETRIEVAL_MAX_ITERATIONS"
KG_RETRIEVAL_MAX_ITERATIONS_DEFAULT = 3


def _resolve_kg_max_iterations(max_iterations: Optional[int]) -> int:
    if max_iterations is not None:
        return max(1, int(max_iterations))

    raw_value = os.getenv(KG_RETRIEVAL_MAX_ITERATIONS_ENV)
    if not raw_value:
        return KG_RETRIEVAL_MAX_ITERATIONS_DEFAULT

    try:
        return max(1, int(raw_value))
    except ValueError:
        return KG_RETRIEVAL_MAX_ITERATIONS_DEFAULT

class CaseContentKnowledgeGraphRetriever:
    """
    A tool for retrieving information from the BlastFoam case content knowledge graph.
    This tool uses LLM-generated search strategies to find relevant tutorial cases, solvers, and concepts.
    """
    def __init__(self, llm_api_key=None, llm_base_url=None, llm_model=None):
        """
        Initialize the CaseContentKnowledgeGraphRetriever.

        Args:
            llm_api_key: Retrieval LLM API Key.
            llm_base_url: Retrieval LLM API base URL.
            llm_model: Retrieval LLM model name.
        """
        llm_config = resolve_retrieval_llm_config(
            api_key=llm_api_key,
            base_url=llm_base_url,
            model=llm_model,
        )

        self.llm = None
        if llm_config["api_key"]:
            self.llm = ChatOpenAI(
                **chat_openai_kwargs(
                    base_url=llm_config["base_url"],
                    model=llm_config["model"],
                    api_key=llm_config["api_key"],
                    provider=llm_config["provider"],
                    temperature=0.1,
                )
            )

        # Get BLASTFOAM_TUTORIALS path for file reading
        self.foam_tutorials_path = os.getenv("BLASTFOAM_TUTORIALS")
        if not self.foam_tutorials_path:
            print("Warning: BLASTFOAM_TUTORIALS environment variable not set. File content retrieval will be limited.")

        # Load knowledge base
        self._load_knowledge_base()

    def _load_knowledge_base(self):
        """Load the case content knowledge graphs from multiple files."""
        base_dir = Path(__file__).resolve().parents[3]
        knowledge_dir = base_dir / "data/knowledge_graph/case_content_knowledge_graph"

        self.nodes = []
        self.relationships = []
        self.id_to_node = {}
        self.case_path_to_node_id = {}
        self.case_to_file_ids = defaultdict(list)
        self.file_to_variable_ids = defaultdict(list)
        self.file_id_to_case_path = {}

        try:
            json_files = [f for f in os.listdir(knowledge_dir) if f.endswith('.json')]

            for file_name in json_files:
                knowledge_path = knowledge_dir / file_name
                with open(knowledge_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)

                    # 使用文件名（去掉 .json 后缀）作为唯一前缀
                    unique_prefix = file_name.replace('.json', '')

                    # 提取 case_id（第一个 Case 节点的 ID）用于存储
                    case_id = None
                    nodes = data.get("nodes", [])
                    for node in nodes:
                        if node.get('label') == 'Case':
                            case_id = node.get('id')
                            break

                    if not case_id:
                        print(f"Warning: No Case node found in {file_name}, skipping...")
                        continue

                    # 创建 ID 映射表：旧 ID -> 新 ID
                    id_mapping = {}

                    # 处理节点：所有节点都添加唯一前缀以彻底避免冲突
                    for node in nodes:
                        old_id = node['id']

                        # 为所有节点添加文件名前缀
                        new_id = f"{unique_prefix}::{old_id}"
                        node['id'] = new_id
                        id_mapping[old_id] = new_id

                        # 添加元数据属性
                        if 'properties' not in node:
                            node['properties'] = {}
                        node['properties']['source_file'] = file_name
                        node['properties']['case_id'] = case_id
                        node['properties']['original_id'] = old_id  # 保存原始 ID

                    self.nodes.extend(nodes)

                    # 处理关系：更新 source 和 target 引用
                    relationships = data.get("relationships", [])
                    for rel in relationships:
                        old_source = rel.get('source')
                        old_target = rel.get('target')

                        # 更新为新的 ID
                        if old_source in id_mapping:
                            rel['source'] = id_mapping[old_source]
                        else:
                            print(f"Warning: Relationship source '{old_source}' not found in mapping for {file_name}")

                        if old_target in id_mapping:
                            rel['target'] = id_mapping[old_target]
                        else:
                            print(f"Warning: Relationship target '{old_target}' not found in mapping for {file_name}")

                    self.relationships.extend(relationships)

            self.id_to_node = {node['id']: node for node in self.nodes}
            self.case_path_to_node_id = {
                str(node.get("properties", {}).get("path")): node["id"]
                for node in self.nodes
                if node.get("label") == "Case" and node.get("properties", {}).get("path")
            }

            for rel in self.relationships:
                rel_type = rel.get("type")
                source_id = rel.get("source")
                target_id = rel.get("target")
                source_node = self.id_to_node.get(source_id)
                target_node = self.id_to_node.get(target_id)

                if not source_node or not target_node:
                    continue

                if rel_type == "CONTAINS":
                    if source_node.get("label") == "Case" and target_node.get("label") == "File":
                        case_path = source_node.get("properties", {}).get("path")
                        if case_path:
                            self.case_to_file_ids[str(case_path)].append(target_id)
                            self.file_id_to_case_path[target_id] = str(case_path)
                elif rel_type == "DEFINES":
                    if source_node.get("label") == "File" and target_node.get("label") == "Variable":
                        self.file_to_variable_ids[source_id].append(target_id)

            # 检查是否有 ID 冲突
            if len(self.id_to_node) < len(self.nodes):
                print(f"Warning: ID conflicts detected! {len(self.nodes)} nodes but only {len(self.id_to_node)} unique IDs.")
            else:
                print(f"✓ All node IDs are unique!")

            print(f"Loaded {len(self.nodes)} nodes and {len(self.relationships)} relationships from {len(json_files)} files in the case content knowledge graph.")
        except Exception as e:
            print(f"Error loading case content knowledge graph: {e}")
            import traceback
            traceback.print_exc()
            self.nodes = []
            self.relationships = []
            self.id_to_node = {}
            self.case_path_to_node_id = {}
            self.case_to_file_ids = defaultdict(list)
            self.file_to_variable_ids = defaultdict(list)
            self.file_id_to_case_path = {}

    def _get_knowledge_graph_summary(self) -> str:
        """
        Generate a summary of the knowledge graph structure to help LLM understand it.

        Returns:
            A summary string describing the knowledge graph structure.
        """
        # Count node types
        node_types = defaultdict(int)
        for node in self.nodes:
            node_types[node.get('label', 'Unknown')] += 1

        # Get sample nodes for each type
        samples = defaultdict(list)
        for node in self.nodes[:50]:  # Sample first 50 nodes
            label = node.get('label', 'Unknown')
            if len(samples[label]) < 2:
                samples[label].append(node)

        summary = "## Case Content Knowledge Graph Structure\n\n"
        summary += "This knowledge graph contains information extracted from blastFoam tutorial cases.\n\n"
        summary += "### Node Types and Counts:\n"
        for label, count in sorted(node_types.items()):
            summary += f"- **{label}**: {count} nodes\n"

        summary += "\n### Node Structure Examples:\n"
        for label, nodes in samples.items():
            summary += f"\n**{label} nodes:**\n"
            for node in nodes:
                summary += f"- ID: {node.get('id')}, Properties: {list(node.get('properties', {}).keys())}\n"

        summary += "\n### Search Capabilities:\n"
        summary += "- You can search by node ID (exact match)\n"
        summary += "- You can search by node label (Case, File, Variable, etc.)\n"
        summary += "- You can search by property values (name, path, type, etc.)\n"
        summary += "- You can combine multiple criteria\n"

        return summary

    def _execute_search_strategy(self, strategy: dict) -> list:
        """
        Execute the search strategy on the local knowledge graph.

        Args:
            strategy: The search strategy dictionary generated by LLM.

        Returns:
            List of matching node IDs with their relevance scores.
        """
        search_criteria = strategy.get("search_criteria", {})
        node_labels = search_criteria.get("node_labels", [])
        property_filters = search_criteria.get("property_filters", {})

        # Fix: Handle case where property_filters is a list (LLM hallucination)
        if isinstance(property_filters, list):
            print(f"DEBUG: property_filters is a list, converting to dict: {property_filters}")
            new_filters = {}
            for item in property_filters:
                if isinstance(item, dict):
                    new_filters.update(item)
            property_filters = new_filters
        elif not isinstance(property_filters, dict):
            print(f"DEBUG: property_filters is not a dict or list: {type(property_filters)}")
            property_filters = {}

        keyword_search = search_criteria.get("keyword_search", [])

        # Dictionary to store node scores
        node_scores = defaultdict(float)

        for node in self.nodes:
            node_id = node.get('id')
            label = node.get('label', '')
            properties = node.get('properties', {})

            score = 0.0

            # Check node label match
            if node_labels and label in node_labels:
                score += 5.0

            # Check property filters
            for prop_name, prop_pattern in property_filters.items():
                if prop_name in properties:
                    prop_value = str(properties[prop_name]).lower()
                    pattern = str(prop_pattern).lower()

                    # Handle wildcard matching
                    if '*' in pattern:
                        pattern_regex = pattern.replace('*', '.*')
                        if re.search(pattern_regex, prop_value):
                            score += 3.0
                    elif pattern in prop_value:
                        score += 3.0

            # Check keyword search
            for keyword in keyword_search:
                keyword_lower = keyword.lower()
                keyword_lower = keyword_lower.replace('-', '')

                # Search in label
                if keyword_lower in label.lower():
                    score += 2.0

                # Search in all properties
                for prop_value in properties.values():
                    if isinstance(prop_value, str) and keyword_lower in prop_value.lower():
                        score += 1.0

            if score > 0:
                node_scores[node_id] = score

        # Return sorted list of (node_id, score) tuples
        sorted_results = sorted(node_scores.items(), key=lambda x: x[1], reverse=True)
        print(f"Search strategy found {len(sorted_results)} matching nodes")
        return sorted_results

    def _find_file_for_variable(self, variable_id: str) -> str:
        """
        Find the file that defines a given variable by traversing the knowledge graph relationships.

        Args:
            variable_id: The ID of the variable node.

        Returns:
            The file path that defines this variable, or None if not found.
        """
        # Look for relationships where this variable is the target and type is DEFINES
        for rel in self.relationships:
            if rel.get('target') == variable_id and rel.get('type') == 'DEFINES':
                file_id = rel.get('source')
                # Check if the source is a File node
                file_node = self.id_to_node.get(file_id)
                if file_node and file_node.get('label') == 'File':
                    return file_node.get('properties', {}).get('path')

        return None

    def _get_file_content(self, file_path: str, max_lines: int = 100) -> str:
        """
        Retrieve the actual content of a file from the BLASTFOAM_TUTORIALS directory.

        Args:
            file_path: The relative path of the file (e.g., "blastFoam/building3D/system/controlDict")
            max_lines: Maximum number of lines to read (default: 100)

        Returns:
            The file content as a string, or an error message if the file cannot be read.
        """
        if not self.foam_tutorials_path:
            return "File content unavailable: BLASTFOAM_TUTORIALS environment variable not set."

        tutorials_root = Path(self.foam_tutorials_path).expanduser().resolve()
        candidate = Path(file_path).expanduser()
        full_path = candidate.resolve() if candidate.is_absolute() else (tutorials_root / candidate).resolve()
        if full_path != tutorials_root and not full_path.is_relative_to(tutorials_root):
            return f"File access denied outside BLASTFOAM_TUTORIALS: {file_path}"

        if not full_path.exists():
            return f"File not found: {file_path}"

        try:
            with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()

                if len(lines) > max_lines:
                    content = ''.join(lines[:max_lines])
                    content += f"\n... (truncated, showing first {max_lines} lines of {len(lines)} total lines)"
                else:
                    content = ''.join(lines)

                return content
        except Exception as e:
            return f"Error reading file {file_path}: {str(e)}"

    def _get_case_info_for_nodes(self, node_ids: list) -> dict:
        """
        获取每个节点所属的 Case 信息。
        此方法从 _hierarchical_search 中分离出来，确保所有检索结果都包含 case 上下文信息。

        Relationship structure:
        - Case CONTAINS File
        - File DEFINES Variable

        Args:
            node_ids: 节点 ID 列表

        Returns:
            字典，key 为节点 ID，value 为对应的 Case 节点信息
        """
        node_to_case = {}

        for node_id in node_ids:
            node = self.id_to_node.get(node_id)
            if not node:
                continue

            case_info = None
            node_label = node.get('label', '')

            # 如果节点本身就是 Case
            if node_label == 'Case':
                case_info = node

            # 如果是 File 节点，查找包含它的 Case
            elif node_label == 'File':
                for rel in self.relationships:
                    # Case CONTAINS File
                    if (rel.get('type') == 'CONTAINS' and
                        rel.get('target') == node_id):
                        case_id = rel.get('source')
                        case_node = self.id_to_node.get(case_id)
                        if case_node and case_node.get('label') == 'Case':
                            case_info = case_node
                            break

            # 如果是 Variable 节点，通过 DEFINES 关系找到 File，再找 Case
            elif node_label == 'Variable':
                for rel in self.relationships:
                    # File DEFINES Variable
                    if (rel.get('type') == 'DEFINES' and
                        rel.get('target') == node_id):
                        file_id = rel.get('source')
                        # 查找 File 所属的 Case
                        for rel2 in self.relationships:
                            # Case CONTAINS File
                            if (rel2.get('type') == 'CONTAINS' and
                                rel2.get('target') == file_id):
                                case_id = rel2.get('source')
                                case_node = self.id_to_node.get(case_id)
                                if case_node and case_node.get('label') == 'Case':
                                    case_info = case_node
                                    break
                        if case_info:
                            break

            if case_info:
                node_to_case[node_id] = case_info

        return node_to_case

    def _normalize_file_reference(self, file_path: str, case_path: str) -> str:
        """
        Normalize a case-relative file path from a path that may already include
        the full case prefix.
        """
        normalized_path = str(file_path).replace("\\", "/").strip()
        normalized_case = str(case_path).replace("\\", "/").strip().rstrip("/")

        prefix = f"{normalized_case}/"
        if normalized_path.startswith(prefix):
            return normalized_path[len(prefix):]
        return normalized_path

    def _build_structured_results(
        self,
        node_ids: list,
        top_k: Optional[int] = None,
        score_by_node: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, object]]:
        """
        Convert selected node IDs into strict retrieval candidates.

        File nodes map directly to their file path.
        Variable nodes are resolved to the file that defines them.
        Case nodes are not emitted as strict file candidates.
        """
        if not node_ids:
            return []

        node_to_case = self._get_case_info_for_nodes(node_ids)
        score_by_node = score_by_node or {}
        structured_results: List[Dict[str, object]] = []
        seen = set()

        for rank, node_id in enumerate(node_ids, start=1):
            node = self.id_to_node.get(node_id)
            if not node:
                continue

            label = node.get("label", "")
            properties = node.get("properties", {})
            case_info = node_to_case.get(node_id)
            case_path = None
            if case_info:
                case_path = case_info.get("properties", {}).get("path")

            file_path = None
            if label == "File":
                file_path = properties.get("path")
            elif label == "Variable":
                file_path = self._find_file_for_variable(node_id)

            if not case_path or not file_path:
                continue

            normalized_file_path = self._normalize_file_reference(str(file_path), str(case_path))
            canonical_id = f"{case_path}::{normalized_file_path}"
            if canonical_id in seen:
                continue
            seen.add(canonical_id)

            structured_results.append(
                {
                    "case_path": str(case_path),
                    "file_path": normalized_file_path,
                    "canonical_id": canonical_id,
                    "path": f"{case_path}/{normalized_file_path}",
                    "source_node_id": node_id,
                    "source_node_type": label,
                    "source_node_name": properties.get("name"),
                    "rank": rank,
                    "score": score_by_node.get(node_id),
                }
            )

            if top_k is not None and len(structured_results) >= top_k:
                break

        return structured_results

    def _normalize_match_text(self, text: str) -> str:
        normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
        normalized = normalized.lower().replace("-", " ").replace("_", " ")
        normalized = re.sub(r"[^a-z0-9./]+", " ", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _query_mentions_any(self, normalized_query: str, phrases: List[str]) -> bool:
        return any(self._normalize_match_text(phrase) in normalized_query for phrase in phrases)

    def _infer_case_candidates(
        self,
        user_query: str,
        node_ids: list,
        score_by_node: Optional[Dict[str, float]] = None,
    ) -> List[tuple]:
        node_to_case = self._get_case_info_for_nodes(node_ids)
        score_by_node = score_by_node or {}
        case_scores = defaultdict(float)
        normalized_query = self._normalize_match_text(user_query)

        for case_path in self.case_path_to_node_id:
            hint_score = self._score_case_candidate(normalized_query, case_path)
            if hint_score > 0:
                case_scores[str(case_path)] += hint_score

        for rank, node_id in enumerate(node_ids, start=1):
            case_info = node_to_case.get(node_id)
            if not case_info:
                continue

            case_path = case_info.get("properties", {}).get("path")
            if not case_path:
                continue

            base_score = float(score_by_node.get(node_id) or 0.0)
            if base_score <= 0:
                base_score = max(0.0, 12.0 - rank)
            case_scores[str(case_path)] += base_score + (1.0 / rank)

        return sorted(case_scores.items(), key=lambda item: item[1], reverse=True)

    def _score_case_candidate(self, normalized_query: str, case_path: str) -> float:
        normalized_case = self._normalize_match_text(case_path)
        score = 0.0

        case_intent_rules = [
            (
                "blastXiFoam/deflagrationToDetonationTransition",
                [
                    "deflagration to detonation",
                    "ddt",
                    "laminar flame speed",
                    "equivalence ratio",
                    "fuel rich",
                    "spalart allmaras",
                    "arrhenius",
                ],
                140.0,
            ),
            (
                "blastFoam/freeField",
                ["free field", "free field explosion", "free-field"],
                140.0,
            ),
            (
                "blastEulerFoam/reactingParticles",
                [
                    "dusty environment",
                    "dust explosion",
                    "reacting particles",
                    "particle phase",
                    "particles",
                ],
                125.0,
            ),
            (
                "blastFoam/movingCone",
                [
                    "moving cone",
                    "cone moving",
                    "supersonic",
                    "hypersonic",
                ],
                125.0,
            ),
            (
                "blastFoam/triplePointShockInteration",
                [
                    "triple point",
                    "three point",
                    "incident shock",
                    "shock wave",
                    "mach number",
                ],
                125.0,
            ),
            (
                "blastFoam/internalDetonation/internalDetonation_withObstacleAndGlass",
                [
                    "closed space",
                    "internal detonation",
                    "obstacle",
                    "glass",
                    "window",
                    "pburst",
                    "fracture model",
                    "principal strain",
                    "principal stress",
                    "explosive charge",
                ],
                155.0,
            ),
            (
                "blastFoam/internalDetonation/internalDetonation",
                ["internal detonation"],
                45.0,
            ),
            (
                "blastFoam/mappedBuilding3D",
                [
                    "blast wave impact",
                    "impact on a building",
                    "impact on building",
                    "field mapping",
                    "mapped building",
                    "building",
                ],
                145.0,
            ),
            (
                "blastFoam/building3D",
                ["building3d", "building"],
                35.0,
            ),
            (
                "blastFoam/burstingWindow_workshop",
                ["bursting window", "window workshop"],
                80.0,
            ),
        ]

        normalized_case_no_space = normalized_case.replace(" ", "")
        for target_case, phrases, boost in case_intent_rules:
            normalized_target = self._normalize_match_text(target_case).replace(" ", "")
            if normalized_case_no_space == normalized_target and self._query_mentions_any(normalized_query, phrases):
                score += boost

        return score

    def _score_file_candidate(
        self,
        normalized_query: str,
        file_path: str,
        variable_names: List[str],
    ) -> float:
        normalized_path = self._normalize_match_text(file_path)
        path_no_space = normalized_path.replace(" ", "")
        query_no_space = normalized_query.replace(" ", "")
        score = 0.0

        def endswith(suffix: str) -> bool:
            return path_no_space.endswith(self._normalize_match_text(suffix).replace(" ", ""))

        if normalized_path and normalized_path in normalized_query:
            score += 30.0

        file_intent_rules = [
            (
                "constant/combustionProperties",
                [
                    "laminar flame speed",
                    "flame speed",
                    "equivalence ratio",
                    "fuel rich",
                    "fuel rich mixture",
                    "reaction rate",
                    "arrhenius",
                    "infinitely fast",
                    "combustion model",
                    "chemical reaction",
                    "mixture",
                ],
                95.0,
            ),
            (
                "0/Su",
                ["laminar flame speed", "flame speed", "su"],
                12.0,
            ),
            (
                "constant/turbulenceProperties",
                [
                    "turbulence",
                    "spalart allmaras",
                    "spalart",
                    "allmaras",
                    "k epsilon",
                    "k omega",
                    "omega sst",
                    "sst",
                    "rans",
                    "laminar",
                ],
                85.0,
            ),
            (
                "constant/turbulenceProperties.gas",
                ["gas phase", "for gas", "gas turbulence", "gas model", "gas"],
                95.0,
            ),
            (
                "constant/turbulenceProperties.particles",
                [
                    "particle phase",
                    "particles phase",
                    "thermal conductivity model",
                    "conductivity model",
                    "particle turbulence",
                ],
                95.0,
            ),
            (
                "system/controlDict",
                [
                    "shorter duration",
                    "longer duration",
                    "run for",
                    "duration",
                    "end time",
                    "courant",
                    "write interval",
                    "write frequency",
                    "output interval",
                    "delta t",
                    "time step",
                    "function object",
                    "functions",
                ],
                88.0,
            ),
            (
                "system/setFieldsDict",
                [
                    "charge mass",
                    "tnt equivalent",
                    "c4 equivalent",
                    "charge location",
                    "explosive charge",
                    "high pressure region",
                    "initial position",
                    "initial distribution",
                    "distribution region",
                    "set fields",
                    "box to cell",
                    "sphere to cell",
                    "closer to one end",
                    "location of the explosive",
                ],
                96.0,
            ),
            (
                "system/blockMeshDict",
                [
                    "block mesh",
                    "mesh",
                    "cell size",
                    "resolution",
                    "grid",
                    "domain size",
                    "geometry",
                    "obstacle",
                ],
                78.0,
            ),
            (
                "constant/dynamicMeshDict",
                [
                    "moving cone",
                    "dynamic mesh",
                    "refinement level",
                    "refine",
                    "moving body",
                    "motion",
                ],
                90.0,
            ),
            (
                "system/fvSchemes",
                [
                    "ausm",
                    "hllc",
                    "kurganov",
                    "muscl",
                    "quick",
                    "runge kutta",
                    "time integration",
                    "gradient scheme",
                    "reconstruction",
                    "flux scheme",
                    "interpolation",
                ],
                90.0,
            ),
            (
                "system/fvSolution",
                [
                    "pressure corrector",
                    "correctors",
                    "smoothsolver",
                    "gamg",
                    "solver",
                    "pimple",
                    "piso",
                ],
                90.0,
            ),
            (
                "constant/phaseProperties",
                [
                    "phase properties",
                    "equation of state",
                    "thermo",
                    "janaf",
                    "activation model",
                    "fracture model",
                    "window",
                    "pburst",
                    "principal strain",
                    "principal stress",
                    "visco elastic",
                    "elastic plastic",
                    "particle diameter",
                    "diameter model",
                    "drag model",
                    "heat transfer",
                    "interfacial pressure",
                    "interfacial velocity",
                    "packing limit",
                    "restitution",
                    "bkw",
                    "jwl",
                    "lszk",
                    "stiffened gas",
                    "rho const",
                    "programmed ignition",
                    "diameter",
                    "millimeter",
                    "millimeters",
                    "stronger window",
                    "fragile window",
                    "window strength",
                    "coefficient of restitution",
                ],
                92.0,
            ),
            (
                "constant/thermophysicalProperties",
                [
                    "thermophysical",
                    "econstthermo",
                    "econst",
                    "constant specific heat",
                    "cv",
                    "hf",
                ],
                92.0,
            ),
            (
                "0/U",
                [
                    "supersonic speed",
                    "hypersonic speed",
                    "moving cone",
                    "shock wave",
                    "mach number",
                    "incident shock",
                    "velocity",
                ],
                72.0,
            ),
            (
                "0/U.orig",
                [
                    "supersonic speed",
                    "hypersonic speed",
                    "moving cone",
                    "shock wave",
                    "mach number",
                    "incident shock",
                    "velocity",
                ],
                72.0,
            ),
        ]

        for suffix, phrases, boost in file_intent_rules:
            if endswith(suffix) and self._query_mentions_any(normalized_query, phrases):
                score += boost

        if "gas" in normalized_query and endswith("constant/turbulenceProperties.gas"):
            score += 20.0
        if "particle" in normalized_query and endswith("constant/turbulenceProperties.particles"):
            score += 20.0
        if "building" in normalized_query and "building3d/" in path_no_space:
            score += 35.0
        if "field mapping" in normalized_query and "building3d/" in path_no_space:
            score += 20.0
        if "sector" in normalized_query and "sector/" in path_no_space:
            score += 35.0
        if "wedge" in normalized_query and "wedge/" in path_no_space:
            score += 35.0

        generic_tokens = {
            "model",
            "type",
            "value",
            "air",
            "default",
            "phase",
            "file",
            "dictionary",
            "field",
            "properties",
        }
        for variable_name in variable_names:
            normalized_variable = self._normalize_match_text(variable_name)
            if not normalized_variable:
                continue

            compact_variable = normalized_variable.replace(" ", "")
            if compact_variable in {"su", "cv", "hf"}:
                if re.search(rf"\b{re.escape(compact_variable)}\b", normalized_query):
                    score += 12.0
                continue

            for token in normalized_variable.split():
                if len(token) < 4 or token in generic_tokens:
                    continue
                if token in normalized_query:
                    score += 6.0

        if endswith("constant/phaseProperties") and "0/d.particles.orig" in query_no_space:
            score -= 10.0

        return score

    def _resolve_same_case_file_results(
        self,
        user_query: str,
        node_ids: list,
        structured_results: List[Dict[str, object]],
        top_k: int,
        score_by_node: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, object]]:
        if top_k <= 0:
            return []

        case_candidates = self._infer_case_candidates(
            user_query=user_query,
            node_ids=node_ids,
            score_by_node=score_by_node,
        )
        if not case_candidates:
            return structured_results[:top_k]

        dominant_case, dominant_score = case_candidates[0]
        second_score = case_candidates[1][1] if len(case_candidates) > 1 else 0.0
        current_cases = {str(item.get("case_path")) for item in structured_results if item.get("case_path")}

        if len(current_cases) > 1 and dominant_score < (second_score * 1.2):
            return structured_results[:top_k]

        file_ids = self.case_to_file_ids.get(dominant_case, [])
        if not file_ids:
            return structured_results[:top_k]

        normalized_query = self._normalize_match_text(user_query)
        current_by_canonical = {
            str(item.get("canonical_id")): item
            for item in structured_results
            if item.get("canonical_id")
        }
        scored_candidates = []

        for file_id in file_ids:
            file_node = self.id_to_node.get(file_id)
            if not file_node:
                continue

            full_file_path = file_node.get("properties", {}).get("path")
            if not full_file_path:
                continue

            normalized_file_path = self._normalize_file_reference(str(full_file_path), dominant_case)
            canonical_id = f"{dominant_case}::{normalized_file_path}"
            variable_names = []
            for variable_id in self.file_to_variable_ids.get(file_id, []):
                variable_node = self.id_to_node.get(variable_id)
                if variable_node:
                    variable_name = variable_node.get("properties", {}).get("name")
                    if variable_name:
                        variable_names.append(str(variable_name))

            score = self._score_file_candidate(
                normalized_query=normalized_query,
                file_path=normalized_file_path,
                variable_names=variable_names,
            )

            existing = current_by_canonical.get(canonical_id)
            if existing:
                existing_rank = int(existing.get("rank") or 999)
                score += max(0.0, 45.0 - existing_rank)

            scored_candidates.append(
                (
                    score,
                    canonical_id,
                    {
                        "case_path": dominant_case,
                        "file_path": normalized_file_path,
                        "canonical_id": canonical_id,
                        "path": f"{dominant_case}/{normalized_file_path}",
                        "source_node_id": file_id,
                        "source_node_type": "File",
                        "source_node_name": file_node.get("properties", {}).get("name"),
                        "score": score,
                    },
                )
            )

        scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)

        resolved_results = []
        seen = set()
        for rank, (_score, canonical_id, candidate) in enumerate(scored_candidates, start=1):
            if canonical_id in seen:
                continue
            seen.add(canonical_id)
            candidate["rank"] = rank
            resolved_results.append(candidate)
            if len(resolved_results) >= top_k:
                break

        if not resolved_results:
            return structured_results[:top_k]

        top_resolved_score = float(resolved_results[0].get("score") or 0.0)
        top_existing_score = 0.0
        if structured_results:
            top_existing_score = float(structured_results[0].get("score") or 0.0)

        if top_resolved_score <= 0 and top_existing_score > 0:
            return structured_results[:top_k]

        return resolved_results

    def _retrieve_node_details_with_content(self, node_ids: list, include_file_content: bool = True, node_to_case: dict = None) -> str:
        """
        Retrieve and format the details for the identified nodes, including file content.

        Args:
            node_ids: A list of node IDs to retrieve details for.
            include_file_content: Whether to include actual file content for File nodes.
            node_to_case: Optional dictionary mapping node IDs to their Case node information.

        Returns:
            A formatted string containing the details of the nodes with file content.
        """
        if not node_ids:
            return "No relevant case content information found in the knowledge base."

        # 如果没有提供 case 信息，自动获取
        if node_to_case is None:
            print("Retrieving case information for nodes...")
            node_to_case = self._get_case_info_for_nodes(node_ids)

        result = []
        for node_id in node_ids:
            node = self.id_to_node.get(node_id)
            if not node:
                continue

            label = node.get('label', 'N/A')
            properties = node.get('properties', {})

            content = f"## Type: {label} (ID: {node_id})\n"

            # 添加 Case Context 信息（如果有）
            if node_id in node_to_case:
                case_info = node_to_case[node_id]
                case_props = case_info.get('properties', {})
                content += "\n### Case Context\n"
                content += f"- **Case Name**: {case_props.get('name', 'N/A')}\n"
                content += f"- **Case Path**: {case_props.get('path', 'N/A')}\n"
                content += f"- **Solver**: {case_props.get('solver', 'N/A')}\n"

                # Try to fetch README content as description
                case_path = case_props.get('path')
                description = None
                if case_path and self.foam_tutorials_path:
                    for readme_name in ['README.md', 'README']:
                        readme_rel_path = os.path.join(case_path, readme_name)
                        full_readme_path = Path(self.foam_tutorials_path) / readme_rel_path
                        if full_readme_path.exists():
                            description = self._get_file_content(readme_rel_path, max_lines=50)
                            break

                if description:
                    content += f"- **Description**: \n{description}\n"
                content += "\n"

            # 显示节点自己的属性
            content += "### Node Properties\n"
            for key, value in properties.items():
                content += f"- **{key.capitalize()}**: {value}\n"

            # If this is a File node, try to retrieve the actual file content
            if include_file_content and label == 'File':
                file_path = properties.get('path')
                if file_path:
                    if self.foam_tutorials_path:
                        file_path = os.path.join(self.foam_tutorials_path, file_path)

                    content += f"\n### File Content:\n"
                    content += "```\n"
                    file_content = self._get_file_content(file_path)
                    content += file_content
                    content += "\n```\n"

            # If this is a Variable node, find the file that defines it and retrieve content
            elif label == 'Variable':
                file_path = self._find_file_for_variable(node_id)
                if file_path:
                    content += f"\n### Defined in File: {file_path}\n"
                    if include_file_content:
                        content += "### File Content:\n"
                        content += "```\n"
                        file_content = self._get_file_content(file_path)
                        content += file_content
                        content += "\n```\n"
                else:
                    content += f"\n*Note: Could not find the file that defines this variable*\n"

            result.append(content)

        if not result:
            return "Could not retrieve details for the identified nodes."

        return "--- Retrieved Case Content Information ---\n\n" + "\n---\n".join(result)

    def _react_decide(self, user_query: str, kg_summary: str, history: list) -> dict:
        """
        Use LLM to decide the next action in the ReAct loop.
        """
        if self.llm is None:
            strategy = {
                "search_criteria": {
                    "node_labels": [],
                    "property_filters": {},
                    "keyword_search": [
                        token
                        for token in re.findall(r"[A-Za-z0-9_.-]+", user_query)
                        if len(token) > 2
                    ],
                }
            }
            return {
                "thought": "No retrieval LLM is configured; using deterministic keyword search.",
                "action": "search_nodes",
                "action_input": strategy,
            }

        history_text = ""
        for item in history:
            role = item['role']
            content = item['content']
            history_text += f"{role.upper()}: {content}\n"

        prompt = f"""You are an intelligent agent searching a knowledge graph of OpenFOAM cases.
Your goal is to find information relevant to the user's query.

{kg_summary}

User Query: "{user_query}"

History of your thoughts and actions:
{history_text}

Available Tools:
1. search_nodes: Search for nodes in the knowledge graph.
   Input: A JSON object with search criteria (node_labels, property_filters, keyword_search).
   Example Input: {{ "node_labels": ["Case"], "keyword_search": ["damBreak"] }}

2. inspect_nodes: Retrieve details and content of specific nodes.
   Input: A JSON object with a list of node_ids.
   Example Input: {{ "node_ids": ["case::123", "file::456"] }}

3. finish: Return the final answer to the user.
   Input: A JSON object with a list of relevant node_ids and an explanation.
   Example Input: {{ "node_ids": ["file::789"], "explanation": "Found the controlDict file." }}

Decide your next step. Return a JSON object with the following structure:
{{
    "thought": "Your reasoning for the next step",
    "action": "search_nodes" or "inspect_nodes" or "finish",
    "action_input": {{ ... }}
}}

Please provide ONLY the JSON object, no additional text.
"""

        response = self.llm.invoke(prompt)

        # Track tokens
        tracker = MetricsTracker()
        usage = getattr(response, 'usage_metadata', None) or {}
        agent_name = tracker.current_agent or "CaseContentTool"
        tracker.record_llm_call(
            agent_name=agent_name,
            input_tokens=usage.get('input_tokens', 0),
            output_tokens=usage.get('output_tokens', 0),
            model=self.llm.model_name if hasattr(self.llm, 'model_name') else 'unknown'
        )

        try:
            content = response.content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content.strip())
        except Exception as e:
            print(f"Error parsing ReAct decision: {e}")
            # Fallback or retry logic could go here
            return {
                "thought": "Error parsing response, finishing.",
                "action": "finish",
                "action_input": {"node_ids": [], "explanation": "I encountered an error processing the search."}
            }

    def _execute_react_search(
        self,
        user_query: str,
        top_k: int = 5,
        include_file_content: bool = True,
        max_iterations: Optional[int] = None,
    ) -> Dict[str, object]:
        """
        Execute the ReAct loop once and return both text and structured outputs.
        """
        max_iterations = _resolve_kg_max_iterations(max_iterations)
        print(f"Starting ReAct search for: '{user_query}'")

        kg_summary = self._get_knowledge_graph_summary()
        history = []
        fallback_node_ids = []
        score_by_node: Dict[str, float] = {}

        for i in range(max_iterations):
            print(f"Iteration {i+1}/{max_iterations}")

            decision = self._react_decide(user_query, kg_summary, history)

            thought = decision.get("thought")
            action = decision.get("action")
            action_input = decision.get("action_input")

            print(f"Thought: {thought}")
            print(f"Action: {action}")

            history.append({"role": "assistant", "content": f"Thought: {thought}\nAction: {action}\nInput: {json.dumps(action_input)}"})

            observation = ""
            if action == "search_nodes":
                strategy = {"search_criteria": action_input}
                if "search_criteria" in action_input:
                    strategy = action_input

                results = self._execute_search_strategy(strategy)
                fallback_node_ids = [node_id for node_id, _score in results[:top_k]]
                score_by_node = {node_id: float(score) for node_id, score in results}
                top_results = results[:15]
                observation = f"Found {len(results)} nodes. Top {len(top_results)}:\n"
                for node_id, score in top_results:
                    node = self.id_to_node.get(node_id)
                    if node:
                        props = node.get('properties', {})
                        name = props.get('name', 'N/A')
                        path = props.get('path', 'N/A')
                        label = node.get('label', 'N/A')
                        observation += f"- ID: {node_id}, Label: {label}, Name: {name}, Path: {path}, Score: {score}\n"

            elif action == "inspect_nodes":
                node_ids = action_input.get("node_ids", [])
                if node_ids:
                    fallback_node_ids = node_ids[:top_k]
                content = self._retrieve_node_details_with_content(node_ids, include_file_content=include_file_content)
                observation = f"Node Details:\n{content}"

            elif action == "finish":
                final_node_ids = action_input.get("node_ids", [])
                explanation = action_input.get("explanation", "")

                if not final_node_ids:
                    return {
                        "text": f"No relevant information found. {explanation}",
                        "structured_results": [],
                        "node_ids": [],
                    }

                final_content = self._retrieve_node_details_with_content(final_node_ids, include_file_content=include_file_content)
                structured_results = self._build_structured_results(
                    final_node_ids,
                    top_k=top_k,
                    score_by_node=score_by_node,
                )
                return {
                    "text": f"{explanation}\n\n{final_content}",
                    "structured_results": self._resolve_same_case_file_results(
                        user_query=user_query,
                        node_ids=final_node_ids,
                        structured_results=structured_results,
                        top_k=top_k,
                        score_by_node=score_by_node,
                    ),
                    "node_ids": final_node_ids,
                }

            else:
                observation = f"Unknown action: {action}"

            print(f"Observation: {observation[:200]}...")
            history.append({"role": "system", "content": f"Observation: {observation}"})

        if fallback_node_ids:
            print("Max iterations reached. Returning best-effort results from the last relevant nodes.")
            fallback_content = self._retrieve_node_details_with_content(
                fallback_node_ids,
                include_file_content=include_file_content,
            )
            structured_results = self._build_structured_results(
                fallback_node_ids,
                top_k=top_k,
                score_by_node=score_by_node,
            )
            return {
                "text": "Max iterations reached before finish. Returning best-effort results.\n\n" + fallback_content,
                "structured_results": self._resolve_same_case_file_results(
                    user_query=user_query,
                    node_ids=fallback_node_ids,
                    structured_results=structured_results,
                    top_k=top_k,
                    score_by_node=score_by_node,
                ),
                "node_ids": fallback_node_ids,
            }

        return {
            "text": "Max iterations reached without a final answer.",
            "structured_results": [],
            "node_ids": [],
        }

    def search_detailed(
        self,
        user_query: str,
        top_k: int = 5,
        include_file_content: bool = False,
        max_iterations: Optional[int] = None,
    ) -> Dict[str, object]:
        """
        Search the knowledge graph and return both text and structured results.
        """
        result = self._execute_react_search(
            user_query,
            top_k=top_k,
            include_file_content=include_file_content,
            max_iterations=max_iterations,
        )
        return result

    def search(self, user_query: str, top_k: int = 5, include_file_content: bool = True, max_iterations: Optional[int] = None) -> str:
        """
        Search the knowledge graph using an LLM-driven ReAct agent.

        Args:
            user_query: The user's query string.
            top_k: Number of top results to return in the final answer.
            include_file_content: Whether to include actual file content.
            max_iterations: Maximum number of ReAct iterations. If omitted,
                read from KG_RETRIEVAL_MAX_ITERATIONS (default: 3).

        Returns:
            A string containing the retrieved information.
        """
        result = self._execute_react_search(
            user_query,
            top_k=top_k,
            include_file_content=include_file_content,
            max_iterations=max_iterations,
        )
        return result["text"]


# --- Usage Example ---
def main():
    # Load environment variables from .env file at the project root
    load_dotenv(dotenv_path=Path(__file__).resolve().parents[3] / '.env')

    # Initialize the retriever
    retriever = CaseContentKnowledgeGraphRetriever()

    # Example 1: Find fvSolution settings from a specific case
    query1 = "Show me the PIMPLE settings from the blastFoam_building3D case."
    results1 = retriever.search(query1, top_k=3)
    print("\n--- Results for Query 1 ---")
    print(results1)

    # Example 2: Find turbulence model information
    query2 = "What turbulence model is used in the blastFoam_axisymmetricCharge case?"
    results2 = retriever.search(query2, top_k=3)
    print("\n--- Results for Query 2 ---")
    print(results2)

    # Example 3: Find equation of state information
    query3 = "example of functions in controlDict for blastFoam overpressure"
    results3 = retriever.search(query3, top_k=3)
    print("\n--- Results for Query 3 ---")
    print(results3)

if __name__ == '__main__':
    main()
