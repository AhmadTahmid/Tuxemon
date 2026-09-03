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

.PHONY: foundry-evolve
foundry-evolve:
	python -m foundry.evolve

.PHONY: foundry-selfplay
foundry-selfplay:
	python -m foundry.selfplay

.PHONY: foundry-ecology
foundry-ecology:
	python -m foundry.ecology

.PHONY: foundry-playthrough
foundry-playthrough:
	python -m foundry.playthrough

.PHONY: foundry-probe
foundry-probe:
	python -m foundry.runtime --probe

.PHONY: foundry-play
foundry-play:
	python -m foundry.runtime --play

.PHONY: foundry-freeze
foundry-freeze:
	python buildconfig/setup_foundry_release.py build

.PHONY: foundry-certify
foundry-certify:
	python -m foundry.town
	python -m foundry.ecology
	python -m foundry.runtime --probe
	python -m foundry.selfplay
	python -m foundry.playthrough

.PHONY: foundry-release
foundry-release: foundry-certify
	python buildconfig/setup_foundry_release.py build
	python -m foundry.release

# Format code
.PHONY: format
format:
	tox -e fmt
