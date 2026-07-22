export const DATA_ROUTING_TIERS = ["normal", "amber", "red"] as const;

export type DataRoutingTier = (typeof DATA_ROUTING_TIERS)[number];

export type DataRoutingTierPolicy = {
  allowed_connectors: string[];
  llm_allowed: boolean;
};

export type DataRouting = Record<DataRoutingTier, DataRoutingTierPolicy>;

export const DENY_ALL_DATA_ROUTING: DataRouting = {
  normal: { allowed_connectors: [], llm_allowed: false },
  amber: { allowed_connectors: [], llm_allowed: false },
  red: { allowed_connectors: [], llm_allowed: false },
};

export class DataRoutingValidationError extends Error {
  constructor(message = "Invalid data-routing policy") {
    super(message);
    this.name = "DataRoutingValidationError";
  }
}

const CONNECTOR_SLUG = /^[a-z0-9][a-z0-9_.-]{0,127}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]) {
  const keys = Object.keys(value);
  return keys.length === expected.length && keys.every((key) => expected.includes(key));
}

/**
 * Validate the settings response at the browser boundary.
 *
 * TypeScript types disappear at runtime, so a cast here would let a malformed
 * or future-unknown policy paint a permissive UI. Rejecting anything outside
 * the backend contract keeps load and save confirmation fail closed.
 */
export function parseDataRouting(value: unknown): DataRouting {
  if (!isRecord(value) || !hasExactKeys(value, DATA_ROUTING_TIERS)) {
    throw new DataRoutingValidationError();
  }

  const parsed = {} as DataRouting;
  for (const tier of DATA_ROUTING_TIERS) {
    const policy = value[tier];
    if (
      !isRecord(policy) ||
      !hasExactKeys(policy, ["allowed_connectors", "llm_allowed"]) ||
      typeof policy.llm_allowed !== "boolean" ||
      !Array.isArray(policy.allowed_connectors)
    ) {
      throw new DataRoutingValidationError("Invalid data-routing tier policy");
    }

    const connectors: string[] = [];
    for (const connector of policy.allowed_connectors) {
      if (
        typeof connector !== "string" ||
        !CONNECTOR_SLUG.test(connector) ||
        connectors.includes(connector)
      ) {
        throw new DataRoutingValidationError("Invalid data-routing connector destination");
      }
      connectors.push(connector);
    }

    parsed[tier] = {
      allowed_connectors: connectors,
      llm_allowed: policy.llm_allowed,
    };
  }

  return parsed;
}

export function dataRoutingEquals(left: DataRouting, right: DataRouting): boolean {
  return DATA_ROUTING_TIERS.every(
    (tier) =>
      left[tier].llm_allowed === right[tier].llm_allowed &&
      [...left[tier].allowed_connectors].sort().join("\0") ===
        [...right[tier].allowed_connectors].sort().join("\0")
  );
}
