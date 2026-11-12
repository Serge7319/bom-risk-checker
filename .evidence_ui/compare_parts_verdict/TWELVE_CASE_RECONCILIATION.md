# Twelve-case limit reconciliation

Preserved Match/Different for known, comparable magnitudes. Unsupported comparisons stay Needs data.

| Case | Values | Role / mode | Units | Conditions | Verdict | Why |
| --- | --- | --- | --- | --- | --- | --- |
| Capacitor rated voltage | 50V vs 25V | max / LIMIT_GE | V | none | Different | Absolute ratings, comparable units |
| Capacitor PDF rated voltage | 50V vs 25V | max / LIMIT_GE | V | none | Different | Same absolute-rating rule |
| Resistor power | 0.1W vs 0.125W | max / LIMIT_GE | W | none | Different | Absolute ratings |
| Resistor DigiKey power | 0.1W vs 0.125W / 0.063W | max / LIMIT_GE | W | none | Different | Absolute ratings |
| Inductor Isat | 1A vs 0.5A | max / LIMIT_GE | A | none | Different | Absolute ratings |
| Inductor DigiKey DCR / Isat | 20 vs 25 mOhm; 5A vs 2A | max / LIMIT_LE/GE | Ohm/A | none or matching | Different | Known magnitudes + units |
| Diode Vr | 40V vs 60V | max / LIMIT_GE | V | none | Different | Absolute ratings |
| Diode DigiKey Vr / Vf | 30 vs 40 V; 800 vs 450 mV | max | V | none | Different | Absolute ratings |
| BJT power / VCE(sat) | 225 vs 350 mW; 300 vs 250 mV @ 5mA,50mA | max | W/V | none / matching @ | Different | Matching @ conditions for VCE(sat) |
| MOSFET RDS(on) | 50 vs 40 mOhm | max / LIMIT_LE | Ohm | none | Different | Absolute ratings |
| MOSFET DigiKey RDS | 54 vs 40/120 mOhm @ Id,Vgs | max / LIMIT_LE | Ohm | matching @ | Different | Same Id/Vgs on both sides |
| Regulator dropout | 0.4 vs 0.25 V @ 600mA | max / LIMIT_LE | V | matching @ | Different | Same load condition |

Unsupported (Needs data) examples covered by regression:
- One side cites `@` condition, the other does not
- `@` conditions differ
- Typical/guaranteed roles without a class token
- Missing / unparseable units without a preferred storage unit
