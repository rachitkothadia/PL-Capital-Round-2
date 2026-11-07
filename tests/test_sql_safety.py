import pytest


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM portfolios",
        "SELECT 1; DROP TABLE holdings",
        "PRAGMA database_list",
        "ATTACH '/tmp/x' AS evil",
        "VACUUM INTO '/tmp/x'",
        "SELECT load_extension('x')",
        "SELECT readfile('.env')",
        "SELECT * FROM sqlite_master",
        "SELECT * FROM _dataset_meta",
        "SELECT * FROM pragma_table_info('portfolios')",
        "SELECT * FROM missing",
        "SELECT unknown_column FROM portfolios",
        "SELECT p.missing FROM portfolios p",
        "SELECT * FROM main.portfolios",
        "WITH x AS (DELETE FROM holdings RETURNING *) SELECT * FROM x",
        "WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT * FROM x",
        "SELECT randomblob(1000000000)",
        "SELECT current_weight FROM portfolios",
        "SELECT :unused FROM portfolios",
        "SELECT ? FROM portfolios",
    ],
)
def test_unsafe_queries_rejected_before_execution(db_path, sql):
    from pl_capital.errors import QueryError
    from pl_capital.sql_tool import execute

    with pytest.raises(QueryError):
        execute(db_path, sql, {})


def test_parameter_binding_not_interpolation(db_path):
    from pl_capital.sql_tool import execute

    attack = "Growth Equity Fund' OR 1=1 --"
    result = execute(
        db_path,
        "SELECT portfolio_name FROM portfolios WHERE portfolio_name=:name",
        {"name": attack},
    )
    assert result.rows == []
    assert execute(db_path, "SELECT COUNT(*) FROM portfolios", {}).rows == [[13]]


def test_cte_join_and_limits(db_path):
    from pl_capital.errors import QueryError
    from pl_capital.sql_tool import execute

    result = execute(
        db_path,
        "WITH x AS (SELECT portfolio_name FROM portfolios) SELECT * FROM x ORDER BY portfolio_name",
        {},
        max_rows=3,
    )
    assert result.row_count == 3
    assert result.truncated
    assert result.source_tables == ["portfolios"]
    with pytest.raises(QueryError, match="interrupted|budget"):
        execute(
            db_path,
            "SELECT COUNT(*) FROM holdings a CROSS JOIN holdings b CROSS JOIN holdings c CROSS JOIN holdings d",
            {},
            max_steps=1000,
        )


def test_unused_parameters_rejected(db_path):
    from pl_capital.errors import QueryError
    from pl_capital.sql_tool import execute

    with pytest.raises(QueryError):
        execute(db_path, "SELECT COUNT(*) FROM portfolios", {"extra": "x"})
