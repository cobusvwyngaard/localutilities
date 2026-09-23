// The tool registry: every tool is declared once here and consumed by both the UI and the
// engine (via the generated dist/tools.json — run `npm run gen:registry` after any change).
// DESIGN.md §3.1. Only erasable TypeScript syntax is allowed in this package, so Node can run
// it directly (no enums, namespaces or parameter properties).

export type Category = 'download' | 'video' | 'audio' | 'pdf' | 'image' | 'document' | 'text';

export type Runtime = 'browser' | 'engine';

/** External programs and Python packages the engine reports in /api/health. */
export type DependencyId =
  | 'ffmpeg'
  | 'ffprobe'
  | 'deno'
  | 'yt-dlp'
  | 'pikepdf'
  | 'ghostscript'
  | 'tesseract'
  | 'libreoffice'
  | 'pandoc'
  | 'calibre';

export const dependencyIds: readonly DependencyId[] = [
  'ffmpeg',
  'ffprobe',
  'deno',
  'yt-dlp',
  'pikepdf',
  'ghostscript',
  'tesseract',
  'libreoffice',
  'pandoc',
  'calibre',
];

export interface EnumParam {
  type: 'enum';
  label: string;
  options: Array<{ value: string; label: string }>;
  default: string;
}

export interface NumberParam {
  type: 'number';
  label: string;
  min: number;
  max: number;
  default: number;
  integer?: boolean;
  step?: number;
  unit?: string;
}

export interface BooleanParam {
  type: 'boolean';
  label: string;
  default: boolean;
}

export interface TextParam {
  type: 'text';
  label: string;
  maxLength: number;
  default?: string;
  placeholder?: string;
}

export type ParamDef = EnumParam | NumberParam | BooleanParam | TextParam;

/** Drives the generated form. Keys are camelCase parameter names. */
export type ParamSchema = Record<string, ParamDef>;

export interface InputSpec {
  /** What the job accepts: uploaded/Inbox files, URLs, or both. */
  kinds: Array<'file' | 'url'>;
  /** Accepted file extensions, lower case with the dot (e.g. ".mp4"). Omit for any. */
  accept?: string[];
  min: number;
  max: number;
}

export interface ToolDef {
  id: string; // "video.compress"
  title: string;
  description: string;
  category: Category;
  runsIn: Runtime[];
  inputs: InputSpec;
  params: ParamSchema;
  /** Engine dependencies; the UI disables the tool with a fix-it message when one is missing. */
  requires: DependencyId[];
  /** Above this input size, prefer the engine. */
  browserLimitBytes?: number;
}

export interface CategoryDef {
  id: Category;
  title: string;
}

// South African English in all user-facing text.
export const categories: readonly CategoryDef[] = [
  { id: 'download', title: 'Download' },
  { id: 'video', title: 'Video' },
  { id: 'audio', title: 'Audio' },
  { id: 'pdf', title: 'PDF' },
  { id: 'image', title: 'Images' },
  { id: 'document', title: 'Documents' },
  { id: 'text', title: 'Text' },
];

// Phase 0: the registry is intentionally empty. Tools arrive from Phase 1 (DESIGN.md §9).
export const tools: readonly ToolDef[] = [];
