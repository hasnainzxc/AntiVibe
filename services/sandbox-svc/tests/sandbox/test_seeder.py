"""Tests for mock DB seeder."""

import tempfile
import json
from pathlib import Path
from sandbox.seeder import seed_to_json, _get_tenant_users, SeedResult, USER_A_ID, USER_B_ID


class TestTenantUsers:
    def test_10_users_total(self):
        users = _get_tenant_users()
        assert len(users) == 10

    def test_5_tenant1_students(self):
        users = _get_tenant_users()
        t1 = [u for u in users if u.tenant_id == 1]
        assert len(t1) == 5
        assert all(u.role == "student" for u in t1)

    def test_5_tenant2_admins(self):
        users = _get_tenant_users()
        t2 = [u for u in users if u.tenant_id == 2]
        assert len(t2) == 5
        assert all(u.role == "admin" for u in t2)

    def test_known_user_a_is_tenant1_student(self):
        users = _get_tenant_users()
        user_a = next(u for u in users if u.uid == USER_A_ID)
        assert user_a.tenant_id == 1
        assert user_a.role == "student"

    def test_known_user_b_is_tenant2_admin(self):
        users = _get_tenant_users()
        user_b = next(u for u in users if u.uid == USER_B_ID)
        assert user_b.tenant_id == 2
        assert user_b.role == "admin"


class TestSeedToJson:
    def test_json_written_with_correct_counts(self, tmp_path):
        result = seed_to_json(tmp_path)
        assert result.postgres["users"] == 10
        assert result.postgres["posts"] == 50
        assert result.postgres["settings"] == 10
        assert result.postgres["admins"] == 5
        assert result.postgres["universities"] == 2

    def test_output_file_exists(self, tmp_path):
        seed_to_json(tmp_path)
        seed_file = tmp_path / "seed.json"
        assert seed_file.exists()

    def test_output_has_both_tenants(self, tmp_path):
        seed_to_json(tmp_path)
        data = json.loads((tmp_path / "seed.json").read_text())
        assert len(data["tenant_users"]["tenant1"]) == 5
        assert len(data["tenant_users"]["tenant2"]) == 5

    def test_user_a_in_tenant1(self, tmp_path):
        seed_to_json(tmp_path)
        data = json.loads((tmp_path / "seed.json").read_text())
        assert "user-a-tenant1" in data["tenant_users"]["tenant1"]

    def test_user_b_in_tenant2(self, tmp_path):
        seed_to_json(tmp_path)
        data = json.loads((tmp_path / "seed.json").read_text())
        assert "user-b-tenant2" in data["tenant_users"]["tenant2"]
