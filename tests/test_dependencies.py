from graph_stan import refactor as gs

def test_assignment_dependencies():
    stan = """
    data { int N; vector[N] x; }
    parameters { real alpha; real beta; }
    transformed parameters { vector[N] mu; mu = alpha + beta * x; }
    """
    nodes, symbols = gs.parse_stan_string(stan)
    assert "mu" in nodes
    assert nodes["mu"].dependencies == {"alpha", "beta", "x"}

def test_sampling_dependencies():
    stan = """
    data { int N; vector[N] y; }
    parameters { real mu; real sigma; }
    model { y ~ normal(mu, sigma); }
    """
    nodes, symbols = gs.parse_stan_string(stan)
    assert "y" in nodes
    assert nodes["y"].relation == "~"
    assert nodes["y"].dependencies == {"mu", "sigma"}

def test_target_increment_dependencies():
    stan = """
    data { real x; }
    parameters { real a; }
    model { target += normal_lpdf(x | a, 1); }
    """
    nodes, symbols = gs.parse_stan_string(stan)
    assert "target" in nodes
    assert nodes["target"].dependencies == {"x", "a"}

def test_loop_index_not_dependency():
    stan = """
    data { int N; vector[N] y; }
    parameters { real mu; real sigma; }
    model {
      for (i in 1:N) {
        y[i] ~ normal(mu, sigma);
      }
    }
    """
    nodes, symbols = gs.parse_stan_string(stan)
    assert "y" in nodes
    assert "i" not in nodes["y"].dependencies
    assert nodes["y"].dependencies == {"mu", "sigma"}

