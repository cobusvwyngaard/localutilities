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
  /** Passwords: shown as a password field, never logged or echoed back by the engine. */
  secret?: boolean;
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

const VIDEO_FILES = ['.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v', '.wmv', '.flv', '.mpg', '.mpeg', '.ts', '.mts', '.m2ts', '.3gp'];
const AUDIO_FILES = ['.mp3', '.m4a', '.aac', '.wav', '.flac', '.ogg', '.oga', '.opus', '.wma', '.aiff', '.aif', '.amr'];

// Phase 1 (DESIGN.md §5): the four requested tools, engine only for now. Browser versions of the
// media and PDF tools follow in phase 2.
export const tools: readonly ToolDef[] = [
  {
    id: 'download.media',
    title: 'Download video or audio',
    description: 'YouTube and other sites supported by yt-dlp. Only download what you have the right to.',
    category: 'download',
    runsIn: ['engine'],
    inputs: { kinds: ['url'], min: 1, max: 1 },
    params: {
      mode: {
        type: 'enum',
        label: 'Download',
        options: [
          { value: 'video', label: 'Video (MP4)' },
          { value: 'audio', label: 'Audio only' },
        ],
        default: 'video',
      },
      quality: {
        type: 'enum',
        label: 'Video quality (at most)',
        options: [
          { value: 'best', label: 'Best available' },
          { value: '1080', label: '1080p' },
          { value: '720', label: '720p' },
          { value: '480', label: '480p' },
        ],
        default: '1080',
      },
      audioFormat: {
        type: 'enum',
        label: 'Audio format (audio only)',
        options: [
          { value: 'm4a', label: 'M4A (AAC, usually no re-encoding)' },
          { value: 'mp3', label: 'MP3' },
          { value: 'opus', label: 'Opus' },
        ],
        default: 'm4a',
      },
      playlist: { type: 'boolean', label: 'Download the whole playlist', default: false },
      subtitles: { type: 'boolean', label: 'Subtitles (English and Afrikaans, as SRT files)', default: false },
      sponsorblock: { type: 'boolean', label: 'Cut out sponsor segments (SponsorBlock)', default: false },
    },
    requires: ['yt-dlp', 'deno', 'ffmpeg'],
  },
  {
    id: 'video.compress',
    title: 'Compress video',
    description: 'Smaller video files with presets for sharing, archiving and lectures, or a target size.',
    category: 'video',
    runsIn: ['engine'],
    inputs: { kinds: ['file'], accept: VIDEO_FILES, min: 1, max: 50 },
    params: {
      preset: {
        type: 'enum',
        label: 'Preset',
        options: [
          { value: 'share', label: 'Share (small): up to 720p, H.264' },
          { value: 'balanced', label: 'Balanced: up to 1080p, H.264' },
          { value: 'archive', label: 'Archive: HEVC, smaller but slower (older devices may not play it)' },
          { value: 'lecture', label: 'Screen recording or lecture: 1080p, 15 fps, mono audio' },
          { value: 'target', label: 'Target size (enter MB below)' },
        ],
        default: 'balanced',
      },
      targetMb: { type: 'number', label: 'Target size (for “Target size”)', min: 1, max: 100000, default: 25, step: 1, unit: 'MB' },
      hardware: { type: 'boolean', label: 'Fast (hardware encoder, if this computer has one)', default: false },
    },
    requires: ['ffmpeg', 'ffprobe'],
  },
  {
    id: 'video.convert',
    title: 'Convert video',
    description: 'Change the container format. Streams are copied without quality loss whenever possible.',
    category: 'video',
    runsIn: ['engine'],
    inputs: { kinds: ['file'], accept: VIDEO_FILES, min: 1, max: 50 },
    params: {
      target: {
        type: 'enum',
        label: 'Convert to',
        options: [
          { value: 'mp4', label: 'MP4' },
          { value: 'mkv', label: 'MKV' },
          { value: 'webm', label: 'WebM' },
          { value: 'mov', label: 'MOV' },
        ],
        default: 'mp4',
      },
    },
    requires: ['ffmpeg', 'ffprobe'],
  },
  {
    id: 'audio.compress',
    title: 'Compress audio',
    description: 'Smaller audio files for speech, podcasts or music. Also extracts the sound from videos.',
    category: 'audio',
    runsIn: ['engine'],
    inputs: { kinds: ['file'], accept: [...AUDIO_FILES, ...VIDEO_FILES], min: 1, max: 100 },
    params: {
      preset: {
        type: 'enum',
        label: 'Preset',
        options: [
          { value: 'speech', label: 'Speech, smallest: Opus 32 kbps mono' },
          { value: 'speech-mp3', label: 'Speech, compatible: MP3 64 kbps mono' },
          { value: 'podcast', label: 'Podcast: MP3 96 kbps mono, loudness normalised' },
          { value: 'music', label: 'Music: AAC 192 kbps (M4A)' },
          { value: 'music-mp3', label: 'Music, compatible: MP3 VBR high quality' },
        ],
        default: 'speech',
      },
    },
    requires: ['ffmpeg', 'ffprobe'],
  },
  {
    id: 'audio.convert',
    title: 'Convert audio',
    description: 'Change the audio format. The audio is copied without quality loss whenever possible.',
    category: 'audio',
    runsIn: ['engine'],
    inputs: { kinds: ['file'], accept: [...AUDIO_FILES, ...VIDEO_FILES], min: 1, max: 100 },
    params: {
      target: {
        type: 'enum',
        label: 'Convert to',
        options: [
          { value: 'mp3', label: 'MP3' },
          { value: 'm4a', label: 'M4A (AAC)' },
          { value: 'opus', label: 'Opus' },
          { value: 'ogg', label: 'OGG (Vorbis)' },
          { value: 'flac', label: 'FLAC (lossless)' },
          { value: 'wav', label: 'WAV (uncompressed)' },
        ],
        default: 'mp3',
      },
    },
    requires: ['ffmpeg', 'ffprobe'],
  },
  {
    id: 'pdf.unlock',
    title: 'Unlock PDF',
    description:
      'Removes printing/copying restrictions, or saves an unprotected copy of a PDF you know the password for. ' +
      'Removing restrictions from documents you do not own may breach the licence you received them under.',
    category: 'pdf',
    runsIn: ['engine'],
    inputs: { kinds: ['file'], accept: ['.pdf'], min: 1, max: 50 },
    params: {
      password: {
        type: 'text',
        label: 'Open password (only if the PDF will not open without one)',
        maxLength: 1024,
        default: '',
        secret: true,
      },
    },
    requires: ['pikepdf'],
  },
];
