import json
import math
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from langchain_openai import ChatOpenAI
from principia_core.config.llm_profiles import chat_openai_kwargs
from principia_core.config.retrieval_llm import resolve_retrieval_llm_config
from principia_core.metrics.tracker import MetricsTracker


STOPWORDS = {
    "a",
    "all",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "describe",
    "described",
    "documents",
    "documented",
    "does",
    "entry",
    "explain",
    "explains",
    "for",
    "from",
    "group",
    "how",
    "i",
    "in",
    "introduces",
    "is",
    "it",
    "like",
    "model",
    "models",
    "of",
    "only",
    "or",
    "section",
    "subsection",
    "that",
    "the",
    "to",
    "use",
    "user",
    "using",
    "what",
    "where",
    "which",
    "with",
}


class UserGuideKnowledgeGraphRetriever:
    """
    A hierarchical approach to knowledge retrieval from the BlastFoam documentation.
    This class uses a two-step process:
    1. First, it identifies relevant chapters using a simplified knowledge graph
    2. Then, it retrieves more specific sections within those chapters
    3. Finally, it returns the full content of the identified target nodes
    """
    def __init__(self, llm_api_key=None, llm_base_url=None, llm_model=None):
        """
        Initialize the KnowledgeGraphRetriever.

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

        # Load knowledge bases
        self._load_knowledge_bases()

    def _load_knowledge_bases(self):
        """Load both simplified and complete knowledge bases"""
        # Determine the paths to the knowledge files
        base_dir = Path(__file__).resolve().parents[3]
        simplified_path = base_dir / "data/knowledge_graph/user_guide_knowledge_graph/simplified_user_guide_knowledge_graph.json"
        complete_path = base_dir / "data/knowledge_graph/user_guide_knowledge_graph/user_guide_knowledge_graph.json"

        # Load simplified knowledge (used for initial retrieval)
        try:
            with open(simplified_path, 'r', encoding='utf-8') as f:
                self.simplified_knowledge = json.load(f)
            print(f"Loaded {len(self.simplified_knowledge)} simplified knowledge nodes")
        except Exception as e:
            print(f"Error loading simplified knowledge: {e}")
            self.simplified_knowledge = []

        # Load complete knowledge (used for final content retrieval)
        try:
            with open(complete_path, 'r', encoding='utf-8') as f:
                self.complete_knowledge = json.load(f)
            print(f"Loaded {len(self.complete_knowledge)} complete knowledge nodes")
        except Exception as e:
            print(f"Error loading complete knowledge: {e}")
            self.complete_knowledge = []

        # Build a mapping from ID to node for faster lookups
        self.id_to_node = {node.get('id'): node for node in self.complete_knowledge if node.get('id')}
        self.number_to_node_ids: Dict[str, List[str]] = {}
        self.parent_to_children: Dict[str, List[str]] = defaultdict(list)
        for node in self.complete_knowledge:
            node_id = node.get("id")
            number = node.get("number")
            if not node_id or not number:
                if node_id and node.get("parentId"):
                    self.parent_to_children[str(node.get("parentId"))].append(str(node_id))
                continue
            self.number_to_node_ids.setdefault(str(number), []).append(str(node_id))
            if node.get("parentId"):
                self.parent_to_children[str(node.get("parentId"))].append(str(node_id))

        self.search_document_count = 0
        self.search_document_frequency: Counter[str] = Counter()
        self.search_idf_cache: Dict[str, float] = {}
        self.search_index: Dict[str, Dict[str, object]] = {}
        self.ancestor_cache: Dict[str, Tuple[str, ...]] = {}
        self.depth_cache: Dict[str, int] = {}
        self._build_search_index()

    def _build_search_index(self) -> None:
        """Precompute lightweight lexical features for graph-aware reranking."""
        self.search_document_frequency.clear()
        self.search_idf_cache.clear()
        self.search_index.clear()
        self.search_document_count = 0

        for node in self.complete_knowledge:
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue

            title = str(node.get("title") or "")
            summary = str(node.get("content_summary") or "")
            content = str(node.get("content") or "")[:2000]
            number = str(node.get("number") or "")
            semantic_type = str(node.get("semantic_type") or "")
            ancestor_titles = " ".join(self._ancestor_title_parts(node_id))

            title_tokens = self._tokenize_text(title)
            summary_tokens = self._tokenize_text(summary)
            content_tokens = self._tokenize_text(content)
            ancestor_tokens = self._tokenize_text(ancestor_titles)
            semantic_tokens = self._tokenize_text(semantic_type)
            number_tokens = self._tokenize_text(number)
            id_tokens = self._tokenize_text(node_id)

            title_blob = self._normalize_search_text(
                " ".join(part for part in (title, number, semantic_type) if part)
            )
            summary_blob = self._normalize_search_text(
                " ".join(part for part in (summary, ancestor_titles) if part)
            )
            full_blob = self._normalize_search_text(
                " ".join(
                    part
                    for part in (node_id, number, title, semantic_type, ancestor_titles, summary, content)
                    if part
                )
            )

            unique_tokens = set(
                title_tokens
                + summary_tokens
                + content_tokens
                + ancestor_tokens
                + semantic_tokens
                + number_tokens
                + id_tokens
            )
            self.search_document_frequency.update(unique_tokens)
            self.search_document_count += 1

            self.search_index[node_id] = {
                "title_counter": Counter(title_tokens),
                "summary_counter": Counter(summary_tokens),
                "content_counter": Counter(content_tokens),
                "ancestor_counter": Counter(ancestor_tokens),
                "semantic_counter": Counter(semantic_tokens),
                "number_counter": Counter(number_tokens),
                "id_counter": Counter(id_tokens),
                "title_blob": title_blob,
                "summary_blob": summary_blob,
                "full_blob": full_blob,
                "has_children": bool(self.parent_to_children.get(node_id)),
                "depth": self._node_depth(node_id),
            }

    def _node_depth(self, node_id: str) -> int:
        if node_id in self.depth_cache:
            return self.depth_cache[node_id]

        depth = 0
        current_id = node_id
        while current_id:
            node = self.id_to_node.get(current_id)
            if not node:
                break
            parent_id = node.get("parentId")
            if not parent_id:
                break
            depth += 1
            current_id = str(parent_id)

        self.depth_cache[node_id] = depth
        return depth

    def _ancestor_ids(self, node_id: str) -> Tuple[str, ...]:
        if node_id in self.ancestor_cache:
            return self.ancestor_cache[node_id]

        ancestors: List[str] = []
        current_id = node_id
        while current_id:
            node = self.id_to_node.get(current_id)
            if not node:
                break
            parent_id = node.get("parentId")
            if not parent_id:
                break
            parent_str = str(parent_id)
            ancestors.append(parent_str)
            current_id = parent_str

        result = tuple(ancestors)
        self.ancestor_cache[node_id] = result
        return result

    def _ancestor_title_parts(self, node_id: str) -> List[str]:
        parts: List[str] = []
        for ancestor_id in self._ancestor_ids(node_id):
            node = self.id_to_node.get(ancestor_id)
            if not node:
                continue
            number = str(node.get("number") or "").strip()
            title = str(node.get("title") or "").strip()
            if number:
                parts.append(number)
            if title:
                parts.append(title)
        return parts

    def _expand_compound_text(self, text: object) -> str:
        raw = str(text or "")
        raw = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
        raw = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", raw)
        raw = raw.replace("/", " ").replace("_", " ").replace("-", " ")
        raw = re.sub(r"([A-Za-z])(\d)", r"\1 \2", raw)
        raw = re.sub(r"(\d)([A-Za-z])", r"\1 \2", raw)
        return raw

    def _normalize_search_text(self, text: object) -> str:
        expanded = self._expand_compound_text(text).lower()
        return re.sub(r"[^a-z0-9]+", " ", expanded).strip()

    def _tokenize_text(self, text: object) -> List[str]:
        expanded = self._expand_compound_text(text).lower()
        raw_tokens = re.findall(r"[a-z]+|\d+(?:\.\d+)+|\d+", expanded)
        tokens: List[str] = []
        for token in raw_tokens:
            tokens.append(token)
            if "." in token:
                tokens.extend(part for part in token.split(".") if part)
        return tokens

    def _important_query_tokens(self, query: str) -> List[str]:
        tokens = self._tokenize_text(query)
        important = [token for token in tokens if token not in STOPWORDS]
        return important or tokens

    def _query_phrases(self, query_tokens: Sequence[str]) -> List[str]:
        filtered = [token for token in query_tokens if token not in STOPWORDS]
        phrases: List[str] = []
        for window in (3, 2):
            for index in range(len(filtered) - window + 1):
                phrases.append(" ".join(filtered[index:index + window]))
        return phrases

    def _idf(self, token: str) -> float:
        if token in self.search_idf_cache:
            return self.search_idf_cache[token]

        df = self.search_document_frequency.get(token, 0)
        idf = 1.0 + math.log((1.0 + self.search_document_count) / (1.0 + df))
        self.search_idf_cache[token] = idf
        return idf

    def _score_counter(self, query_counter: Counter[str], field_counter: Counter[str], weight: float) -> float:
        score = 0.0
        for token, query_count in query_counter.items():
            field_count = field_counter.get(token, 0)
            if not field_count:
                continue
            score += weight * self._idf(token) * min(query_count, field_count)
        return score

    def _infer_target_granularity(self, query: str) -> str:
        normalized_query = self._normalize_search_text(query)
        if "which chapter" in normalized_query or "what chapter" in normalized_query:
            return "chapter"

        section_markers = (
            "which section",
            "what section",
            "which subsection",
            "what subsection",
            "overview",
            "group the available",
            "introduces",
            "group the",
        )
        detail_markers = (
            "which user guide entry",
            "which model",
            "what model",
            "where is the",
            "where is",
            "what utility",
            "which utility",
            "which solver",
            "what solver",
        )

        if any(marker in normalized_query for marker in section_markers):
            return "section"
        if any(marker in normalized_query for marker in detail_markers):
            return "detail"
        if "section" in normalized_query or "subsection" in normalized_query:
            return "section"
        return "detail"

    def _score_scope_bonus(
        self,
        node_id: str,
        chapter_ids: Sequence[str],
        section_ids: Sequence[str],
        subsection_ids: Sequence[str],
    ) -> float:
        score = 0.0
        ancestor_ids = set(self._ancestor_ids(node_id))
        chapter_set = {str(item) for item in chapter_ids if item}
        section_set = {str(item) for item in section_ids if item}
        subsection_set = {str(item) for item in subsection_ids if item}

        if node_id in subsection_set:
            score += 3.0
        elif ancestor_ids & subsection_set:
            score += 2.0

        if node_id in section_set:
            score += 2.0
        elif ancestor_ids & section_set:
            score += 1.2

        if node_id in chapter_set:
            score += 1.0
        elif ancestor_ids & chapter_set:
            score += 0.8

        return score

    def _score_granularity_bonus(self, node_id: str, target_granularity: str) -> float:
        node_info = self.search_index.get(node_id, {})
        has_children = bool(node_info.get("has_children"))

        if target_granularity == "chapter":
            if node_id.startswith("ch"):
                return 4.0
            if node_id.startswith("sec"):
                return -1.5
            return -3.0

        if target_granularity == "section":
            if node_id.startswith("sec"):
                return 4.0
            if node_id.startswith("ch"):
                return -2.0
            return -2.5 if not has_children else -1.5

        # detail
        if node_id.startswith("ch"):
            return -4.0
        if node_id.startswith("sec"):
            return -2.5 if has_children else -1.0
        return 4.0 if not has_children else 1.0

    def _score_node(
        self,
        query: str,
        query_tokens: Sequence[str],
        query_counter: Counter[str],
        query_phrases: Sequence[str],
        node_id: str,
        chapter_ids: Sequence[str],
        section_ids: Sequence[str],
        subsection_ids: Sequence[str],
        target_granularity: str,
    ) -> float:
        node_info = self.search_index.get(node_id)
        if not node_info:
            return float("-inf")

        score = 0.0
        score += self._score_counter(query_counter, node_info["title_counter"], 4.5)
        score += self._score_counter(query_counter, node_info["summary_counter"], 2.0)
        score += self._score_counter(query_counter, node_info["ancestor_counter"], 1.5)
        score += self._score_counter(query_counter, node_info["number_counter"], 2.0)
        score += self._score_counter(query_counter, node_info["id_counter"], 1.5)
        score += self._score_counter(query_counter, node_info["semantic_counter"], 0.8)
        score += self._score_counter(query_counter, node_info["content_counter"], 0.6)

        title_blob = str(node_info["title_blob"])
        summary_blob = str(node_info["summary_blob"])
        full_blob = str(node_info["full_blob"])
        normalized_query = self._normalize_search_text(query)
        if normalized_query and normalized_query in full_blob:
            score += 3.5
        if title_blob and title_blob in normalized_query:
            score += 4.0
        if normalized_query and title_blob and normalized_query in title_blob:
            score += 2.0

        for phrase in query_phrases:
            if phrase and phrase in title_blob:
                score += 3.0
            elif phrase and phrase in summary_blob:
                score += 1.2

        title_tokens = [
            token for token in node_info["title_counter"]
            if token not in STOPWORDS
        ]
        matched_title_tokens = [token for token in title_tokens if token in query_counter]
        if matched_title_tokens:
            score += 0.6 * len(matched_title_tokens)
            title_match_ratio = len(matched_title_tokens) / max(1, len(title_tokens))
            if title_match_ratio >= 0.8:
                score += 3.5 * title_match_ratio
            elif len(matched_title_tokens) >= 2:
                score += 1.5

        score += self._score_scope_bonus(node_id, chapter_ids, section_ids, subsection_ids)
        score += self._score_granularity_bonus(node_id, target_granularity)
        score += 0.08 * float(node_info["depth"])

        return score

    def _rank_candidates(
        self,
        query: str,
        chapter_ids: Sequence[str],
        section_ids: Sequence[str],
        subsection_ids: Sequence[str],
        top_k: int,
    ) -> List[str]:
        query_tokens = self._important_query_tokens(query)
        query_counter: Counter[str] = Counter(query_tokens)
        query_phrases = self._query_phrases(query_tokens)
        target_granularity = self._infer_target_granularity(query)

        ranked: List[Tuple[float, str]] = []
        for node_id in self.id_to_node:
            score = self._score_node(
                query=query,
                query_tokens=query_tokens,
                query_counter=query_counter,
                query_phrases=query_phrases,
                node_id=node_id,
                chapter_ids=chapter_ids,
                section_ids=section_ids,
                subsection_ids=subsection_ids,
                target_granularity=target_granularity,
            )
            if score <= 0:
                continue
            ranked.append((score, node_id))

        ranked.sort(key=lambda item: (-item[0], item[1]))
        ordered = [node_id for _score, node_id in ranked]

        if ordered:
            return ordered[:top_k]

        fallback = list(subsection_ids) + list(section_ids) + list(chapter_ids)
        deduped: List[str] = []
        seen = set()
        for node_id in fallback:
            resolved_id = self._resolve_node_id(node_id)
            if not resolved_id or resolved_id in seen:
                continue
            seen.add(resolved_id)
            deduped.append(resolved_id)
            if len(deduped) >= top_k:
                break
        return deduped

    def _resolve_node_id(self, node_reference) -> Optional[str]:
        """Resolve a node reference from node ID or section number."""
        if not node_reference:
            return None

        text = str(node_reference).strip()
        if not text:
            return None

        normalized_id = self._normalize_node_id(text)
        if normalized_id in self.id_to_node:
            return normalized_id

        cleaned_number = (
            text.replace("Section", "")
            .replace("section", "")
            .replace("Chapter", "")
            .replace("chapter", "")
            .strip()
        )
        matches = self.number_to_node_ids.get(cleaned_number, [])
        if len(matches) == 1:
            return matches[0]
        return None

    def _get_ancestor_context(self, node_id: str) -> Dict[str, Optional[str]]:
        """Return the enclosing section and chapter IDs for a node."""
        current_id = node_id
        section_id: Optional[str] = None
        chapter_id: Optional[str] = None

        while current_id:
            node = self.id_to_node.get(current_id)
            if not node:
                break

            current_node_id = str(node.get("id"))
            if chapter_id is None and current_node_id.startswith("ch"):
                chapter_id = current_node_id
            if section_id is None and (current_node_id.startswith("sec") or current_node_id.startswith("ch")):
                section_id = current_node_id

            parent_id = node.get("parentId")
            current_id = str(parent_id) if parent_id else ""

        return {
            "section_id": section_id or node_id,
            "chapter_id": chapter_id,
        }

    def _build_structured_results(self, node_ids: List[str], top_k: int = 5) -> List[Dict[str, object]]:
        """Build structured retrieval results for evaluation."""
        structured_results: List[Dict[str, object]] = []
        deduped_node_ids: List[str] = []
        seen = set()

        for node_id in node_ids:
            resolved_id = self._resolve_node_id(node_id)
            if not resolved_id or resolved_id in seen:
                continue
            seen.add(resolved_id)
            deduped_node_ids.append(resolved_id)

        total = max(1, len(deduped_node_ids))
        for rank, resolved_id in enumerate(deduped_node_ids, start=1):
            node = self.id_to_node.get(resolved_id)
            if not node:
                continue

            ancestor_context = self._get_ancestor_context(resolved_id)
            structured_results.append(
                {
                    "node_id": resolved_id,
                    "canonical_id": resolved_id,
                    "number": node.get("number"),
                    "title": node.get("title"),
                    "parent_id": node.get("parentId"),
                    "section_id": ancestor_context["section_id"],
                    "chapter_id": ancestor_context["chapter_id"],
                    "score": float(total - rank + 1) / float(total),
                }
            )
            if len(structured_results) >= top_k:
                break

        return structured_results

    def _identify_relevant_chapters(self, query):
        """
        First level of retrieval: identify relevant chapters

        Args:
            query: User's query string

        Returns:
            List of chapter node IDs deemed relevant
        """
        # Filter to just get chapter-level nodes
        chapter_nodes = [node for node in self.simplified_knowledge
                        if node.get('id') and
                        node.get('id').startswith('ch')]

        # Create a prompt to identify relevant chapters
        chapters_info = "\n".join([
            f"Chapter {node.get('number', 'unknown')}: {node.get('title', 'untitled')}"
            for node in chapter_nodes
        ])
        example_output = {'chapters': ['ch2', 'ch3', 'ch19']}
        prompt = f"""You are an expert in computational fluid dynamics and the BlastFoam software.
