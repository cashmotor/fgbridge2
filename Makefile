.PHONY: install run clean

install:
	pip install -r requirements.txt

run:
	python -m src.main

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf data/attachments/*
	rm -rf data/sessions/*
