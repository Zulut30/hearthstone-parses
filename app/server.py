from __future__ import annotations

import uvicorn

from .config import bind_host, bind_port


def main() -> None:
    uvicorn.run("app.main:app", host=bind_host(), port=bind_port(), proxy_headers=True)


if __name__ == "__main__":
    main()
