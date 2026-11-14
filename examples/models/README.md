# models

What you learn: model utilities. Read in this order:

1. `model_sizes.py`: Name a model by its size, not by its id (planned interface, decision D121)
2. `catalog_dates.py`: Which model a size means, and when it changes (planned interface, decision D121)
3. `fitted_parameters.py`: The same parameters on every model (planned interface, decision D121)
4. `emulated_features.py`: What a model cannot do is emulated, not refused (planned interface, decision D121)
5. `providers_together.py`: One client for the language, the embedding and the decision model (planned, decision D121)
6. `cohere.py`: Cohere embeddings through `skye.provider("cohere")` (Live)
7. `cost_tracking.py`: Estimating request cost with CostCalculator (Live)
8. `decision_model.py`: The DecisionModel Port (proposed-interface, guarded)
9. `retry_and_errors.py`: Provider errors and the client's own retries (Live)
10. `token_counting.py`: Counting tokens with TokenCounter (Live)

Run: `python examples/models/cohere.py`

What you see: printed results; with no key a scripted client answers and the example prints which mode ran.

What you need: `pip install skyeai`; a provider key only to call a real service.
