from pathlib import Path


def test_migration_contains_overlap_exclusion_constraint():
    content = (Path(__file__).resolve().parents[1] / 'migrations/versions/0001_initial.py').read_text()
    assert 'EXCLUDE USING gist' in content
    assert 'tstzrange(starts_at, ends_at' in content
    assert "'confirmed','completed','no_show'" in content
