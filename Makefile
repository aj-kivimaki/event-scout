.PHONY: rebuild test

rebuild:
	docker compose build python-api && docker compose up -d python-api

test:
	python -m pytest
