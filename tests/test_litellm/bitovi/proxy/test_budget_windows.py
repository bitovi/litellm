from litellm_bitovi.proxy.budget.windows import current_model_budget_window


def test_current_model_budget_window_has_epoch() -> None:
    window = current_model_budget_window("1d")
    assert window.epoch == int(window.window_start.timestamp())
    assert window.reset_at > window.window_start
