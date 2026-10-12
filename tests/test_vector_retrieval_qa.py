import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/retrieval_method"))
import candidate_hybrid as hybrid
import vector_retrieval_qa as vector


def test_dense_mode_does_not_add_lexical_rankings(tmp_path, monkeypatch):
    retriever = hybrid.Retriever.__new__(hybrid.Retriever)
    retriever.docs = [
        {"id": "a", "path": "a", "start": 1, "end": 1, "text": "literal"},
        {"id": "b", "path": "b", "start": 1, "end": 1, "text": "semantic"},
    ]
    retriever.counts = []
    retriever.lengths = []
    retriever.average = 1
    retriever.postings = {"literal": [(0, 1)]}
    retriever.semantic = True
    retriever.vectors = __import__("numpy").array([[0.0, 1.0], [1.0, 0.0]])
    retriever.model = SimpleNamespace(encode=lambda *args, **kwargs: __import__("numpy").array([[1.0, 0.0]]))
    retriever.queries = {}
    retriever.manifest = {"parameters": {"pool_per_retriever": 64, "rrf_k": 60}}
    rows, audit = retriever.query("literal", mode="vector", limit=1)
    assert [row["id"] for row in rows] == ["b"]
    assert audit["retrieval_mode"] == "vector"
    assert "bm25_posting_visits" not in audit["work"]


def test_vector_prompt_and_locate_return_numbered_original_lines(tmp_path):
    assert "不使用知识图谱、BM25、字面精确匹配" in vector.prompt({})
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    source = corpus / "a.txt"
    source.write_text("alpha\nbeta\n")
    engine = SimpleNamespace(
        options={"navigation_only": False}, corpus=corpus,
        files={"a.txt": ["alpha", "beta"]},
        manifest={"a.txt": {"sha256": vector.qa.digest(source.read_bytes())}},
        graph_path=None,
        retriever=SimpleNamespace(query=lambda *args, **kwargs: ([{
            "id": "passage", "path": "a.txt", "start": 1, "end": 2,
        }], {"work": {}, "retrieval_mode": "vector"})),
    )
    session = vector.Session(engine, "retrieval_first", "question")
    result, accounting = session.dispatch({
        "action": "locate", "translation": "", "query": "", "needs": []
    }, 6000)
    assert result["items"][0]["text"] == "1: alpha\n2: beta"
    assert session.seen == {"a.txt": {"1": "alpha", "2": "beta"}}
    assert accounting["actual_graph_loaded"] is False
