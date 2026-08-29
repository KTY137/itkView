// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-ddef35a370b7
/**
 * PDB test-type definitions in the shape the ITk Production Database really
 * returns — copied verbatim (read-only) out of a live itkFlow mirror's
 * `test_type_schema` table, which stores `getTestTypeByCode` unmodified.
 *
 * WHY THIS FILE EXISTS. Until 2026-08-27 every TestForm fixture in this repo
 * described a test's measurement fields under a `results` key. No PDB
 * definition does that: all 14 mirrored MODULE definitions carry **no
 * `results` key at all** and list every measurement field under
 * **`parameters`**. The generated form therefore rendered the handful of
 * `properties` and not one measurement field, while refusing to submit
 * without a result value — no test type could be recorded, and the suite was
 * green throughout. Fixtures for the form generator belong here, in the shape
 * the product actually receives.
 *
 * Verbatim except: the `componentType` block (a multi-kilobyte stage/test
 * catalogue the form never reads) is omitted, and where a definition is
 * truncated it says so. No personal data appears in a test-type definition
 * (`sys` is timestamps and a revision counter only).
 */
import type { TestSchemaDefinition, TestTypeSchema } from "../api";

/** `GLUE_WEIGHT` ("Module glue weights"), complete: 4 `properties`,
 * 19 `parameters` — every one a `float`/`single`, none required. */
export const glueWeightMirrorDefinition: TestSchemaDefinition =
{
  "id": "60308fafefb208000a6c01cf",
  "code": "GLUE_WEIGHT",
  "name": "Module glue weights",
  "description": "Weights associated with module gluing",
  "state": "active",
  "project": "S",
  "changeStage": false,
  "automaticGrading": false,
  "parameters": [
    {
      "code": "GW_SENSOR",
      "name": "Weight of sensor [g]",
      "description": "Weight of bare sensor [g]",
      "dataType": "float",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "rangeMin": null,
      "rangeMax": null
    },
    {
      "code": "GW_GLUE_H2",
      "name": "Weight of glue under hybrid 2 [g]",
      "description": "Weight of glue under hybrid 2 [g]",
      "dataType": "float",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "GW_HYBRID1",
      "name": "Weight of hybrid 1 (without tabs) [g]",
      "description": "Weight of hybrid 1 (without tabs) [g]",
      "dataType": "float",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "GW_GLUE_PB",
      "name": "Weight of glue under powerboard [g]",
      "description": "Glue weight under powerboard [g]",
      "dataType": "float",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "GW_HYBRID2",
      "name": "Weight of hybrid 2 (without tabs) [g]",
      "description": "Weight of hybrid 2 (without tabs) [g]",
      "dataType": "float",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "GW_GLUE_H1",
      "name": "Weight of glue under hybrid 1 [g]",
      "description": "Weight of glue under hybrid 1 [g]",
      "dataType": "float",
      "order": 4,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_MODULE_H1H2",
      "name": "Weight of module with hybrid 1 and hybrid 2 [g]",
      "description": "Weight of module with hybrid 1 and hybrid 2 [g]",
      "dataType": "float",
      "order": 6,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_GLUE_H1H2",
      "name": "Weight of glue under hybrids 1 and 2 combined [g]",
      "description": "Weight of glue under hybrids 1 and 2 combined [g]",
      "dataType": "float",
      "order": 8,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_MODULE_PB",
      "name": "Weight of module with only a powerboard [g]",
      "description": "Weight of module with only a powerboard [g]",
      "dataType": "float",
      "order": 9,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_PB",
      "name": "Weight of powerboard [g]",
      "description": "Weight of powerboard [g]",
      "dataType": "float",
      "order": 10,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_MODULE_H1PB",
      "name": "Weight of module with 1 hybrid and powerboard [g]",
      "description": "Weight of module with 1 hybrid and powerboard [g]",
      "dataType": "float",
      "order": 12,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_GLUE_H1PB",
      "name": "Weight of glue under hybrid 1 and powerboard combined [g]",
      "description": "Weight of glue under hybrid 1 and powerboard combined [g]",
      "dataType": "float",
      "order": 13,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_MODULE_H1H2PB",
      "name": "Weight of module with hybrid 1, hybrid 2 and powerboard [g]",
      "description": "Weight of module with hybrid 1, hybrid 2 and powerboard [g]",
      "dataType": "float",
      "order": 14,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_GLUE_H1H2PB",
      "name": "Weight of glue under hybrid 1, hybrid 2 and powerboard combined [g]",
      "description": "Weight of glue under hybrid 1, hybrid 2 and powerboard combined [g]",
      "dataType": "float",
      "order": 15,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_MODULE_H1",
      "name": "Weight of module with only 1 hybrid [g]",
      "description": "Weight of module with only 1 hybrid [g]",
      "dataType": "float",
      "order": 16,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_HYBRID1T",
      "name": "Weight of hybrid 1 (with tabs) [g]",
      "description": "Weight of hybrid 1 (with tabs) [g]",
      "dataType": "float",
      "order": 16,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_HYBRID2T",
      "name": "Weight of hybrid 2 (with tabs) [g]",
      "description": "Weight of hybrid 2 (with tabs) [g]",
      "dataType": "float",
      "order": 17,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_T1",
      "name": "Weight of hybrid 1 tabs [g]",
      "description": "Weight of hybrid 1 tabs [g]",
      "dataType": "float",
      "order": 18,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    },
    {
      "code": "GW_T2",
      "name": "Weight of hybrid 2 tabs [g]",
      "description": "Weight of hybrid 2 tabs [g]",
      "dataType": "float",
      "order": 19,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null
    }
  ],
  "properties": [
    {
      "code": "GW_METHOD",
      "name": "Glue application method",
      "order": 1,
      "description": "\"stencil\" or \"dispenser\"",
      "dataType": "string",
      "valueType": "single",
      "required": true
    },
    {
      "code": "GLUE_METHOD_V_H1",
      "name": "Version number of stencil or dispenser programme used for Hybrid 1",
      "order": 2,
      "description": "Version number of stencil or dispenser programme used for Hybrid 1",
      "dataType": "string",
      "valueType": "single",
      "required": false
    },
    {
      "code": "GLUE_METHOD_V_H2",
      "name": "Version number of stencil or dispenser programme used for Hybrid 2",
      "order": 3,
      "description": "Version number of stencil or dispenser programme used for Hybrid 2",
      "dataType": "string",
      "valueType": "single",
      "required": false
    },
    {
      "code": "GLUE_METHOD_V_PB",
      "name": "Version number of stencil or dispenser programme used for Powerboard",
      "order": 4,
      "description": "Version number of stencil or dispenser programme used for Powerboard",
      "dataType": "string",
      "valueType": "single",
      "required": false
    }
  ],
  "sys": {
    "cts": "2021-02-20T04:27:27.435Z",
    "mts": "2026-04-02T12:21:21.431Z",
    "rev": 32
  }
};

