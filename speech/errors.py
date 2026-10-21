"""Safe operational failures; no upstream messages or user text in logs."""
class ReferenceNotReady(ValueError):
    pass


class BackendFailure(RuntimeError):
    def __init__(self, code, message, retryable=True):
        super().__init__(message)
        self.code, self.retryable = code, retryable
