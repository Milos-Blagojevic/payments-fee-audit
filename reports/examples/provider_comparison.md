# Provider comparison

What each card segment's succeeded payments cost under the contract of the provider that processed them, and what they would have cost under the other card provider's contract. Payment-level fees only (interchange, scheme fee, markup and fixed fee, or the blended rate), each provider's own month volume for its tiers; refund and chargeback fees, minimums and volume discounts are left out (assumption A23). Amounts in EUR; a positive saving means the other contract would have been cheaper. Source: `fct_provider_comparison`.

The switch that would have saved the most: moving Brightpay's `eea_consumer` volume (EUR 10,307,622.05, 125,016 payments) to Northgate Acquiring's contract, EUR 102,581.19 from 2026-01 to 2026-06 (0.708% instead of 1.703% of volume).

## Whole period

| Segment | Processed by | Volume | Billed | Under own contract | Rate | Under the other contract | Rate | Saving if switched |
|---|---|---|---:|---:|---:|---:|---:|---:|
| eea_consumer | Brightpay | 10,307,622.05 | 176,554.71 | 175,563.44 | 1.703% | 72,982.25 (Northgate Acquiring) | 0.708% | 102,581.19 |
| eea_consumer | Northgate Acquiring | 15,339,887.65 | 116,713.66 | 109,259.17 | 0.712% | 268,640.64 (Brightpay) | 1.751% | -159,381.47 |
| other | Brightpay | 1,017,670.39 | 32,619.92 | 32,570.38 | 3.200% | 20,871.82 (Northgate Acquiring) | 2.051% | 11,698.56 |
| other | Northgate Acquiring | 1,490,661.70 | 31,528.69 | 30,643.97 | 2.056% | 48,476.81 (Brightpay) | 3.252% | -17,832.84 |

## By month

| Segment | Processed by | Month | Payments | Volume | Own contract | Other contract | Saving |
|---|---|---|---:|---:|---:|---:|---:|
| eea_consumer | Brightpay | 2026-01 | 18,479 | 1,566,041.62 | 26,545.36 | 12,406.48 | 14,138.88 |
| eea_consumer | Brightpay | 2026-02 | 17,960 | 1,517,692.38 | 25,738.05 | 12,018.88 | 13,719.17 |
| eea_consumer | Brightpay | 2026-03 | 22,060 | 1,851,016.02 | 31,429.90 | 12,825.19 | 18,604.71 |
| eea_consumer | Brightpay | 2026-04 | 21,483 | 1,765,704.13 | 30,090.97 | 11,716.75 | 18,374.22 |
| eea_consumer | Brightpay | 2026-05 | 22,733 | 1,814,479.92 | 31,086.09 | 12,088.80 | 18,997.29 |
| eea_consumer | Brightpay | 2026-06 | 22,301 | 1,792,687.98 | 30,673.07 | 11,926.15 | 18,746.92 |
| eea_consumer | Northgate Acquiring | 2026-01 | 28,658 | 1,981,904.78 | 15,979.88 | 34,910.74 | -18,930.86 |
| eea_consumer | Northgate Acquiring | 2026-02 | 27,344 | 1,903,688.76 | 15,356.81 | 33,488.37 | -18,131.56 |
| eea_consumer | Northgate Acquiring | 2026-03 | 35,919 | 2,509,851.45 | 17,724.15 | 44,119.09 | -26,394.94 |
| eea_consumer | Northgate Acquiring | 2026-04 | 38,847 | 2,772,581.48 | 18,681.87 | 48,528.13 | -29,846.26 |
| eea_consumer | Northgate Acquiring | 2026-05 | 43,109 | 3,126,436.87 | 21,035.18 | 54,548.83 | -33,513.65 |
| eea_consumer | Northgate Acquiring | 2026-06 | 41,634 | 3,045,424.31 | 20,481.28 | 53,045.48 | -32,564.20 |
| other | Brightpay | 2026-01 | 1,854 | 156,566.82 | 5,003.68 | 3,342.01 | 1,661.67 |
| other | Brightpay | 2026-02 | 1,768 | 157,960.70 | 5,022.98 | 3,370.01 | 1,652.97 |
| other | Brightpay | 2026-03 | 2,146 | 179,701.14 | 5,747.86 | 3,665.08 | 2,082.78 |
| other | Brightpay | 2026-04 | 2,105 | 176,696.39 | 5,650.36 | 3,523.83 | 2,126.53 |
| other | Brightpay | 2026-05 | 2,228 | 175,791.70 | 5,654.72 | 3,538.19 | 2,116.53 |
| other | Brightpay | 2026-06 | 2,133 | 170,953.64 | 5,490.78 | 3,432.70 | 2,058.08 |
| other | Northgate Acquiring | 2026-01 | 2,728 | 185,473.21 | 3,981.27 | 6,060.64 | -2,079.37 |
| other | Northgate Acquiring | 2026-02 | 2,710 | 181,780.67 | 3,915.30 | 5,948.80 | -2,033.50 |
| other | Northgate Acquiring | 2026-03 | 3,512 | 249,804.89 | 5,131.48 | 8,122.32 | -2,990.84 |
| other | Northgate Acquiring | 2026-04 | 3,812 | 272,067.71 | 5,480.96 | 8,842.87 | -3,361.91 |
| other | Northgate Acquiring | 2026-05 | 4,233 | 319,841.09 | 6,468.26 | 10,333.48 | -3,865.22 |
| other | Northgate Acquiring | 2026-06 | 3,999 | 281,694.13 | 5,666.70 | 9,168.70 | -3,502.00 |
