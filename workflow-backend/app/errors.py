class NotFoundError(Exception):
    """A requested resource doesn't exist. Rendered by app.main as 404 {"detail": ...}."""
