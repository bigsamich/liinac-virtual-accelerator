# 06 — Remote & mobile

## Browser GUI — http://gb10:6080/vnc.html
The full PyQt GUI streamed via noVNC (identical, software-GL 3D).
Session persists across disconnects like tmux. Unauthenticated on the
LAN — keep it inside the lab network.

## Phone dashboard — http://gb10:6081
Single-column, thumb-first:
- Permit banner + big numbers (W, T%, mA, worst BLM).
- **Trend sparklines** (transmission, worst BLM, energy, current) with
  30 min / 5 min / 30 s range buttons (1 Hz sampling).
- Recent machine events.
- **Studies card**: what's running (live step counter) and the shared
  queue → "manage" opens the full studies page: AI planning, preset
  chips (tap to queue), Run next, Abort+restore, result reports and AI
  analysis. Results from phone-started runs auto-persist to the
  knowledge base.
- **Ask-the-machine** box.
- "full control room" → the streamed GUI with **Interact / Pan-Zoom
  modes**: Interact passes touches to the app; Pan/Zoom makes pinch
  zoom your *view* (never the plots), + / − / Fit buttons.
All buttons flash green on tap and show busy states.
