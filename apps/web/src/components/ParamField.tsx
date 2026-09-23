import type { ParamDef, ToolDef } from '@werkbank/shared';

export type ParamValue = string | number | boolean;

export function defaultsFor(tool: ToolDef): Record<string, ParamValue> {
  return Object.fromEntries(
    Object.entries(tool.params).map(([key, def]) => [key, def.type === 'text' ? (def.default ?? '') : def.default]),
  );
}

const control =
  'mt-1 block w-full rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm dark:border-zinc-700 dark:bg-zinc-950';

export function ParamField({
  name,
  def,
  value,
  disabled,
  onChange,
}: {
  name: string;
  def: ParamDef;
  value: ParamValue;
  disabled: boolean;
  onChange: (value: ParamValue) => void;
}) {
  const id = `param-${name}`;
  switch (def.type) {
    case 'enum':
      return (
        <label htmlFor={id} className="block text-sm font-medium">
          {def.label}
          <select id={id} className={control} value={String(value)} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
            {def.options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
      );
    case 'number':
      return (
        <label htmlFor={id} className="block text-sm font-medium">
          {def.label}
          <span className="mt-1 flex items-center gap-2">
            <input
              id={id}
              type="number"
              className={control.replace('mt-1 ', '')}
              min={def.min}
              max={def.max}
              step={def.step ?? (def.integer ? 1 : 'any')}
              value={String(value)}
              disabled={disabled}
              onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
            />
            {def.unit && <span className="text-zinc-500">{def.unit}</span>}
          </span>
        </label>
      );
    case 'boolean':
      return (
        <label htmlFor={id} className="flex items-center gap-2 text-sm">
          <input id={id} type="checkbox" checked={Boolean(value)} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
          {def.label}
        </label>
      );
    case 'text':
      return (
        <label htmlFor={id} className="block text-sm font-medium">
          {def.label}
          <input
            id={id}
            type={def.secret ? 'password' : 'text'}
            autoComplete="off"
            className={control}
            maxLength={def.maxLength}
            placeholder={def.placeholder}
            value={String(value)}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
          />
        </label>
      );
  }
}
