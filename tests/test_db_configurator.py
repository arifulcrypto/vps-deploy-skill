"""Test 3X-UI SQLite script generator."""
from scripts.db_configurator import generate_remote_sqlite_script


def test_script_compiles_cleanly():
    script = generate_remote_sqlite_script(
        client_uuid="00000000-0000-0000-0000-000000000001",
        sub_id="sub123",
        email="test@example.com",
        password="normal_password",
        hy2_port=30001,
        reality_port=20001,
        cf_port=443,
        domain="node.example.com",
        cert_path="/path/cert.pem",
        key_path="/path/key.pem",
    )
    code_obj = compile(script, "<test>", "exec")
    assert code_obj is not None


def test_script_compiles_with_special_characters():
    tricky_password = """test"pass'with\\slash$and{braces}"""
    script = generate_remote_sqlite_script(
        client_uuid="00000000-0000-0000-0000-000000000001",
        sub_id="sub123",
        email="test@example.com",
        password=tricky_password,
        hy2_port=30002,
        reality_port=20002,
    )
    code_obj = compile(script, "<test_tricky>", "exec")
    assert code_obj is not None
