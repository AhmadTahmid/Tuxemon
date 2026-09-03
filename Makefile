# Default target to run when `make` is called by itself
.PHONY: default
default: run

# Install dependencies
.PHONY: setup
setup:
	pip install -U -r ./requirements.txt

# Run the game
.PHONY: run
run:
	python ./run_tuxemon.py

# Run tests
.PHONY: test
test:
	tox -e py3

# Compile the observed legacy corpus into an evidence graph.
.PHONY: foundry-audit
foundry-audit:
	python -m foundry

.PHONY: foundry-build
foundry-build:
	python -m foundry.town

.PHONY: foundry-probe
foundry-probe:
	python -m foundry.runtime --probe

.PHONY: foundry-play
foundry-play:
	python -m foundry.runtime --play

# Format code
.PHONY: format
format:
	tox -e fmt