/** `HYBRID_TESTS_SUMMARY`, truncated to 3 of its 36 `parameters` — all 36
 * share this shape: `dataType: "testRun"`, a reference to another run
 * rather than a value a person types. The form can capture none of them,
 * which is a different situation from "you forgot to fill something in". */
export const hybridTestsSummaryMirrorDefinition: TestSchemaDefinition =
{
  "id": "64dffea90cdc7a0042370692",
  "code": "HYBRID_TESTS_SUMMARY",
  "name": "Hybrid Tests Summary",
  "description": "a summary of all hybrid tests for specific run number and institution",
  "state": "active",
  "project": "S",
  "automaticGrading": false,
  "parameters": [
    {
      "code": "H0-RESPONSE_CURVE_3PG",
      "name": "H0 Response Curve 3PG",
      "description": "",
      "dataType": "testRun",
      "order": 1,
      "required": false,
      "valueType": "single",
      "additional": false,
      "arrayDimensions": null,
      "objectDefinition": null,
      "rangeMin": null,
      "rangeMax": null,
      "multipleSelection": null,
      "codeTable": null,
      "thresholds": null,
      "children": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null
    },
    {
      "code": "H0-RESPONSE_CURVE_10PG",
      "name": "H0 Response Curve 10PG",
      "description": "",
      "dataType": "testRun",
      "order": 1,
      "required": false,
      "valueType": "single",
      "additional": false,
      "arrayDimensions": null,
      "objectDefinition": null,
      "rangeMin": null,
      "rangeMax": null,
      "multipleSelection": null,
      "codeTable": null,
      "thresholds": null,
      "children": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null
    },
    {
      "code": "H0-STROBE_DELAY",
      "name": "H0 Strobe Delay",
      "description": "",
      "dataType": "testRun",
      "order": 1,
      "required": false,
      "valueType": "single",
      "additional": false,
      "arrayDimensions": null,
      "objectDefinition": null,
      "rangeMin": null,
      "rangeMax": null,
      "multipleSelection": null,
      "codeTable": null,
      "thresholds": null,
      "children": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null
    }
  ],
  "properties": [],
  "plots": [],
  "sys": {
    "cts": "2023-08-18T23:28:41.307Z",
    "mts": "2024-05-12T17:23:54.419Z",
    "rev": 69
  }
};

