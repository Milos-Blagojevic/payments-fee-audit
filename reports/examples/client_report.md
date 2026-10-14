# Client report

From 2026-01 to 2026-06, Fernway billed its 40 clients EUR 1,049,178.87 against EUR 1,059,363.42 due under their pricing agreements: EUR 10,184.55 of revenue leakage (M09) across 126 invoice lines. After EUR 588,774.32 of provider fees and FX spread allocated to the clients' events, the margin is EUR 460,404.55 (M10), 1.635% of processed volume.

Amounts in EUR. *Leakage* is what the pricing agreement says Fernway should have billed minus what its invoice billed (positive = billed too little); findings are corrected on Fernway's own invoices, not disputed (A31). *Margin* is client billing minus the provider costs allocated to the client. Sources: `fct_client_billing_findings`, `fct_client_margin`; client × month rows are in `client_margin.csv`, findings by client, type and month in `client_findings.csv`.

Cost allocation (A09, A32): each provider fee goes to the client whose ledger event it belongs to (EUR 473,081.51); monthly provider charges without an event, minimums and volume adjustments, are split by the client's share of the volume the term is computed on (EUR 3,943.33); the FX spread of the client's converted payouts (M08) is a cost too (EUR 111,749.48). Fees on provider lines after the ledger watermark (EUR 2,525.35) belong to the next billing cycle and are left out.

## Leakage by type

| Type | Finding | Clients | Findings | Billed too little | Billed too much |
|---|---|---:|---:|---:|---:|
| L01 | Payout rail fee not billed to the client | 33 | 92 | 1,808.55 | 0.00 |
| L02 | Promotional price after its end date | 2 | 4 | 1,595.43 | 0.00 |
| L03 | FX markup not billed to the client | 1 | 6 | 4,463.26 | 0.00 |
| L04 | Volume discount above the agreed tier | 21 | 24 | 2,317.31 | 0.00 |

## Leakage by month

| Type | Finding | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 | 2026-06 |
|---|---|---:|---:|---:|---:|---:|---:|
| L01 | Payout rail fee not billed to the client | 0.00 | 0.00 | 0.00 | 617.85 | 608.40 | 582.30 |
| L02 | Promotional price after its end date | 0.00 | 0.00 | 0.00 | 0.00 | 797.01 | 798.42 |
| L03 | FX markup not billed to the client | 643.06 | 571.10 | 1,022.46 | 765.18 | 690.89 | 770.57 |
| L04 | Volume discount above the agreed tier | 354.36 | 340.87 | 640.80 | 110.96 | 423.02 | 447.30 |

## Leakage by client

Clients with at least one finding.

| Client | Name | Findings | Billed too little | Billed too much | Types |
|---|---|---:|---:|---:|---|
| CL003 | Hartley Stalls | 1 | 31.94 | 0.00 | L04 |
| CL004 | Pebblestone Goods | 4 | 262.78 | 0.00 | L01, L04 |
| CL005 | Ashgrove Goods | 4 | 36.00 | 0.00 | L01, L04 |
| CL006 | Hartley Makers | 3 | 1.35 | 0.00 | L01 |
| CL007 | Larkspur Swap | 3 | 571.50 | 0.00 | L01 |
| CL008 | Quillon Market | 3 | 554.40 | 0.00 | L01 |
| CL009 | Cobble Goods | 2 | 14.67 | 0.00 | L01, L04 |
| CL010 | Hartley Market | 3 | 23.40 | 0.00 | L01 |
| CL011 | Ashgrove Trading Post | 3 | 45.45 | 0.00 | L01 |
| CL012 | Alder Market | 3 | 56.62 | 0.00 | L01, L04 |
| CL013 | Yewdale Trading Post | 4 | 163.24 | 0.00 | L01, L04 |
| CL014 | Saltmarsh Swap | 1 | 128.49 | 0.00 | L04 |
| CL015 | Quillon Mart | 1 | 99.69 | 0.00 | L04 |
| CL016 | Pebblestone Mart | 5 | 230.35 | 0.00 | L01, L04 |
| CL017 | Saltmarsh Stalls | 3 | 9.00 | 0.00 | L01 |
| CL018 | Brackwater Collective | 3 | 9.45 | 0.00 | L01 |
| CL019 | Fernhill Collective | 4 | 116.86 | 0.00 | L01, L04 |
| CL020 | Driftwood Swap | 2 | 50.80 | 0.00 | L01, L04 |
| CL021 | Fernhill Mart | 4 | 61.12 | 0.00 | L01, L04 |
| CL022 | Rosemoor Mart | 10 | 4,785.92 | 0.00 | L01, L03, L04 |
| CL023 | Juniper Exchange | 4 | 29.78 | 0.00 | L01, L04 |
| CL025 | Inkwell Makers | 2 | 1,482.13 | 0.00 | L02 |
| CL026 | Ember Bazaar | 3 | 483.75 | 0.00 | L01 |
| CL027 | Cobble Market | 3 | 3.60 | 0.00 | L01 |
| CL028 | Cobble Swap | 7 | 167.88 | 0.00 | L01, L02, L04 |
| CL029 | Hartley Swap | 3 | 4.95 | 0.00 | L01 |
| CL030 | Ashgrove Swap | 3 | 28.40 | 0.00 | L01, L04 |
| CL031 | Dunmore Bazaar | 5 | 396.30 | 0.00 | L01, L04 |
| CL032 | Birchwood Market | 2 | 1.35 | 0.00 | L01 |
| CL033 | Dunmore Mart | 3 | 4.50 | 0.00 | L01 |
| CL034 | Yewdale Goods | 4 | 93.19 | 0.00 | L01, L04 |
| CL035 | Yewdale Bazaar | 4 | 93.05 | 0.00 | L01, L04 |
| CL036 | Driftwood Bazaar | 4 | 90.72 | 0.00 | L01, L04 |
| CL037 | Kestwick Trading Post | 3 | 1.80 | 0.00 | L01 |
| CL038 | Hartley Goods | 3 | 10.80 | 0.00 | L01 |
| CL039 | Gullwing Market | 4 | 33.47 | 0.00 | L01, L04 |
| CL040 | Oakfield Exchange | 3 | 5.85 | 0.00 | L01 |

