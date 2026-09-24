from app.security import generate_api_key, hash_api_key, tokens_equal


def test_keys_are_unique_and_prefixed():
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100
    assert all(k.startswith("tp_") and len(k) > 40 for k in keys)


def test_hash_is_deterministic_and_not_plaintext():
    key = generate_api_key()
    assert hash_api_key(key) == hash_api_key(key)
    assert key not in hash_api_key(key)
    assert len(hash_api_key(key)) == 64


def test_tokens_equal():
    assert tokens_equal("abc", "abc")
    assert not tokens_equal("abc", "abd")
