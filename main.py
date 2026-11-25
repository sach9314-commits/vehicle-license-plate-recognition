"""Compatibility entry point for the integrated Drishti Drive application."""

from menu.app import app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