## Margin per client

Whole period. *Event fees* are provider fees of the client's own events; *shared fees* its volume share of monthly charges; *FX spread* the M08 cost of its converted payouts.

| Client | Name | Volume | Billed | Leakage | Event fees | Shared fees | FX spread | Margin | Margin rate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| CL001 | Thistle Mart | 800,762.14 | 35,119.66 | 0.00 | 18,474.18 | -77.58 | 3,669.62 | 13,053.44 | 1.630% |
| CL002 | Nettlebed Market | 1,449,685.30 | 47,642.43 | 0.00 | 14,609.45 | 437.71 | 3,695.67 | 28,899.60 | 1.994% |
| CL003 | Hartley Stalls | 145,043.88 | 5,000.13 | 31.94 | 1,643.38 | 40.49 | 126.00 | 3,190.26 | 2.200% |
| CL004 | Pebblestone Goods | 945,825.66 | 38,564.68 | 262.78 | 11,499.55 | 289.63 | 1,663.76 | 25,111.74 | 2.655% |
| CL005 | Ashgrove Goods | 168,997.27 | 7,017.26 | 36.00 | 2,816.68 | 42.41 | 195.61 | 3,962.56 | 2.345% |
| CL006 | Hartley Makers | 135,702.59 | 5,025.60 | 1.35 | 3,021.90 | -12.79 | 119.70 | 1,896.79 | 1.398% |
| CL007 | Larkspur Swap | 1,829,709.32 | 76,839.89 | 571.50 | 49,844.45 | -176.78 | 20,362.22 | 6,810.00 | 0.372% |
| CL008 | Quillon Market | 1,897,597.27 | 77,678.59 | 554.40 | 48,975.11 | -185.08 | 18,439.54 | 10,449.02 | 0.551% |
| CL009 | Cobble Goods | 64,091.80 | 2,964.07 | 14.67 | 702.40 | 23.77 | 30.67 | 2,207.23 | 3.444% |
| CL010 | Hartley Market | 1,990,246.99 | 67,062.79 | 23.40 | 23,877.42 | 606.07 | 3,715.98 | 38,863.32 | 1.953% |
| CL011 | Ashgrove Trading Post | 84,072.56 | 5,478.16 | 45.45 | 2,640.21 | -9.25 | 1,162.82 | 1,684.38 | 2.003% |
| CL012 | Alder Market | 314,001.74 | 13,374.97 | 56.62 | 3,766.32 | 99.71 | 1,409.84 | 8,099.10 | 2.579% |
| CL013 | Yewdale Trading Post | 1,072,058.35 | 30,905.99 | 163.24 | 14,882.71 | 137.51 | 867.34 | 15,018.43 | 1.401% |
| CL014 | Saltmarsh Swap | 688,034.43 | 20,060.46 | 128.49 | 13,561.74 | -66.07 | 1,760.33 | 4,804.46 | 0.698% |
| CL015 | Quillon Mart | 599,256.89 | 23,375.93 | 99.69 | 12,936.87 | -58.41 | 2,253.53 | 8,243.94 | 1.376% |
| CL016 | Pebblestone Mart | 496,187.10 | 19,144.75 | 230.35 | 11,387.26 | -47.81 | 727.52 | 7,077.78 | 1.426% |
| CL017 | Saltmarsh Stalls | 1,085,764.33 | 46,768.51 | 9.00 | 15,620.50 | 335.66 | 2,921.68 | 27,890.67 | 2.569% |
| CL018 | Brackwater Collective | 949,393.57 | 35,808.53 | 9.45 | 11,192.15 | 287.11 | 1,224.88 | 23,104.39 | 2.434% |
| CL019 | Fernhill Collective | 576,964.80 | 26,664.53 | 116.86 | 8,177.82 | 177.39 | 2,497.36 | 15,811.96 | 2.741% |
| CL020 | Driftwood Swap | 242,357.03 | 8,140.02 | 50.80 | 2,818.59 | 76.77 | 570.34 | 4,674.32 | 1.929% |
| CL021 | Fernhill Mart | 276,556.33 | 8,480.31 | 61.12 | 3,221.32 | 80.36 | 171.17 | 5,007.46 | 1.811% |
| CL022 | Rosemoor Mart | 1,264,849.47 | 47,344.32 | 4,785.92 | 18,971.89 | 385.78 | 3,779.56 | 24,207.09 | 1.914% |
| CL023 | Juniper Exchange | 156,797.35 | 7,046.54 | 29.78 | 3,808.27 | -15.56 | 683.00 | 2,570.83 | 1.640% |
| CL024 | Rosemoor Trading Post | 736,743.88 | 31,858.83 | 0.00 | 8,574.33 | 224.57 | 3,345.63 | 19,714.30 | 2.676% |
| CL025 | Inkwell Makers | 843,388.01 | 22,999.88 | 1,482.13 | 16,422.14 | -81.26 | 1,890.50 | 4,768.50 | 0.565% |
| CL026 | Ember Bazaar | 1,792,588.76 | 75,204.99 | 483.75 | 45,931.23 | -178.65 | 21,197.44 | 8,254.97 | 0.461% |
| CL027 | Cobble Market | 357,708.46 | 11,378.58 | 3.60 | 7,502.80 | -33.36 | 230.30 | 3,678.84 | 1.028% |
| CL028 | Cobble Swap | 127,125.57 | 4,541.49 | 167.88 | 1,606.79 | 39.48 | 130.69 | 2,764.53 | 2.175% |
| CL029 | Hartley Swap | 673,097.02 | 24,979.93 | 4.95 | 8,433.09 | 211.27 | 1,673.19 | 14,662.38 | 2.178% |
| CL030 | Ashgrove Swap | 182,173.95 | 7,193.78 | 28.40 | 2,494.52 | 55.24 | 771.45 | 3,872.57 | 2.126% |
| CL031 | Dunmore Bazaar | 1,086,871.18 | 31,364.26 | 396.30 | 17,221.38 | 19.46 | 1,112.91 | 13,010.51 | 1.197% |
| CL032 | Birchwood Market | 416,687.17 | 16,431.78 | 1.35 | 8,904.09 | -40.68 | 517.58 | 7,050.79 | 1.692% |
| CL033 | Dunmore Mart | 590,678.58 | 20,251.60 | 4.50 | 6,824.28 | 177.50 | 1,053.86 | 12,195.96 | 2.065% |
| CL034 | Yewdale Goods | 472,218.94 | 18,031.46 | 93.19 | 5,183.58 | 149.46 | 1,462.64 | 11,235.78 | 2.379% |
| CL035 | Yewdale Bazaar | 365,018.19 | 15,203.89 | 93.05 | 4,691.16 | 113.49 | 698.26 | 9,700.98 | 2.658% |
| CL036 | Driftwood Bazaar | 490,943.80 | 19,739.78 | 90.72 | 6,295.79 | 146.41 | 2,111.99 | 11,185.59 | 2.278% |
| CL037 | Kestwick Trading Post | 234,678.23 | 7,616.63 | 1.80 | 2,893.71 | 74.13 | 189.86 | 4,458.93 | 1.900% |
| CL038 | Hartley Goods | 1,471,650.91 | 47,652.36 | 10.80 | 16,919.62 | 448.21 | 2,085.60 | 28,198.93 | 1.916% |
| CL039 | Gullwing Market | 187,789.41 | 7,030.43 | 33.47 | 4,204.24 | -18.03 | 514.04 | 2,330.18 | 1.241% |
| CL040 | Oakfield Exchange | 892,523.56 | 32,191.08 | 5.85 | 10,528.59 | 265.05 | 715.40 | 20,682.04 | 2.317% |
