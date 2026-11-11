# Vendored libraries of the extraction page

These are unmodified copies of the published npm files. The page has no build step and loads them from this folder.
To upgrade a library, replace its file with the one from the new npm tarball, then update this table and the licence
files.

| File | Package | Upstream file | SHA-256 | Licence |
|---|---|---|---|---|
| `ajv2020.min.js` | [ajv-dist](https://www.npmjs.com/package/ajv-dist) 8.17.1 (the browser bundles of [Ajv](https://ajv.js.org) 8.17.1, JSON Schema draft 2020-12) | `dist/ajv2020.min.js` | `d2f97a24636c44135e1ffffeea29656c06a1c1f71b315e958c88d0e8126c2100` | MIT, `LICENSE.ajv`; the bundle includes fast-deep-equal 3 (MIT, `LICENSE.fast-deep-equal`), fast-uri 3 (BSD-3-Clause, `LICENSE.fast-uri`) and json-schema-traverse 1 (MIT, `LICENSE.json-schema-traverse`) |
| `js-yaml.esm.min.mjs` | [js-yaml](https://www.npmjs.com/package/js-yaml) 5.5.0 | `dist/browser/js-yaml.esm.min.mjs` | `de0f5266d4312ab9cd564aba4217eb9cc98dcfd18bd59988aa7e0971e7c722b5` | MIT, `LICENSE.js-yaml` |

Ajv's licence comes from the ajv 8.17.1 package, because ajv-dist ships none. The licences of the bundled
dependencies come from fast-deep-equal 3.1.3, fast-uri 3.0.1 and json-schema-traverse 1.0.0. The `sourceMappingURL`
comments refer to source maps that are not copied here.
