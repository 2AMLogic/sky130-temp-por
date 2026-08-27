# temp-por comp data (generated, public-sources-only)

Generated 2026-08-27 from the upstream comp library's `temp-por.md` entry by an internal, private-repo-only tool. This is a derived, filtered copy — regenerate rather than hand-edit. Every row below cites a public vendor datasheet or a public distributor pricing page; nothing internal survived extraction.

## Comparable parts

| Vendor | Part | Accuracy | Range | Iq | Slope | Package | Price | Source |
|---|---|---|---|---|---|---|---|---|
| Texas Instruments | LMT70 | ±0.36 °C max (−55…150 °C); ±0.05 °C typ / ±0.13 °C max (20…42 °C) — factory-trimmed, no field trim step | −55…+150 °C | 9.2 µA typ, 12 µA max | −5.19 mV/°C (NTC-style) | 0.88×0.88 mm WLCSP (DSBGA) | $0.701 (LMT70, ti.com store, single-unit tier) | Datasheet: [ti.com/lit/ds/symlink/lmt70.pdf](https://www.ti.com/lit/ds/symlink/lmt70.pdf) (SNIS187A). Pricing: [ti.com/product/LMT70](https://www.ti.com/product/LMT70) |
| Microchip | MCP9700A | −2.0…+4.0 °C max over the full −40…+125 °C range (±1 °C typ) | −40…+125 °C — **exact match to our operating range** | 6 µA typ, 12 µA max | 10.0 mV/°C typ | SOT-23-3 / SC70-5 / TO-92-3 | not fetched | Datasheet: [ww1.microchip.com/downloads/en/DeviceDoc/20001942G.pdf](https://ww1.microchip.com/downloads/en/DeviceDoc/20001942G.pdf) (DS20001942G) |
| Vendor | Part | Threshold (closest option) | Hysteresis | Iq | Reset pulse | Package | Price | Source |
|---|---|---|---|---|---|---|---|---|
| Texas Instruments | TPS3839K33 | 2.857–2.974 V (2.93 V typ, ±1% at 25 °C, factory-trimmed) — nearest fixed option to our 2.60 V typ | 29 mV typ | 150 nA typ, 500 nA max | 200 ms typ (120–350 ms), active-low push-pull | SOT23-3 / 1×1 mm X2SON | $0.278 (TPS3839K33DQNR, ti.com store, single-unit tier) | Datasheet: [ti.com/lit/ds/symlink/tps3839.pdf](https://www.ti.com/lit/ds/symlink/tps3839.pdf) (SBVS193D). Pricing: [ti.com/product/TPS3839](https://www.ti.com/product/TPS3839) |

## Sources

| URL | Establishes | Fetched |
|---|---|---|
| https://www.ti.com/lit/ds/symlink/lmt70.pdf | LMT70 accuracy/Iq/slope/package | 2026-08-24 |
| https://www.ti.com/product/LMT70 | LMT70 ti.com store pricing | 2026-08-24 |
| https://www.ti.com/lit/ds/symlink/tps3839.pdf | TPS3839K33 threshold/hysteresis/Iq/reset-pulse/package | 2026-08-24 |
| https://www.ti.com/product/TPS3839 | TPS3839K33DQNR ti.com store pricing | 2026-08-24 |