Given a user query about BlastFoam and a list of available documentation chapters,
identify which chapters would contain relevant information to answer the query.

User Query: "{query}"

Available Chapters:
{chapters_info}

Output only the IDs of the relevant chapters in a JSON array format.
If no chapters seem relevant, return an empty array.
Example:
{json.dumps(example_output, indent=2)}
"""

        # Call LLM to identify relevant chapters
        try:
            if self.llm is None:
                return []
            response = self.llm.invoke(
                [{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )

            # Track tokens
            tracker = MetricsTracker()
            usage = getattr(response, 'usage_metadata', None) or {}
            agent_name = tracker.current_agent or "UserGuideTool"
            tracker.record_llm_call(
                agent_name=agent_name,
                input_tokens=usage.get('input_tokens', 0),
                output_tokens=usage.get('output_tokens', 0),
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else 'unknown'
            )

            # Parse the response
            result = json.loads(response.content)
            relevant_chapters = result.get("chapters", [])
            if not isinstance(relevant_chapters, list):
                relevant_chapters = [relevant_chapters]

            print(f"Identified {len(relevant_chapters)} relevant chapters: {relevant_chapters}")
            return relevant_chapters

        except Exception as e:
            print(f"Error identifying relevant chapters: {e}")
            # If error, return empty list
            return []

    def _identify_relevant_sections(self, query, chapter_ids):
        """
        Second level of retrieval: within identified chapters, find relevant sections

        Args:
            query: User's query string
            chapter_ids: List of relevant chapter IDs

        Returns:
            List of section node IDs deemed relevant
        """
        if not chapter_ids:
            return []

        # Get all sections that belong to the identified chapters
        sections = []
        for node in self.simplified_knowledge:
            if (node.get('parentId') in chapter_ids or
                any(node.get('id', '').startswith(ch_id + '.') for ch_id in chapter_ids)):
                sections.append(node)

        if not sections:
            # If no sections found, return the chapter IDs themselves
            return chapter_ids

        # Create a prompt to identify relevant sections
        sections_info = "\n".join([
            f"Sec {node.get('number', 'unknown')}: {node.get('title', 'untitled')} - {node.get('content_summary', 'No summary')}"
            for node in sections
        ])
        example_output = {'sections': ['sec2.1', 'sec2.3', 'sec5.2']}
        prompt = f"""You are an expert in computational fluid dynamics and the BlastFoam software.
