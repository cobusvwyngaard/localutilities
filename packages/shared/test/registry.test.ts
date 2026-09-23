import { describe, expect, it } from 'vitest';
import { categories, tools, validateRegistry, type ToolDef } from '../src/index.ts';

const sample: ToolDef = {
  id: 'video.sample',
  title: 'Sample',
  description: 'A tool used only in tests.',
  category: 'video',
  runsIn: ['engine', 'browser'],
  inputs: { kinds: ['file'], accept: ['.mp4'], min: 1, max: 5 },
  params: {
    preset: {
      type: 'enum',
      label: 'Preset',
      options: [
        { value: 'share', label: 'Share (small)' },
        { value: 'balanced', label: 'Balanced' },
      ],
      default: 'balanced',
    },
    targetMb: { type: 'number', label: 'Target size', min: 1, max: 4000, default: 25, integer: true, unit: 'MB' },
    hardware: { type: 'boolean', label: 'Fast (hardware)', default: false },
  },
  requires: ['ffmpeg', 'ffprobe'],
  browserLimitBytes: 500 * 1024 * 1024,
};

describe('tool registry', () => {
  it('the shipped registry is valid', () => {
    expect(validateRegistry(tools, categories)).toEqual([]);
  });

  it('accepts a well-formed tool', () => {
    expect(validateRegistry([sample])).toEqual([]);
  });

  it('rejects duplicate ids and bad id shapes', () => {
    const errors = validateRegistry([sample, sample, { ...sample, id: 'Video/Bad' }]);
    expect(errors.some((e) => e.includes('duplicate id'))).toBe(true);
    expect(errors.some((e) => e.includes('"category.name"'))).toBe(true);
  });

  it('rejects an enum default that is not an option', () => {
    const bad: ToolDef = {
      ...sample,
      params: { preset: { type: 'enum', label: 'Preset', options: [{ value: 'a', label: 'A' }], default: 'b' } },
    };
    expect(validateRegistry([bad]).join()).toContain('is not an option');
  });

  it('rejects numbers outside their range and non-integer integers', () => {
    const bad: ToolDef = {
      ...sample,
      params: {
        a: { type: 'number', label: 'A', min: 0, max: 10, default: 11 },
        b: { type: 'number', label: 'B', min: 0, max: 10, default: 1.5, integer: true },
      },
    };
    const errors = validateRegistry([bad]).join('\n');
    expect(errors).toContain('default outside [min, max]');
    expect(errors).toContain('non-integer');
  });

  it('rejects unknown dependencies and categories', () => {
    const bad = { ...sample, category: 'nope', requires: ['ffmpeg', 'magic'] } as unknown as ToolDef;
    const errors = validateRegistry([bad]).join('\n');
    expect(errors).toContain('unknown category');
    expect(errors).toContain('unknown dependency "magic"');
  });

  it('rejects browserLimitBytes on engine-only tools', () => {
    const bad: ToolDef = { ...sample, runsIn: ['engine'] };
    expect(validateRegistry([bad]).join()).toContain('never runs in the browser');
  });
});
