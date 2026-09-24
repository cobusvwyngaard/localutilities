// Generates the media and PDFs the Phase 1 acceptance tests use (nothing binary is committed).
import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { join } from 'node:path';

function ffmpeg(args: string[]): void {
  execFileSync('ffmpeg', ['-v', 'error', '-y', ...args], { stdio: 'inherit' });
}

export default function globalSetup(): void {
  const media = process.env.E2E_MEDIA!;
  mkdirSync(media, { recursive: true });
  const clip = (seconds: number, size: string) => [
    '-f', 'lavfi', '-i', `testsrc2=s=${size}:r=25:d=${seconds}`,
    '-f', 'lavfi', '-i', `sine=frequency=440:d=${seconds}`,
    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest',
  ];
  ffmpeg([...clip(3, '320x240'), join(media, 'clip.mp4')]);
  ffmpeg([...clip(40, '1280x720'), join(media, 'long.mp4')]);

  // PDFs with pikepdf from the engine's environment: owner-restricted, user-password protected, and plain.
  const script = [
    'import pikepdf, sys',
    'restricted = pikepdf.Permissions(extract=False, print_highres=False, modify_other=False)',
    'for name, user in (("restricted.pdf", ""), ("locked.pdf", "open-sesame")):',
    '    pdf = pikepdf.new(); pdf.add_blank_page()',
    '    pdf.save(sys.argv[1] + "/" + name, encryption=pikepdf.Encryption(owner="owner-pw", user=user, allow=restricted))',
    'for name, pages in (("one.pdf", 1), ("two.pdf", 2)):',
    '    pdf = pikepdf.new()',
    '    for _ in range(pages): pdf.add_blank_page()',
    '    pdf.save(sys.argv[1] + "/" + name)',
  ].join('\n');
  execFileSync('uv', ['run', '--project', 'engine', '--frozen', 'python', '-c', script, media], { stdio: 'inherit' });
}
