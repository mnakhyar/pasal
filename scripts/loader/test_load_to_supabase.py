"""Unit tests for load_to_supabase.py -- all Supabase calls are mocked."""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

os.environ.setdefault("SUPABASE_URL", "https://fake.supabase.co")
os.environ.setdefault("SUPABASE_KEY", "fake-key")

sys.path.insert(0, str(Path(__file__).parent))

from load_to_supabase import load_work, load_nodes_recursive

_CHAINABLE = ("select", "eq", "neq", "in_", "ilike", "or_", "match",
              "order", "range", "limit", "single", "upsert", "insert", "delete")


def _qm(data=None, count=0):
    """Return a chainable query mock with preset execute result."""
    m = MagicMock()
    for attr in _CHAINABLE:
        getattr(m, attr).return_value = m
    m.execute.return_value = MagicMock(data=data or [], count=count)
    return m


def _sb():
    """Return a mock Supabase client."""
    return MagicMock()


class TestLoadWork:
    def test_valid_work_returns_id(self):
        sb = _sb()
        mock = _qm(data=[{"id": 42}])
        sb.table.return_value = mock

        law = {
            "type": "UU", "frbr_uri": "/akn/id/act/uu/2003/13",
            "number": "13", "year": 2003,
            "title_id": "UU 13/2003", "status": "berlaku",
        }
        result = load_work(sb, law)
        assert result == 42

    def test_unknown_reg_type_falls_back_to_permen(self):
        sb = _sb()
        mock = _qm(data=[{"id": 99}])
        sb.table.return_value = mock

        law = {
            "type": "UNKNOWN_TYPE", "frbr_uri": "/a",
            "number": "1", "year": 2020,
            "title_id": "T", "status": "berlaku",
        }
        result = load_work(sb, law)
        # Unknown types fall back to PERMEN (id 9) rather than failing
        assert result is not None

    def test_exception_returns_none(self):
        sb = _sb()
        sb.table.return_value.upsert.return_value.execute.side_effect = Exception("db error")

        law = {
            "type": "UU", "frbr_uri": "/a",
            "number": "1", "year": 2020,
            "title_id": "T", "status": "berlaku",
        }
        result = load_work(sb, law)
        assert result is None

    def test_empty_result_returns_none(self):
        sb = _sb()
        mock = _qm(data=[])
        sb.table.return_value = mock

        law = {
            "type": "UU", "frbr_uri": "/a",
            "number": "1", "year": 2020,
            "title_id": "T", "status": "berlaku",
        }
        result = load_work(sb, law)
        assert result is None


class TestLoadNodesRecursive:
    def test_empty_list(self):
        sb = _sb()
        result = load_nodes_recursive(sb, work_id=1, nodes=[])
        assert result == []

    def test_single_pasal_returns_pasal_info(self):
        sb = _sb()
        mock = _qm(data=[{"id": 10}])
        sb.table.return_value = mock

        nodes = [{"type": "pasal", "number": "1", "content": "Text", "children": []}]
        result = load_nodes_recursive(sb, work_id=1, nodes=nodes)

        assert len(result) == 1
        assert result[0]["node_id"] == 10
        assert result[0]["number"] == "1"

    def test_nested_bab_pasal(self):
        sb = _sb()
        call_count = [0]
        ids = [100, 200]

        def mock_insert_side_effect(*args, **kwargs):
            m = MagicMock()
            idx = min(call_count[0], len(ids) - 1)
            m.execute.return_value = MagicMock(data=[{"id": ids[idx]}])
            call_count[0] += 1
            return m

        sb.table.return_value.insert.side_effect = mock_insert_side_effect

        nodes = [{
            "type": "bab", "number": "I", "heading": "Ketentuan Umum",
            "children": [
                {"type": "pasal", "number": "1", "content": "Definisi", "children": []},
            ],
        }]
        result = load_nodes_recursive(sb, work_id=1, nodes=nodes)

        assert len(result) == 1
        assert result[0]["number"] == "1"

    def test_parent_id_passed_to_children(self):
        sb = _sb()
        insert_calls = []

        def track_insert(data):
            insert_calls.append(data)
            m = MagicMock()
            m.execute.return_value = MagicMock(data=[{"id": len(insert_calls)}])
            return m

        sb.table.return_value.insert.side_effect = track_insert

        nodes = [{
            "type": "bab", "number": "I", "heading": "Test",
            "children": [
                {"type": "pasal", "number": "1", "content": "Text", "children": []},
            ],
        }]
        load_nodes_recursive(sb, work_id=1, nodes=nodes)

        # Second insert (pasal) should have parent_id = 1 (bab's id)
        assert len(insert_calls) == 2
        assert insert_calls[1]["parent_id"] == 1


