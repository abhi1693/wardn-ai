import logging

import uvicorn

from adapter.app import create_app

app = create_app()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    uvicorn.run("adapter.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
