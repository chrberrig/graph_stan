from graph_stan import refactor as gs

def test_new_array_syntax():
    stan = """
    data { int N; array[N] int X; }
    """
    nodes, symbols = gs.parse_stan_string(stan)
    assert "X" in symbols
    assert symbols["X"].dims == ("N",)
    assert symbols["X"].base_type == "int"

def test_old_array_syntax():
    stan = """
    data { int N; int X[N]; }
    """
    nodes, symbols = gs.parse_stan_string(stan)
    assert "X" in symbols
    assert symbols["X"].dims == ("N",)
    assert symbols["X"].base_type == "int"

