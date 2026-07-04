.PHONY: up down logs gui test lattice smoke

up:            ## build + start the backend stack
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=50

gui:           ## run the control-room GUI on the host
	.venv/bin/pip2va-gui

gui-web:       ## serve the full GUI in a browser (noVNC on :6080)
	docker compose up -d --build web-gui
	@echo "GUI in browser:  http://localhost:6080/vnc.html  (or http://gb10:6080/vnc.html)" 

test:
	.venv/bin/python -m pytest tests/ -q

lattice:       ## regenerate + numerically re-match the lattice
	.venv/bin/python scripts/gen_lattice.py
	.venv/bin/python scripts/match_lattice.py

smoke:         ## verify a running compose stack end to end
	.venv/bin/python scripts/smoke_compose.py

reset:         ## nuclear reset: wipe all machine state, reboot to design
	docker compose down
	docker compose up -d
	@echo "waiting for MPS baseline capture..."
	@until .venv/bin/python -c "import redis,sys; r=redis.Redis(); \
	sys.exit(0 if any(f.get(b'kind')==b'armed' for _,f in \
	r.xrevrange('stream:mps.events',count=5)) else 1)" 2>/dev/null; \
	do sleep 3; done
	@.venv/bin/python -c "import redis; r=redis.Redis(); \
	st={k.decode():v.decode() for k,v in r.hgetall('state:beam').items()}; \
	print('MACHINE READY: W=%.1f MeV  T=%.4f' % \
	(float(st['w_out']), float(st['transmission'])))" 
