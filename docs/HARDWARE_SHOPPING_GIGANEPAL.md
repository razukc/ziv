# Hardware shopping list — Ziv rung-H bring-up (local vs. import)

Sources: the BOM in [HAPTIC_COMPANION_PLAN.md](HAPTIC_COMPANION_PLAN.md) (§3, ~$35 pin)
and the authoritative parts list in [HARDWARE_BRINGUP.md](HARDWARE_BRINGUP.md) §1
(6× DRV2605L + TCA9548A + 6× LRA behind the mux). Prices scraped 2026-09-17;
giganepal states **prices exclude VAT (13% extra)**. ⚠ Re-verify price/stock at
order time — the plan's own discipline for week-1 ordering.

Bottom line: **the DRV2605L is stocked by no Nepali shop** (seven checked) — the
haptic front-end must be imported, and the cheapest verified landed path is
AliExpress in NPR; Amazon India is the fast-but-pricier path. Everything else
is local same-day.

## Available on giganepal.com (verified product pages)

| # | Part (BOM role) | Price | Link | Notes |
|---|---|---|---|---|
| 1 | **ESP32-S3 SuperMini dev board** — the MCU | ₨ 2,050 | [product](https://www.giganepal.com/product/esp32-s3-supermini-development-board/) | WiFi+BLE, USB-C. ⚠ Listing doesn't state flash/PSRAM — plan wants N16R8 (16 MB flash + 8 MB PSRAM); confirm variant with the seller before ordering |
| 2 | ESP32-S3 AIoT Camera board **with audio** — the Xiaozhi-class alternative | ₨ 6,600 | [search](https://www.giganepal.com/?s=ESP32-S3+AIoT&post_type=product) | Built-in audio I/O ≈ the plan's "board with mic"; closest match to the BOM's ~$10 Xiaozhi-class kit |
| 3 | **Li-Po 3.7 V 1100 mAh** — battery | ₨ 550 | [product](https://www.giganepal.com/product/3-7v-1100mah-li-po-rechargeable-battery-original-type/) | In stock; above the 400–600 mAh spec — fine, more runtime |
| 4 | Li-Po 3.7 V 600 mAh — battery (exact spec) | ₨ 350 | [product](https://www.giganepal.com/product/li-po-battery-3-7v-600mah-with-jst-connector/) | **Out of stock** at scrape time |
| 5 | 18650 3.7 V 5000 mAh (HONGZI) — battery alternative | ₨ 210 | [product](https://www.giganepal.com/product/3-7volt-5000mah-18650-li-ion-rechargeable-battery/) | In stock; pairs with #6 (not a wrist-size cell — bench power) |
| 6 | **TP4056 charging module** (18650/1S Li-ion) | ₨ 180 | [product](https://www.giganepal.com/product/charging-module-18650-lithium-battery-charger-board/) | The BOM's "charger/boost" charging half |
| 7 | **Push Button Switch (DIP), 5 pcs** — braille chord keys | ₨ 50 | [search](https://www.giganepal.com/?s=push+button+switch&post_type=product) | ×2 packs = 6 keys + spares (₨ 100) |
| 8 | PUSH SWITCH LONG HEAD-4 PIN — alt button | ₨ 10 | [search](https://www.giganepal.com/?s=PUSH+SWITCH+LONG+HEAD&post_type=product) | |
| 9 | **Breadboard large GL-12, 840 pts** (×2 per bring-up doc) | ₨ 175 | [search](https://www.giganepal.com/?s=breadboard&post_type=product) | ₨ 350 for the two the doc calls for |
| 10 | Breadboard small | ₨ 120 | same search | |
| 11 | **Jumper M/M 40-pin 10 cm** | ₨ 200 | [product](https://www.giganepal.com/product/male-to-male-jumper-wires-40-pin-10cm/) | |
| 12 | Jumper M/F 40 pc | ₨ 200 | [product](https://www.giganepal.com/product/male-to-female-jumper-wire-cable-40-pieces/) | |
| 13 | Jumper F/F 40 pc | ₨ 200 | [product](https://www.giganepal.com/product/jumper-wire-female-to-female-40-pcs/) | |
| 14 | **USB-A dock charger 5 V / 3 A (ERD TC-204)** — the motor rail | ₨ 510 | [product](https://www.giganepal.com/product/usb-a-dock-charger-15w-3amp/) | Matches HARDWARE_BRINGUP's "USB 5 V ≥ 3 A supply" for the DRV VIN rail |

**Buyable subtotal:** ₨ 4,340 (with #1, #3, 2× #7, 2× #9, 3× jumpers, #6, #14)
≈ **$32–36** at ~₨ 135/$ (⚠ rate at order time) + 13% VAT — inside the plan's
~$35 hardware share of the envelope.

## Nepali shop recon — DRV2605L & TCA9548A (2026-09-17)

Checked before committing to an import:

| Shop | Status | DRV2605L | TCA9548A |
|---|---|---|---|
| [giganepal.com](https://www.giganepal.com) | live (this doc's local list) | ✗ | ✗ |
| [Daraz Nepal](https://www.daraz.com.np) | live | ✗ (0 results) | **✓ Rs. 673**, Overseas fulfillment — [search](https://www.daraz.com.np/catalog/?q=tca9548a) |
| [himalayansolution.com](https://himalayansolution.com) | live | ✗ (search echoes homepage — no hits) | ✗ |
| roboticshop.com.np | **DNS dead** | — | — |
| automationnepal.com | **DNS dead** | — | — |
| mufaddal.com.np | **DNS dead** | — | — |
| neptronics.com.np | **DNS dead** | — | — |
| roboticsnepal.com | **timed out** | — | — |
| RoboNepal.com | **404 (gone)** | — | — |

Also on Daraz (useful, Overseas = AliExpress-fed): INMP441 I²S mic
**Rs. 641–945** ([search](https://www.daraz.com.np/catalog/?q=inmp441));
**ERM coin vibration motors Rs. 199–329 from local Kathmandu sellers**
([search](https://www.daraz.com.np/catalog/?q=vibration+motor)) — the plan's
⚠ MVP fallback, in-country in days. LRA actuators: **0 results** on Daraz —
import-only or fall back to ERM.

## Import options — verified prices

### AliExpress (NPR geo-priced; ships to Nepal, ~2–4 weeks) — cheapest landed

- **DRV2605L breakout modules: Rs. 165–827/unit**, hundreds of sales —
  [search](https://www.aliexpress.com/w/wholesale-drv2605l.html). 6 units ≈
  **Rs. 1,000–4,900** (assume mid-range ~Rs. 3,000); most listings ship
  free/cheap to Nepal.
- TCA9548A: Rs. ~150–300 (same Overseas pipeline as the Daraz listing).
- INMP441: Rs. ~300–600 (the mic is a plan-dodgeable item — #2's on-board
  audio works).
- LRA coin actuators: exists but thin listings; ERM from Daraz local is the
  practical MVP start.

### Amazon India (₹; fast 3–7-day regional leg + int'l ship + duty)

| Item | Price | Link |
|---|---|---|
| **SmartElex DRV2605L breakout, 2-pack** | **₹ 619** (₹309.50/unit) | [search](https://www.amazon.in/s?k=DRV2605L+haptic+motor+driver) |
| SmartElex DRV2605 breakout (single) | ₹ 1,059 | same search |
| DRV2605L breakout (generic) | ₹ 1,977 | same search |
| DRV2605L kit (driver + 3 vibration motors) | ₹ 4,475 | same search |

6 drivers = 3 × 2-packs = **₹ 1,857 ≈ Rs. 3,000** + international shipping
(typically ₹1,200–2,500 for this weight) + 13% VAT + customs →
**~Rs. 4,500–6,500 landed**, 1–2 weeks. ⚠ Amazon.in's Nepal eligibility is
cart-dependent — verify at checkout with a Nepali address; a Kathmandu
forwarder is the fallback. Amazon.com/Adafruit direct (Adafruit #2305 at
$7.95 × 6 + Global shipping ≈ Rs. 8,400–10,400) is the most expensive path.

## Local vs. import — the comparison

| Path | Haptic front-end (6× DRV2605L + mux + motors) | Lead time | Total project cost* |
|---|---|---|---|
| **AliExpress (recommended)** | ~Rs. 3,000–4,300 (DRV 6× ~3,000 + mux ~250 + ERM local ~1,000) | 2–4 wks | ~**Rs. 8,500–9,500** ≈ $63–70 |
| **Amazon India** | ~Rs. 5,500–7,500 landed (drivers Rs. 4,500–6,500 + Daraz mux Rs. 673 + ERM local ~1,000) | 1–2 wks | ~Rs. 10,000–12,500 ≈ $75–95 |
| **All-Daraz hybrid** | mux Rs. 673 + ERM Rs. 1,500 + AliExpress DRVs | mixed | ~Rs. 8,000–10,000 |
| Plan's BOM pin | — | — | ~$35 hardware share |

\* local giganepal subtotal Rs. 4,340 + 13% VAT ≈ Rs. 4,900, plus the
front-end path above.

**Verdict:** the front-end doubles the plan's hardware pin no matter the path,
but **AliExpress keeps it near the pin** (import ≈ Rs. 3,500–4,300) while
Amazon India roughly doubles it again for speed. Practical split:

- **Order now, local (same-day):** everything in the giganepal table →
  stage-A/B bring-up is not blocked.
- **Order now, AliExpress:** 6× DRV2605L (the true long-lead item) +
  optionally the mux + INMP441 in the same parcel.
- **Order now, Daraz (arrives like domestic):** TCA9548A Rs. 673 + 6× ERM coin
  motors as the ⚠ MVP actuators — lets rung-H driver bring-up start **before**
  the AliExpress parcel lands, on the fallback motors the plan already defines.
- **Later, if LRAs matter:** import 6× LRA coin actuators once ERM has proven
  the driver chain (the plan's MVP fallback ordering, made explicit).
