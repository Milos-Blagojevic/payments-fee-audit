# Monthly provider cost report

Fees billed by each provider, by UTC month of the event, against the processed card volume. Amounts in EUR. *Effective rate* is fees billed ÷ processed volume; *markup rate* is the acquirer markup ÷ volume (Northgate only; Brightpay bills one blended fee). *Difference* is billed − expected on the charges that could be checked; *pending* is billed but not checkable yet (ledger lag). Changes compare with the previous month. Kestrel bills payouts, so it has no card volume. Source: `fct_provider_costs`; every component and segment row is in `provider_costs.csv`.

## Totals by provider and month

| Provider | Month | Card volume | Lines | Fees billed | Pending | Difference | Effective rate | Fees vs prev. month | Rate vs prev. month |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Brightpay | 2026-01 | 1,722,608.44 | 21,962 | 31,727.24 | 0.00 | 214.86 | 1.842% |  |  |
| Brightpay | 2026-02 | 1,675,653.08 | 21,644 | 31,485.55 | 0.00 | 185.06 | 1.879% | -0.8% | +3.72 bp |
| Brightpay | 2026-03 | 2,030,717.16 | 26,571 | 38,563.11 | 0.00 | 872.47 | 1.899% | +22.5% | +2.00 bp |
| Brightpay | 2026-04 | 1,942,400.52 | 25,929 | 37,374.06 | 0.00 | 355.29 | 1.924% | -3.1% | +2.51 bp |
| Brightpay | 2026-05 | 1,990,271.62 | 27,483 | 38,619.70 | 0.00 | 861.61 | 1.940% | +3.3% | +1.63 bp |
| Brightpay | 2026-06 | 1,963,641.62 | 27,660 | 38,605.09 | 758.63 | 300.21 | 1.966% | 0.0% | +2.56 bp |
| Kestrel Payouts | 2026-01 |  | 10,424 | 24,647.32 | 0.00 | 711.38 |  |  |  |
| Kestrel Payouts | 2026-02 |  | 9,131 | 20,947.90 | 0.00 | 156.86 |  | -15.0% |  |
| Kestrel Payouts | 2026-03 |  | 10,144 | 23,335.54 | 0.00 | 217.21 |  | +11.4% |  |
| Kestrel Payouts | 2026-04 |  | 10,174 | 12,111.19 | 0.00 | 300.07 |  | -48.1% |  |
| Kestrel Payouts | 2026-05 |  | 9,906 | 11,959.47 | 0.00 | 276.60 |  | -1.3% |  |
| Kestrel Payouts | 2026-06 |  | 10,221 | 11,830.68 | 455.70 | 194.35 |  | -1.1% |  |
| Northgate Acquiring | 2026-01 | 2,167,377.99 | 126,402 | 19,963.16 | 0.00 | 27.74 | 0.921% |  |  |
| Northgate Acquiring | 2026-02 | 2,085,469.43 | 121,999 | 22,151.51 | 0.00 | 2,540.59 | 1.062% | +11.0% | +14.11 bp |
| Northgate Acquiring | 2026-03 | 2,759,656.34 | 159,876 | 26,430.81 | 0.00 | 2,547.37 | 0.958% | +19.3% | -10.44 bp |
| Northgate Acquiring | 2026-04 | 3,044,649.19 | 173,097 | 28,549.68 | 0.00 | 2,920.12 | 0.938% | +8.0% | -2.01 bp |
| Northgate Acquiring | 2026-05 | 3,446,277.96 | 192,200 | 32,543.89 | 0.00 | 3,298.87 | 0.944% | +14.0% | +0.66 bp |
| Northgate Acquiring | 2026-06 | 3,327,118.44 | 190,478 | 28,704.29 | 778.51 | 57.59 | 0.863% | -11.8% | -8.16 bp |

## By card segment

Payment, refund and chargeback fees whose payment has a known card segment.

