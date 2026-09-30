# Project Vision

Sandia is moving from "a config editor with a leases table" toward a
professional DHCP/IP management and network operations console, while
staying a single self-hosted Python application (no frontend build step, no
database server beyond SQLite, the Ollama assistant optional).

Priorities, in order:

1. **Visualization as a first-class surface.** IP/subnet occupancy should be
   something you look at, not just a number. SVG, not a generic table -
   scannable, color-coded, directly actionable.
2. **Everything is contextual.** Right-click (or its equivalent) on any
   network object - IP, lease, reservation, subnet - and get the actions
   that actually apply to that object's current state. No dead menu items.
3. **Never touch the live config silently.** Every change goes through
   validate -> diff -> backup -> apply. This already exists and must not
   regress.
4. **Evidence-based troubleshooting.** When something is explained to the
   user (why a client isn't getting a lease, why a subnet won't hand out
   addresses), it's derived from real parsed state, never invented.
5. **Simplicity over framework.** Server-rendered HTML + htmx + vanilla JS
   has been sufficient for everything built so far and should remain the
   default; reach for something heavier only when a concrete feature
   actually requires it.
