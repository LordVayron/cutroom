import type { SVGProps } from "react";

export function MarkIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden="true" {...props}>
      <path d="M16 2 29 16 16 30 3 16 16 2Z" stroke="currentColor" strokeWidth="1" />
      <path d="M22 10c-2-4-10-4-12 1-3 7 4 13 10 9M8 5c0 4-4 4-5 4M24 27c0-4 4-4 5-4" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
      <path d="m15 11 7 5-7 5V11Z" fill="currentColor" />
    </svg>
  );
}

export function PlusIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M10 4v12M4 10h12" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

export function ArrowIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M4 10h11M11 5l5 5-5 5" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  );
}

export function DownloadIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" {...props}>
      <path d="M10 3v10m0 0 4-4m-4 4L6 9M4 16h12" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

