import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/testdb")

from app.core.security import get_active_branch, get_branch_code


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDb:
    def __init__(self, result):
        self._result = result

    def query(self, *args, **kwargs):
        return _FakeQuery(self._result)


class ActiveBranchSerializationTest(unittest.TestCase):
    def test_get_branch_code_accepts_string(self):
        self.assertEqual(get_branch_code("B10"), "B10")

    def test_get_branch_code_extracts_branch_model_field(self):
        branch = SimpleNamespace(branch_code="B17")
        self.assertEqual(get_branch_code(branch), "B17")

    def test_get_active_branch_returns_session_string_first(self):
        request = SimpleNamespace(session={"active_branch": "B12"})
        db = _FakeDb(SimpleNamespace(last_active_branch=SimpleNamespace(branch_code="B10")))

        result = get_active_branch(request, db, {"id": 1, "branch": "B1"})

        self.assertEqual(result, "B12")

    def test_get_active_branch_converts_db_branch_object_to_code(self):
        request = SimpleNamespace(session={})
        db = _FakeDb(SimpleNamespace(last_active_branch=SimpleNamespace(branch_code="B10")))

        result = get_active_branch(request, db, {"id": 1, "branch": "B1"})

        self.assertEqual(result, "B10")

    def test_get_active_branch_falls_back_to_user_branch_string(self):
        request = SimpleNamespace(session={})
        db = _FakeDb(None)

        result = get_active_branch(request, db, {"id": 1, "branch": "B5"})

        self.assertEqual(result, "B5")


if __name__ == "__main__":
    unittest.main()
