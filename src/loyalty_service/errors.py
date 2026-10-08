class DomainError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 409, headers: dict | None = None):
        self.code, self.message, self.status_code = code, message, status_code
        self.headers = headers or {}
        super().__init__(message)
