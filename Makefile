.PHONY: up down logs gui test lattice smoke

up:            ## build + start the backend stack
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=50

gui:           ## run the control-room GUI on the host
	.venv/bin/pip2va-gui

test:
	.venv/bin/python -m pytest tests/ -q

lattice:       ## regenerate + numerically re-match the lattice
	.venv/bin/python scripts/gen_lattice.py
	.venv/bin/python scripts/match_lattice.py

smoke:         ## verify a running compose stack end to end
	.venv/bin/python scripts/smoke_compose.py
