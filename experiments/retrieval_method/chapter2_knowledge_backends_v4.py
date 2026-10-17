"""Comparable arms for the new graph activity; legacy adapters stay unchanged."""
from pathlib import Path

from chapter2_qa_backends import HybridBackend, NativeBackend, create_backend

MAIN_METHODS = ('bm25', 'e5', 'hybrid', 'graph', 'none')
GRAPH_ABLATIONS = ('no_cross', 'no_conditions', 'no_extension', 'no_context', 'adjacent_only', 'parent_blanket')
METHODS = (*MAIN_METHODS, *GRAPH_ABLATIONS)


def tool_method(method):
    if method not in METHODS:raise ValueError('Unregistered retrieval method')
    return method if method in MAIN_METHODS else 'graph'


class HybridNativeView(HybridBackend):
    """Expose the existing exact RRF ordering for pure-backend diagnostics."""
    def ranked(self, query, limit):
        rows = self.search(query, limit)
        event = self.events[-1]
        native = [dict(**row, native_unit=f'rrf:{row["path"]}:{row["start"]}-{row["end"]}', native_rank=rank)
                  for rank, row in enumerate(rows, 1)]
        packet = self.bm25.engine.sources.map(native)
        return packet, dict(fusion='RRF_k60_pool64', **event['stats'])


def backend(method, resources, *, context_characters=2400, parent_ratio=.5):
    tool_method(method)
    if method == 'none':return None
    corpus, source_map = Path(resources['corpus']), Path(resources['source_map'])
    if method in {'bm25', 'e5'}:
        return create_backend(method, corpus, source_map, e5_index=Path(resources['e5_manifest']).parent)
    if method == 'hybrid':
        return HybridNativeView(backend('bm25', resources), backend('e5', resources))
    from chapter2_knowledge_graph_v4 import AdaptiveSourceGraph
    variant = method if method in {'no_cross', 'no_conditions', 'no_extension'} else 'full'
    policy = {'no_context': 'none', 'adjacent_only': 'adjacent', 'parent_blanket': 'blanket'}.get(method, 'adaptive')
    engine = AdaptiveSourceGraph(Path(resources['graph_' + variant]), corpus, corpus_manifest=source_map,
        context_policy=policy, context_characters=context_characters, parent_ratio=parent_ratio,
        options=dict(with_cross=variant != 'no_cross', with_conditions=variant != 'no_conditions', with_paths=variant != 'no_extension'))
    return NativeBackend(engine, graph=True)