/** `MODULE_METROLOGY`, complete: one enterable `float` plus five `object`
 * parameters (per-position maps), two of which the PDB marks required. */
export const moduleMetrologyMirrorDefinition: TestSchemaDefinition =
{
  "id": "604bcabf1f7cd9000a4ff897",
  "code": "MODULE_METROLOGY",
  "name": "Module Metrology",
  "description": "Metrology of modules",
  "state": "active",
  "project": "S",
  "changeStage": false,
  "automaticGrading": false,
  "parameters": [
    {
      "code": "CAP_HEIGHT",
      "name": "Capacitor heights [um]",
      "description": "Heights of capacitors [um]",
      "dataType": "object",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": 2,
      "objectDefinition": {
        "dimension1": "values",
        "dimension2": "values"
      },
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "SHIELDBOX_HEIGHT",
      "name": "Shield box height [um]",
      "description": "Shield box height [um]",
      "dataType": "float",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": null,
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "PB_POSITION",
      "name": "PB position Deviation [um]",
      "description": "Position Deviation in x and y of the PB [um]",
      "dataType": "object",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": 1,
      "objectDefinition": {
        "dimension1": "values",
        "dimension2": "values"
      },
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "HYBRID_POSITION",
      "name": "Hybrid position Deviation [um]",
      "description": "Position Deviation in x and y of the hybrid(s) [um]",
      "dataType": "object",
      "order": 1,
      "required": true,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": 1,
      "objectDefinition": {
        "dimension1": "values",
        "dimension2": "values"
      },
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "HYBRID_GLUE_THICKNESS",
      "name": "Hybrid glue thickness [um]",
      "description": "Glue thickness under the hybrid, measured at the locations in the QC document [um]",
      "dataType": "object",
      "order": 1,
      "required": true,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": 2,
      "objectDefinition": {
        "dimension1": "values",
        "dimension2": "values"
      },
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": {
        "*": {
          "min": null,
          "max": null,
          "nominal": null
        }
      },
      "children": null,
      "isArray": null
    },
    {
      "code": "PB_GLUE_THICKNESS",
      "name": "Powerboard glue thickness [um]",
      "description": "Glue thickness under powerboard, locations defined in QC documents [um]",
      "dataType": "object",
      "order": 1,
      "required": false,
      "additional": false,
      "valueType": "single",
      "arrayDimensions": null,
      "objectDefinition": {
        "dimension1": "values",
        "dimension2": "values"
      },
      "allAssociatedChildrenIsRequired": null,
      "associateChildren": null,
      "thresholds": null,
      "children": null,
      "isArray": null
    }
  ],
  "properties": [
    {
      "code": "MACHINE",
      "name": "Machine",
      "order": 1,
      "description": "Which machine was used to perform metrology",
      "dataType": "string",
      "valueType": "single",
      "required": true
    },
    {
      "code": "OPERATOR",
      "name": "Operator",
      "order": 2,
      "description": "Operator who performed the test",
      "dataType": "string",
      "valueType": "single",
      "required": true
    },
    {
      "code": "SCRIPT_VERSION",
      "name": "Script version",
      "order": 3,
      "description": "Upload script version: name of your data processing done in script, and ideally version number",
      "dataType": "string",
      "valueType": "single",
      "rangeMin": null,
      "rangeMax": null,
      "multipleSelection": null,
      "codeTable": null,
      "required": true
    }
  ],
  "sys": {
    "cts": "2021-03-12T20:10:39.174Z",
    "mts": "2022-09-02T12:25:23.274Z",
    "rev": 70
  }
};

/** Wrap a mirrored definition the way `GET /api/test-type-schemas` serves it. */
export function mirroredSchema(
  definition: TestSchemaDefinition,
  overrides: Partial<TestTypeSchema> = {},
): TestTypeSchema {
  const code = typeof definition.code === "string" ? definition.code : "UNKNOWN";
  const name = typeof definition.name === "string" ? definition.name : code;
  return {
    id: 1,
    component_type: "MODULE",
    test_code: code,
    name,
    synced_at: "2026-08-27T09:00:00Z",
    schema: definition,
    ...overrides,
  };
}