| Provider | Segment | Month | Volume | Fees billed | Effective rate | Markup rate | Fees vs prev. month | Rate vs prev. month |
|---|---|---|---:|---:|---:|---:|---:|---:|
| Brightpay | eea_consumer | 2026-01 | 1,566,041.62 | 26,755.66 | 1.708% |  |  |  |
| Brightpay | eea_consumer | 2026-02 | 1,517,692.38 | 26,385.82 | 1.739% |  | -1.4% | +3.00 bp |
| Brightpay | eea_consumer | 2026-03 | 1,851,016.02 | 32,682.99 | 1.766% |  | +23.9% | +2.72 bp |
| Brightpay | eea_consumer | 2026-04 | 1,765,704.13 | 31,745.91 | 1.798% |  | -2.9% | +3.22 bp |
| Brightpay | eea_consumer | 2026-05 | 1,814,479.92 | 32,738.95 | 1.804% |  | +3.1% | +0.64 bp |
| Brightpay | eea_consumer | 2026-06 | 1,792,687.98 | 32,207.40 | 1.797% |  | -1.6% | -0.77 bp |
| Brightpay | other | 2026-01 | 156,566.82 | 5,014.84 | 3.203% |  |  |  |
| Brightpay | other | 2026-02 | 157,960.70 | 5,079.38 | 3.216% |  | +1.3% | +1.26 bp |
| Brightpay | other | 2026-03 | 179,701.14 | 5,784.24 | 3.219% |  | +13.9% | +0.32 bp |
| Brightpay | other | 2026-04 | 176,696.39 | 5,951.78 | 3.368% |  | +2.9% | +14.96 bp |
| Brightpay | other | 2026-05 | 175,791.70 | 5,782.92 | 3.290% |  | -2.8% | -7.88 bp |
| Brightpay | other | 2026-06 | 170,953.64 | 5,573.13 | 3.260% |  | -3.6% | -2.96 bp |
| Northgate Acquiring | eea_consumer | 2026-01 | 1,981,904.78 | 15,972.50 | 0.806% | 0.450% |  |  |
| Northgate Acquiring | eea_consumer | 2026-02 | 1,903,688.76 | 15,685.26 | 0.824% | 0.450% | -1.8% | +1.80 bp |
| Northgate Acquiring | eea_consumer | 2026-03 | 2,509,851.45 | 20,956.49 | 0.835% | 0.441% | +33.6% | +1.11 bp |
| Northgate Acquiring | eea_consumer | 2026-04 | 2,772,581.48 | 20,331.17 | 0.733% | 0.332% | -3.0% | -10.17 bp |
| Northgate Acquiring | eea_consumer | 2026-05 | 3,126,436.87 | 25,557.78 | 0.817% | 0.414% | +25.7% | +8.42 bp |
| Northgate Acquiring | eea_consumer | 2026-06 | 3,045,424.31 | 22,107.32 | 0.726% | 0.320% | -13.5% | -9.16 bp |
| Northgate Acquiring | other | 2026-01 | 185,473.21 | 3,990.32 | 2.151% | 0.450% |  |  |
| Northgate Acquiring | other | 2026-02 | 181,780.67 | 3,963.60 | 2.180% | 0.450% | -0.7% | +2.90 bp |
| Northgate Acquiring | other | 2026-03 | 249,804.89 | 5,474.32 | 2.191% | 0.440% | +38.1% | +1.10 bp |
| Northgate Acquiring | other | 2026-04 | 272,067.71 | 5,717.76 | 2.102% | 0.332% | +4.4% | -8.98 bp |
| Northgate Acquiring | other | 2026-05 | 319,841.09 | 6,984.11 | 2.184% | 0.417% | +22.1% | +8.20 bp |
| Northgate Acquiring | other | 2026-06 | 281,694.13 | 5,817.92 | 2.065% | 0.320% | -16.7% | -11.83 bp |

## Fees by component

| Provider | Component | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 |
|---|---|---:|---:|---:|---:|---:|---:|
| Brightpay | chargeback_fee | 0.00 | 455.00 | 965.00 | 1,680.00 | 1,485.00 | 1,400.00 |
| Brightpay | refund_fee | 60.00 | 119.00 | 131.60 | 130.40 | 141.80 | 141.20 |
| Brightpay | transaction_fee | 31,766.30 | 30,938.09 | 37,466.51 | 35,962.22 | 36,992.90 | 37,596.40 |
| Brightpay | volume_adjustment | -99.06 | -26.54 | 0.00 | -398.56 | 0.00 | -532.51 |
| Kestrel Payouts | payout_fee | 24,647.32 | 20,947.90 | 23,335.54 | 12,111.19 | 11,959.47 | 11,830.68 |
| Northgate Acquiring | chargeback_fee | 60.00 | 525.00 | 1,230.00 | 1,620.00 | 1,920.00 | 1,935.00 |
| Northgate Acquiring | fixed_fee | 1,255.48 | 1,202.24 | 1,577.24 | 1,706.40 | 1,893.80 | 1,876.36 |
| Northgate Acquiring | interchange | 7,698.83 | 7,483.39 | 10,031.03 | 10,970.52 | 12,632.41 | 12,140.45 |
| Northgate Acquiring | markup | 9,756.33 | 9,388.92 | 12,159.55 | 10,116.34 | 14,267.84 | 10,951.39 |
| Northgate Acquiring | markup_credit | -118.23 | -257.56 | -284.61 | -250.42 | -291.32 | -305.77 |
| Northgate Acquiring | monthly_minimum | 0.00 | 2,500.00 | 0.00 | 2,500.00 | 0.00 | 0.00 |
| Northgate Acquiring | refund_fee | 44.00 | 90.10 | 107.80 | 123.50 | 140.90 | 141.20 |
| Northgate Acquiring | scheme_fee | 1,266.75 | 1,219.42 | 1,609.80 | 1,763.34 | 1,980.26 | 1,965.66 |