Given a user query and a list of documentation sections, identify which sections would
contain information most relevant to answering the query.

User Query: "{query}"

Available Sections:
{sections_info}

Output only the IDs of the relevant sections in a JSON array format.
Choose the most specific sections (using sec) that would answer the query.
Example:
{json.dumps(example_output, indent=2)}
"""

        # Call LLM to identify relevant sections
        try:
            if self.llm is None:
                return chapter_ids
            response = self.llm.invoke(
                [{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )

            # Track tokens
            tracker = MetricsTracker()
            usage = getattr(response, 'usage_metadata', None) or {}
            agent_name = tracker.current_agent or "UserGuideTool"
            tracker.record_llm_call(
                agent_name=agent_name,
                input_tokens=usage.get('input_tokens', 0),
                output_tokens=usage.get('output_tokens', 0),
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else 'unknown'
            )

            # Parse the response
            result = json.loads(response.content)
            relevant_sections = result.get("sections", [])
            if not isinstance(relevant_sections, list):
                relevant_sections = [relevant_sections]

            print(f"Identified {len(relevant_sections)} relevant sections: {relevant_sections}")

            # If no sections identified, fall back to the chapters
            if not relevant_sections:
                return chapter_ids

            return relevant_sections

        except Exception as e:
            print(f"Error identifying relevant sections: {e}")
            # If error, return chapter IDs as fallback
            return chapter_ids

    def _identify_relevant_subsections(self, query, section_ids):
        """
        Third level of retrieval: within identified sections, find relevant subsections at all levels

        This function recursively retrieves all levels of subsections under the provided section IDs
        and includes the section IDs themselves in the search scope. It then identifies the most
        relevant subsections for the user's query using section numbers rather than IDs.

        Args:
            query: User's query string
            section_ids: List of relevant section IDs

        Returns:
            List of subsection node IDs deemed relevant
        """
        if not section_ids:
            return []

        # Get the original section nodes to include in the search
        section_nodes = []
        for section_id in section_ids:
            node = self.id_to_node.get(section_id)
            if node:
                section_nodes.append(node)

        # Get all subsections recursively under the identified sections
        subsections = []

        # Add the sections themselves to the search scope
        subsections.extend(section_nodes)

        # Function to recursively find all children of a node
        def get_all_children(parent_id):
            children = []
            for node in self.complete_knowledge:
                if node.get('parentId') == parent_id:
                    children.append(node)
                    # Recursively get children of this node
                    children.extend(get_all_children(node.get('id')))
            return children

        # Get all subsections for each section
        for section_id in section_ids:
            subsections.extend(get_all_children(section_id))

        if not subsections:
            # If no subsections found, return the section IDs themselves
            return section_ids

        # Create mapping from section number to node ID for retrieval later
        number_to_id_map = {}
        for node in subsections:
            number = node.get('number')
            if number:
                number_to_id_map[number] = node.get('id')

        # Create a prompt to identify relevant subsections using section numbers
        subsections_info = "\n".join([
            f"Section {node.get('number', 'unknown')}: {node.get('title', 'untitled')} - {node.get('content_summary', 'No summary')}"
            for node in subsections
        ])
        example_output = {'section_numbers': ['2.2.1', '3.2', '5.4.2']}
        prompt = f"""You are an expert in computational fluid dynamics and the BlastFoam software.
