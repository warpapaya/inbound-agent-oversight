from ledgerline_crm.seed import seed
from ledgerline_crm.store import Store


def test_kb_search_is_relevant_not_an_unconditional_policy_dump(tmp_path):
    store = Store(tmp_path / "crm.db", tmp_path / "audit.jsonl")
    seed(store)
    assert {d["id"] for d in store.search_knowledge_base("QuickBooks")} == {"kb-integrations"}
    assert "kb-policy" in {d["id"] for d in store.search_knowledge_base("commercial policy")}
    assert store.search_knowledge_base("nonsense-zebra") == []
