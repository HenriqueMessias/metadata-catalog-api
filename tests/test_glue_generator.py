from __future__ import annotations

import pytest

# Dependências opcionais do emulador (requirements-glue-emulator.txt): sem elas, estes
# testes são pulados em vez de quebrar a coleta do `pytest` na instalação padrão.
pytest.importorskip("faker")

from scripts.glue_emulator.generator import TableGenerator


def test_same_seed_produces_identical_tables():
    first = TableGenerator(seed=42).generate_table("sales")
    second = TableGenerator(seed=42).generate_table("sales")

    assert first.table_name == second.table_name
    assert [c.name for c in first.columns] == [c.name for c in second.columns]
    assert first.owner_email == second.owner_email


def test_different_seeds_produce_different_tables():
    first = TableGenerator(seed=1).generate_table("sales")
    second = TableGenerator(seed=2).generate_table("sales")

    assert first.table_name != second.table_name


def test_every_table_has_an_id_primary_key_column():
    table = TableGenerator(seed=1).generate_table("sales")

    assert table.columns[0].name == "id"


def test_drift_columns_always_adds_a_column():
    generator = TableGenerator(seed=1)
    table = generator.generate_table("sales")

    drifted = generator.drift_columns(table.columns)

    assert len(drifted) >= len(table.columns) + 1 - 1  # +1 add, -1 possible removal
    original_names = {c.name for c in table.columns}
    new_names = {c.name for c in drifted}
    assert len(new_names - original_names) >= 1


def test_drift_columns_never_removes_the_primary_key():
    generator = TableGenerator(seed=1)
    table = generator.generate_table("sales")

    for _ in range(20):
        drifted = generator.drift_columns(table.columns)
        assert "id" in {c.name for c in drifted}


def test_drift_columns_never_nets_out_to_no_change():
    # Regression test: found by running the emulator end-to-end against a
    # live API with --seed 42 -- one table's added column was immediately
    # removed again by the same drift_columns() call, netting to zero
    # change and silently failing to bump schema_version.
    for seed in range(200):
        generator = TableGenerator(seed=seed)
        table = generator.generate_table("sales")
        before = [c.name for c in table.columns]

        drifted = generator.drift_columns(table.columns)
        after = [c.name for c in drifted]

        assert before != after, f"seed={seed} produced no net column change"