Given a user query and a list of sections and subsections, identify which ones would
contain information most relevant to answering the query.

User Query: "{query}"

Available Sections/Subsections:
{subsections_info}

Output only the section numbers of the relevant subsections in a JSON array format.
Choose the most specific subsections that would answer the query.
Example:
{json.dumps(example_output, indent=2)}
"""

        # Call LLM to identify relevant subsections
        try:
            if self.llm is None:
                return section_ids
            response = self.llm.invoke(
                [{"role": "user", "content": prompt}],
                response_format={"type": "json_object"}
            )

            # Track tokens
            tracker = MetricsTracker()
            usage = getattr(response, 'usage_metadata', None) or {}
            agent_name = tracker.current_agent or "UserGuideTool"
            tracker.record_llm_call(
                agent_name=agent_name,
                input_tokens=usage.get('input_tokens', 0),
                output_tokens=usage.get('output_tokens', 0),
                model=self.llm.model_name if hasattr(self.llm, 'model_name') else 'unknown'
            )

            # Parse the response
            result = json.loads(response.content)
            relevant_section_numbers = result.get("section_numbers", [])
            if not isinstance(relevant_section_numbers, list):
                relevant_section_numbers = [relevant_section_numbers]

            print(f"Identified {len(relevant_section_numbers)} relevant section numbers: {relevant_section_numbers}")

            # Convert section numbers back to node IDs
            relevant_subsection_ids = []
            for section_number in relevant_section_numbers:
                # Check if this number exists in our map
                if section_number in number_to_id_map:
                    relevant_subsection_ids.append(number_to_id_map[section_number])
                else:
                    # Try to find a node with this number directly
                    for node in subsections:
                        if node.get('number') == section_number:
                            relevant_subsection_ids.append(node.get('id'))
                            break

            print(f"Mapped to {len(relevant_subsection_ids)} subsection IDs: {relevant_subsection_ids}")

            # If no subsections identified or mapping failed, fall back to the sections
            if not relevant_subsection_ids:
                return section_ids

            return relevant_subsection_ids

        except Exception as e:
            print(f"Error identifying relevant subsections: {e}")
            # If error, return section IDs as fallback
            return section_ids

    def _normalize_node_id(self, node_id):
        """
        Normalize a node ID by removing spaces and converting 'section' to 'sec'

        Args:
            node_id: The node ID string to normalize

        Returns:
            Normalized node ID string
        """
        # Remove spaces
        node_id = str(node_id).strip().replace(" ", "")
        # Convert 'section' to 'sec' case-insensitively
        node_id = node_id.lower().replace("section", "sec")
        if node_id.startswith("sec"):
            # Restore the original case for the 'sec' prefix
            node_id = "sec" + node_id[3:]
        return node_id

    def _retrieve_full_content(self, node_ids):
        """
        Retrieve the full content for the identified nodes

        Args:
            node_ids: List of node IDs to retrieve full content for

        Returns:
            String containing the full formatted content
        """
        if not node_ids:
            return "No relevant information found in the knowledge base."

        result = []
        valid_node_ids = set()

        for node_id in node_ids:
            normalized_node_id = self._normalize_node_id(node_id)
            node = self.id_to_node.get(normalized_node_id)
            if not node:
                continue
            valid_node_ids.add(normalized_node_id)
            # Format the node content
            section_content = f"## Section {node.get('number', 'unknown')}: {node.get('title', 'untitled')}\n\n"

            if node.get('content_summary'):
                section_content += f"**Summary:** {node.get('content_summary')}\n\n"

            if node.get('content'):
                section_content += f"**Content:**\n{node.get('content')}\n\n"

            # Add table information if available
            table = node.get('table')
            if table and table != '[]':
                try:
                    if isinstance(table, str):
                        table = json.loads(table)
                    section_content += f"**Parameters Table:**\n{json.dumps(table, indent=2)}\n\n"
                except:
                    pass

            result.append(section_content)
        print(f"Identified {len(result)} relevant contents: {', '.join(valid_node_ids)}")
        if not result:
            return "No content found for the identified sections."

        return "--- Retrieved Documentation Information ---\n\n" + "\n---\n".join(result)

    def search_detailed(
        self,
        user_query: str,
        top_k: int = 5,
        include_file_content: bool = False,
        max_iterations: Optional[int] = None,
    ) -> Dict[str, object]:
        """
        Search the knowledge base and return both formatted text and structured results.
        """
        del include_file_content
        del max_iterations

        print(f"Searching knowledge base for: '{user_query}'")

        chapter_ids = self._identify_relevant_chapters(user_query)
        section_ids = self._identify_relevant_sections(user_query, chapter_ids)
        subsection_ids = self._identify_relevant_subsections(user_query, section_ids)
        ranked_node_ids = self._rank_candidates(
            query=user_query,
            chapter_ids=chapter_ids,
            section_ids=section_ids,
            subsection_ids=subsection_ids,
            top_k=top_k,
        )
        structured_results = self._build_structured_results(ranked_node_ids, top_k=top_k)
        ordered_node_ids = [str(item["node_id"]) for item in structured_results]
        results = self._retrieve_full_content(ordered_node_ids)

        return {
            "text": results,
            "structured_results": structured_results,
            "node_ids": ordered_node_ids,
        }

    def search(self, user_query: str, top_k: int = 5, include_file_content: bool = False, max_iterations: Optional[int] = None) -> str:
        """
        Main search method that implements the hierarchical retrieval process

        Args:
            user_query: The user's query string

        Returns:
            String containing the retrieved knowledge content
        """
        result = self.search_detailed(
            user_query,
            top_k=top_k,
            include_file_content=include_file_content,
            max_iterations=max_iterations,
        )
        return str(result["text"])

# --- 使用示例 ---
def main():
    # 初始化工具 - 使用环境变量作为默认值
    knowledge_retriever = UserGuideKnowledgeGraphRetriever()

    # 示例1：检索时间积分方案
    query1 = "How do I use the RK4 time integration scheme?"
    results1 = knowledge_retriever.search(query1)
    print("\n--- Results for Query 1 ---")
    print(results1)

    # 示例2：检索摩擦模型
    query2 = "List all the Frictional stress models and their titles"
    results2 = knowledge_retriever.search(query2)
    print("\n--- Results for Query 2 ---")
    print(results2)

    # 示例3：检索特定参数
    query3 = "What are the parameters for the JohnsonJackson model?"
    results3 = knowledge_retriever.search(query3)
    print("\n--- Results for Query 3 ---")
    print(results3)

    # 示例4：复杂实体查询
    query4 = "I need to set up a simulation for a mine buried charge. Can you find the relevant example section?"
    results4 = knowledge_retriever.search(query4)
    print("\n--- Results for Query 4 ---")
    print(results4)


if __name__ == '__main__':
    main()
