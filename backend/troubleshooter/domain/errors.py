"""Expected operational failures, safe to expose without remote response bodies."""


class BudgetExceeded(Exception):
    pass


class ModelUnavailable(Exception):
    pass
