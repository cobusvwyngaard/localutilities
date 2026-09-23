import {
  categories as defaultCategories,
  dependencyIds,
  type CategoryDef,
  type ParamDef,
  type ToolDef,
} from './tools.ts';

const TOOL_ID = /^[a-z][a-z0-9]*(\.[a-z][a-z0-9-]*)+$/;
const PARAM_KEY = /^[a-z][a-zA-Z0-9]*$/;
const EXTENSION = /^\.[a-z0-9]+$/;

function checkParam(where: string, p: ParamDef): string[] {
  const errors: string[] = [];
  if (!p.label.trim()) errors.push(`${where}: label is empty`);
  switch (p.type) {
    case 'enum': {
      const values = p.options.map((o) => o.value);
      if (values.length === 0) errors.push(`${where}: enum has no options`);
      if (new Set(values).size !== values.length) errors.push(`${where}: duplicate enum values`);
      if (!values.includes(p.default)) errors.push(`${where}: default "${p.default}" is not an option`);
      break;
    }
    case 'number': {
      if (![p.min, p.max, p.default].every(Number.isFinite)) errors.push(`${where}: min/max/default must be finite`);
      if (p.min > p.max) errors.push(`${where}: min > max`);
      if (p.default < p.min || p.default > p.max) errors.push(`${where}: default outside [min, max]`);
      if (p.integer && ![p.min, p.max, p.default].every(Number.isInteger)) {
        errors.push(`${where}: integer param with non-integer min/max/default`);
      }
      if (p.step !== undefined && !(p.step > 0)) errors.push(`${where}: step must be > 0`);
      break;
    }
    case 'boolean':
      break;
    case 'text': {
      if (!Number.isInteger(p.maxLength) || p.maxLength < 1 || p.maxLength > 10_000) {
        errors.push(`${where}: maxLength must be an integer in [1, 10000]`);
      }
      if (p.default !== undefined && p.default.length > p.maxLength) errors.push(`${where}: default longer than maxLength`);
      break;
    }
    default:
      errors.push(`${where}: unknown param type`);
  }
  return errors;
}

/** Returns a list of problems; an empty list means the registry is valid. */
export function validateRegistry(
  tools: readonly ToolDef[],
  categories: readonly CategoryDef[] = defaultCategories,
): string[] {
  const errors: string[] = [];
  const categoryIds = new Set(categories.map((c) => c.id));
  const seen = new Set<string>();

  for (const t of tools) {
    const where = `tool "${t.id}"`;
    if (!TOOL_ID.test(t.id)) errors.push(`${where}: id must look like "category.name"`);
    if (seen.has(t.id)) errors.push(`${where}: duplicate id`);
    seen.add(t.id);
    if (!t.title.trim()) errors.push(`${where}: title is empty`);
    if (!categoryIds.has(t.category)) errors.push(`${where}: unknown category "${t.category}"`);
    if (t.runsIn.length === 0 || new Set(t.runsIn).size !== t.runsIn.length) {
      errors.push(`${where}: runsIn must be non-empty and without duplicates`);
    }
    for (const r of t.runsIn) if (r !== 'browser' && r !== 'engine') errors.push(`${where}: unknown runtime "${r}"`);
    if (t.browserLimitBytes !== undefined) {
      if (!t.runsIn.includes('browser')) errors.push(`${where}: browserLimitBytes set but tool never runs in the browser`);
      if (!Number.isInteger(t.browserLimitBytes) || t.browserLimitBytes <= 0) {
        errors.push(`${where}: browserLimitBytes must be a positive integer`);
      }
    }
    for (const d of t.requires) if (!dependencyIds.includes(d)) errors.push(`${where}: unknown dependency "${d}"`);

    const { inputs } = t;
    if (inputs.kinds.length === 0) errors.push(`${where}: inputs.kinds is empty`);
    if (!Number.isInteger(inputs.min) || !Number.isInteger(inputs.max) || inputs.min < 0 || inputs.min > inputs.max || inputs.max > 1000) {
      errors.push(`${where}: inputs.min/max must be integers with 0 <= min <= max <= 1000`);
    }
    for (const ext of inputs.accept ?? []) if (!EXTENSION.test(ext)) errors.push(`${where}: bad extension "${ext}"`);

    for (const [key, p] of Object.entries(t.params)) {
      if (!PARAM_KEY.test(key)) errors.push(`${where}: param key "${key}" must be camelCase`);
      errors.push(...checkParam(`${where} param "${key}"`, p));
    }
  }
  return errors;
}
