from research.coinsignals_btc_exit_search import allocation_grid, rank_configs


def test_allocation_grid_is_unique_normalized_and_diverse():
    grid = allocation_grid()
    assert len(grid) >= 20
    assert len(grid) == len(set(grid))
    assert all(abs(sum(weights) - 1) < 1e-5 for weights in grid)
    assert (0.25, 0.25, 0.25, 0.25) in grid
    assert (1.0, 0.0, 0.0, 0.0) in grid


def test_config_ranking_uses_train_not_oos():
    results = [
        {
            "id": "train_winner",
            "train": {"avg_r": 0.2, "profit_factor": 1.2},
            "oos": {"avg_r": -1.0},
        },
        {
            "id": "oos_winner",
            "train": {"avg_r": 0.1, "profit_factor": 2.0},
            "oos": {"avg_r": 2.0},
        },
    ]
    assert rank_configs(results)[0]["id"] == "train_winner"
