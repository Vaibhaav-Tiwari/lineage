from lineage.graph.subgraph import Fragment


def test_merge_dedupes_nodes_and_edges():
    a = Fragment(
        nodes=[{"id": "pep:1", "label": "PEP", "props": {}}],
        edges=[{"src": "pep:2", "dst": "pep:1", "type": "SUPERSEDES", "props": {}}],
    )
    b = Fragment(
        nodes=[{"id": "pep:1", "label": "PEP", "props": {}}, {"id": "pep:2", "label": "PEP", "props": {}}],
        edges=[
            {"src": "pep:2", "dst": "pep:1", "type": "SUPERSEDES", "props": {}},
            {"src": "pep:2", "dst": "pep:1", "type": "REFERENCES", "props": {}},
        ],
    )
    m = a.merge(b)
    assert sorted(n["id"] for n in m.nodes) == ["pep:1", "pep:2"]
    assert len(m.edges) == 2
    assert m.ids() == {"pep:1", "pep:2"}


def test_merge_does_not_mutate_inputs():
    a = Fragment(nodes=[{"id": "x", "label": "X", "props": {}}], edges=[])
    a.merge(Fragment(nodes=[{"id": "y", "label": "Y", "props": {}}], edges=[]))
    assert [n["id"] for n in a.nodes] == ["x"]
